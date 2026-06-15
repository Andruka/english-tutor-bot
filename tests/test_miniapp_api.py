"""Tests for FastAPI placement-test Mini App endpoints."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import aiosqlite
import pytest
from fastapi.testclient import TestClient


def _signed_init_data(bot_token: str, *, user_id: int = 123, auth_date: int | None = None) -> str:
    payload = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAEAAAE",
        "user": json.dumps({"id": user_id, "first_name": "Ada"}, separators=(",", ":")),
    }
    data_check_string = "\n".join(f"{key}={payload[key]}" for key in sorted(payload))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode(payload)


@pytest.mark.asyncio
async def test_placement_questions_require_valid_init_data_and_do_not_leak_answers(tmp_path):
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "miniapp.db"
    await init_db(str(db_path))
    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)

    unauthorized = client.get("/api/placement/questions")
    assert unauthorized.status_code == 401

    response = client.get(
        "/api/placement/questions",
        headers={"X-Telegram-Init-Data": _signed_init_data("bot-token", user_id=321)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"]
    assert len(payload["questions"]) == 15
    first = payload["questions"][0]
    assert {"question_id", "level", "prompt", "choices", "type"} <= set(first)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "correct_answer" not in serialized
    assert "aliases" not in serialized
    assert "explanation" not in serialized


@pytest.mark.asyncio
async def test_placement_submit_scores_and_persists_result(tmp_path):
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api
    from bot.services.placement_test_service import evaluate_test, select_test_questions

    db_path = tmp_path / "miniapp_submit.db"
    await init_db(str(db_path))
    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)
    init_data = _signed_init_data("bot-token", user_id=654)
    headers = {"X-Telegram-Init-Data": init_data}

    questions_payload = client.get("/api/placement/questions", headers=headers).json()
    session_id = questions_payload["session_id"]
    backend_questions = select_test_questions(user_id=654, seed=session_id)
    answers = {
        item["question_id"]: item["correct_answer"]["value"]
        for item in backend_questions
    }
    expected = evaluate_test(backend_questions, answers)

    response = client.post(
        "/api/placement/submit",
        headers=headers,
        json={"session_id": session_id, "answers": answers, "user_id": 999999},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_questions"] == 15
    assert payload["correct_answers"] == expected["correct_answers"]
    assert payload["score"] == expected["score"]
    assert payload["estimated_level"] == expected["estimated_level"]
    assert payload["user_id"] == 654

    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute(
            """SELECT user_id, session_id, total_questions, correct_answers, score, determined_level
               FROM placement_test_results"""
        )
        row = await cursor.fetchone()
    assert row == (
        654,
        session_id,
        expected["total_questions"],
        expected["correct_answers"],
        expected["score"],
        expected["estimated_level"],
    )


@pytest.mark.asyncio
async def test_placement_submit_rejects_duplicate_session(tmp_path):
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api
    from bot.services.placement_test_service import select_test_questions

    db_path = tmp_path / "miniapp_duplicate.db"
    await init_db(str(db_path))
    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)
    headers = {"X-Telegram-Init-Data": _signed_init_data("bot-token", user_id=654)}
    session_id = client.get("/api/placement/questions", headers=headers).json()["session_id"]
    answers = {
        item["question_id"]: "wrong"
        for item in select_test_questions(user_id=654, seed=session_id)
    }

    first = client.post(
        "/api/placement/submit",
        headers=headers,
        json={"session_id": session_id, "answers": answers},
    )
    second = client.post(
        "/api/placement/submit",
        headers=headers,
        json={"session_id": session_id, "answers": answers},
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json() == {"detail": "placement_session_already_submitted"}
