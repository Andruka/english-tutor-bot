"""FastAPI backend for the Telegram Mini App placement test."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Annotated
from urllib.parse import parse_qsl

import aiosqlite
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from bot.services.placement_test_service import (
    DEFAULT_QUESTION_COUNT,
    evaluate_test,
    select_test_questions,
)


class InitDataAuthError(ValueError):
    """Raised when Telegram WebApp initData cannot be trusted."""


@dataclass(frozen=True)
class TelegramInitDataAuth:
    """Trusted user data extracted from verified Telegram WebApp initData."""

    user_id: int
    user: dict[str, Any]
    auth_date: int
    query_id: str | None
    raw: dict[str, str]


class PlacementSubmitRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    answers: dict[str, str] = Field(default_factory=dict)


@dataclass(frozen=True)
class MiniAppSettings:
    db_path: str
    bot_token: str
    init_data_max_age_seconds: int = 24 * 60 * 60


def validate_telegram_init_data(
    init_data: str,
    *,
    bot_token: str,
    max_age_seconds: int = 24 * 60 * 60,
    now: int | None = None,
) -> TelegramInitDataAuth:
    """Validate Telegram WebApp initData with the official HMAC scheme."""
    if not init_data:
        raise InitDataAuthError("missing_init_data")
    if not bot_token:
        raise InitDataAuthError("missing_bot_token")

    values = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received_hash = values.pop("hash", "")
    if not received_hash:
        raise InitDataAuthError("missing_hash")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(received_hash, expected_hash):
        raise InitDataAuthError("invalid_hash")

    try:
        auth_date = int(values.get("auth_date", ""))
    except ValueError as exc:
        raise InitDataAuthError("invalid_auth_date") from exc
    current_time = int(time.time()) if now is None else int(now)
    if auth_date > current_time + 60:
        raise InitDataAuthError("invalid_auth_date")
    if current_time - auth_date > max_age_seconds:
        raise InitDataAuthError("expired_init_data")

    try:
        user = json.loads(values.get("user", "{}"))
    except json.JSONDecodeError as exc:
        raise InitDataAuthError("invalid_user") from exc
    if not isinstance(user, dict):
        raise InitDataAuthError("invalid_user")
    try:
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InitDataAuthError("missing_user_id") from exc

    return TelegramInitDataAuth(
        user_id=user_id,
        user=user,
        auth_date=auth_date,
        query_id=values.get("query_id"),
        raw=values,
    )


def create_miniapp_api(
    *,
    db_path: str,
    bot_token: str,
    init_data_max_age_seconds: int = 24 * 60 * 60,
) -> FastAPI:
    """Create FastAPI app for Telegram Mini App placement endpoints."""
    app = FastAPI(title="English Tutor Mini App API")
    settings = MiniAppSettings(
        db_path=db_path,
        bot_token=bot_token,
        init_data_max_age_seconds=init_data_max_age_seconds,
    )

    async def current_auth(
        x_telegram_init_data: Annotated[str | None, Header()] = None,
    ) -> TelegramInitDataAuth:
        try:
            return validate_telegram_init_data(
                x_telegram_init_data or "",
                bot_token=settings.bot_token,
                max_age_seconds=settings.init_data_max_age_seconds,
            )
        except InitDataAuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/placement/questions")
    async def get_placement_questions(
        auth: TelegramInitDataAuth = Depends(current_auth),
    ) -> dict[str, Any]:
        session_id = _session_id(auth)
        questions = select_test_questions(
            user_id=auth.user_id,
            seed=session_id,
            count=DEFAULT_QUESTION_COUNT,
        )
        return {
            "session_id": session_id,
            "questions": [_public_question(question) for question in questions],
        }

    @app.post("/api/placement/submit")
    async def submit_placement_test(
        request: PlacementSubmitRequest,
        auth: TelegramInitDataAuth = Depends(current_auth),
    ) -> dict[str, Any]:
        questions = select_test_questions(
            user_id=auth.user_id,
            seed=request.session_id,
            count=DEFAULT_QUESTION_COUNT,
        )
        if not questions:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="placement_questions_unavailable",
            )

        evaluation = evaluate_test(questions, request.answers)
        async with aiosqlite.connect(settings.db_path) as conn:
            await _ensure_session_id_column(conn)
            duplicate = await _has_submitted_session(
                conn,
                user_id=auth.user_id,
                session_id=request.session_id,
            )
            if duplicate:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="placement_session_already_submitted",
                )
            await conn.execute(
                """INSERT INTO placement_test_results
                   (user_id, session_id, answers_json, total_questions,
                    correct_answers, score, determined_level)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    auth.user_id,
                    request.session_id,
                    json.dumps(evaluation["answers"], ensure_ascii=False),
                    evaluation["total_questions"],
                    evaluation["correct_answers"],
                    evaluation["score"],
                    evaluation["estimated_level"],
                ),
            )
            await conn.commit()

        return {
            "user_id": auth.user_id,
            "session_id": request.session_id,
            "total_questions": evaluation["total_questions"],
            "correct_answers": evaluation["correct_answers"],
            "score": evaluation["score"],
            "estimated_level": evaluation["estimated_level"],
            "level_breakdown": evaluation["level_breakdown"],
        }

    return app


def _session_id(auth: TelegramInitDataAuth) -> str:
    raw = f"placement:{auth.user_id}:{auth.auth_date}:{auth.query_id or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _public_question(question: dict[str, Any]) -> dict[str, Any]:
    payload = question.get("payload") or {}
    choices = payload.get("choices") or payload.get("possible_answers") or []
    return {
        "question_id": question["question_id"],
        "level": question["level"],
        "prompt": question["prompt"],
        "choices": list(choices),
        "type": question["type"],
        "order": question.get("order"),
        "topic": question.get("topic"),
        "payload": _public_payload(question),
    }


def _public_payload(question: dict[str, Any]) -> dict[str, Any]:
    payload = dict(question.get("payload") or {})
    payload.pop("possible_answers", None)
    payload.pop("choices", None)
    return payload


async def _ensure_session_id_column(conn: aiosqlite.Connection) -> None:
    cursor = await conn.execute("PRAGMA table_info(placement_test_results)")
    existing_columns = {row[1] for row in await cursor.fetchall()}
    if "session_id" not in existing_columns:
        await conn.execute("ALTER TABLE placement_test_results ADD COLUMN session_id TEXT")
        await conn.commit()


async def _has_submitted_session(
    conn: aiosqlite.Connection,
    *,
    user_id: int,
    session_id: str,
) -> bool:
    cursor = await conn.execute(
        """SELECT 1 FROM placement_test_results
           WHERE user_id = ? AND session_id = ?
           LIMIT 1""",
        (user_id, session_id),
    )
    return await cursor.fetchone() is not None


__all__ = [
    "InitDataAuthError",
    "TelegramInitDataAuth",
    "create_miniapp_api",
    "validate_telegram_init_data",
]
