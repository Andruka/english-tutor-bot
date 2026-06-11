"""Минимальный REST API для административной статистики и инспекции пользователей бота.

Endpoints:
    GET /admin/stats
    GET /admin/users/{user_id}

Без внешних web-зависимостей: используется stdlib HTTP-сервер, чтобы не
тащить FastAPI/aiohttp в Telegram-бот ради read-only admin endpoints.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterable
from urllib.parse import urlparse

import aiosqlite

logger = logging.getLogger(__name__)

_onboarding_sessions: dict[str, dict[str, str]] = {}
_onboarding_sessions_lock = threading.Lock()
_text_response_states: dict[str, dict[str, dict[str, str]]] = {}
_text_response_states_lock = threading.Lock()


class PrometheusMetrics:
    """Thread-safe in-process metrics rendered in Prometheus text format."""

    def __init__(self, buckets: Iterable[float] | None = None) -> None:
        self._buckets = tuple(
            buckets or (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
        )
        self._requests_total = 0.0
        self._errors_total = 0.0
        self._latency_sum = 0.0
        self._latency_count = 0.0
        self._bucket_counts = {bucket: 0.0 for bucket in self._buckets}
        self._lock = threading.Lock()

    def observe_request(self, *, status_code: int, latency_seconds: float) -> None:
        """Record one API request, its error status, and duration."""
        duration = max(0.0, float(latency_seconds))
        with self._lock:
            self._requests_total += 1.0
            if status_code >= 400:
                self._errors_total += 1.0
            self._latency_count += 1.0
            self._latency_sum += duration
            for bucket in self._buckets:
                if duration <= bucket:
                    self._bucket_counts[bucket] += 1.0

    def render(self) -> str:
        """Return Prometheus 0.0.4 text exposition format."""
        with self._lock:
            requests_total = self._requests_total
            errors_total = self._errors_total
            latency_count = self._latency_count
            latency_sum = self._latency_sum
            bucket_counts = dict(self._bucket_counts)

        lines = [
            "# HELP api_requests_total Total API requests handled by the admin HTTP server.",
            "# TYPE api_requests_total counter",
            f"api_requests_total {requests_total}",
            "# HELP api_errors_total Total API requests returning HTTP 4xx or 5xx responses.",
            "# TYPE api_errors_total counter",
            f"api_errors_total {errors_total}",
            "# HELP api_request_latency_seconds API request latency in seconds.",
            "# TYPE api_request_latency_seconds histogram",
        ]
        for bucket in self._buckets:
            lines.append(
                f'api_request_latency_seconds_bucket{{le="{bucket:g}"}} {bucket_counts[bucket]}'
            )
        lines.extend(
            [
                f'api_request_latency_seconds_bucket{{le="+Inf"}} {latency_count}',
                f"api_request_latency_seconds_count {latency_count}",
                f"api_request_latency_seconds_sum {latency_sum}",
                "",
            ]
        )
        return "\n".join(lines)


class ConversationService:
    """In-memory service that creates the first web dialogue context."""

    def __init__(self) -> None:
        self._conversations: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    def start_conversation(self, *, session_id: str, level: str, topic: str) -> dict:
        conversation_id = f"conv-{uuid.uuid4().hex}"
        message = build_initial_dialogue_message(level=level, topic=topic)
        context = {
            "session_id": session_id,
            "level": level,
            "topic": topic,
            "message": message,
        }
        with self._lock:
            self._conversations[conversation_id] = context
        return {
            "conversation_id": conversation_id,
            "message": message,
            "metadata": {"level": level, "topic": topic},
        }


def build_initial_dialogue_message(*, level: str, topic: str) -> str:
    """Builds a friendly first prompt tailored to the selected level/topic."""
    topic_label = topic.replace("_", " ")
    if level in {"A1", "A2"}:
        return (
            f"Hi! Welcome to your {level} English practice. "
            f"Let's talk about {topic_label}. I'll keep it simple: "
            f"What can you say about {topic_label}?"
        )
    return (
        f"Hello! Welcome to your {level} English conversation practice. "
        f"Today we'll discuss {topic_label}. Share your first thought, "
        "and I'll help you improve naturally."
    )


def get_onboarding_session(session_id: str) -> dict[str, str] | None:
    """Возвращает копию onboarding session state для тестов/инспекции."""
    with _onboarding_sessions_lock:
        session = _onboarding_sessions.get(session_id)
        return dict(session) if session is not None else None


def save_onboarding_level(session_id: str, level: str) -> None:
    """Сохраняет выбранный уровень в in-memory onboarding session state."""
    with _onboarding_sessions_lock:
        state = _onboarding_sessions.setdefault(session_id, {})
        state["level"] = level


def save_onboarding_topic(session_id: str, topic: str) -> None:
    """Сохраняет выбранную тему в in-memory onboarding session state."""
    with _onboarding_sessions_lock:
        state = _onboarding_sessions.setdefault(session_id, {})
        state["topic"] = topic


def get_text_response_state(session_id: str, response_id: str) -> dict[str, str] | None:
    """Возвращает копию состояния текстового ответа для тестов/инспекции."""
    with _text_response_states_lock:
        session = _text_response_states.get(session_id, {})
        state = session.get(response_id)
        return dict(state) if state is not None else None


def mark_text_response_tts_skipped(
    session_id: str, response_id: str, text: str
) -> None:
    """Помечает TTS для текстового ответа как пропущенный клиентом."""
    with _text_response_states_lock:
        session = _text_response_states.setdefault(session_id, {})
        session[response_id] = {"text": text, "tts_status": "skipped"}


@dataclass(frozen=True)
class AdminStats:
    user_count: int
    active_sessions: int
    system_load: list[float]

    def as_dict(self) -> dict[str, int | list[float]]:
        return {
            "user_count": self.user_count,
            "active_sessions": self.active_sessions,
            "system_load": self.system_load,
        }


@dataclass(frozen=True)
class UserInspection:
    profile: dict
    activity: dict
    permissions: dict[str, bool]

    def as_dict(self) -> dict:
        return {
            "profile": self.profile,
            "activity": self.activity,
            "permissions": self.permissions,
        }


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


async def collect_admin_statistics(db_path: str) -> AdminStats:
    """Собирает статистику для admin endpoint.

    user_count берётся из SQLite; active_sessions — из in-memory AI tutor
    sessions; system_load — из os.getloadavg(), с безопасным fallback для
    платформ без этой функции.
    """
    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        user_count = int(row[0]) if row else 0

    from bot.handlers.dialogue import _tutor_sessions

    try:
        load = [float(value) for value in os.getloadavg()]
    except (AttributeError, OSError):
        load = [0.0, 0.0, 0.0]

    return AdminStats(
        user_count=user_count,
        active_sessions=len(_tutor_sessions),
        system_load=load,
    )


async def collect_user_inspection(
    db_path: str,
    user_id: int,
    admin_user_ids: set[int],
    recent_dialogue_limit: int = 10,
) -> UserInspection | None:
    """Собирает read-only профиль, activity logs и permissions пользователя для админа."""
    from bot.db import DialogueRepository, UserRepository

    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        users = UserRepository(conn)
        dialogues = DialogueRepository(conn)

        user = await users.get(user_id)
        if not user:
            return None

        recent_dialogues = await dialogues.get_history(
            user_id, limit=recent_dialogue_limit
        )
        profile = {key: _json_value(value) for key, value in user.__dict__.items()}
        activity = {
            "dialogue_count": await dialogues.count(user_id),
            "correction_count": await dialogues.count_corrections(user_id),
            "recent_dialogues": [
                {key: _json_value(value) for key, value in entry.__dict__.items()}
                for entry in recent_dialogues
            ],
        }
        inspected_user_is_admin = user_id in admin_user_ids
        permissions = {
            "is_admin": inspected_user_is_admin,
            "can_inspect_users": inspected_user_is_admin,
        }

        return UserInspection(
            profile=profile,
            activity=activity,
            permissions=permissions,
        )


def parse_admin_user_ids(raw: str | None) -> set[int]:
    """Парсит ADMIN_USER_IDS='1,2,3' в set[int]. Некорректные элементы игнорируются."""
    ids: set[int] = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            logger.warning("Игнорируем некорректный ADMIN_USER_IDS элемент: %r", part)
    return ids


def _is_authenticated(headers, admin_token: str) -> bool:
    auth_header = headers.get("Authorization", "")
    return bool(admin_token) and auth_header == f"Bearer {admin_token}"


def _is_authorized(headers, admin_user_ids: set[int]) -> bool:
    raw_user_id = headers.get("X-Admin-User-Id", "")
    try:
        user_id = int(raw_user_id)
    except ValueError:
        return False
    return user_id in admin_user_ids


class AdminStatsServer:
    """Управляемый wrapper над ThreadingHTTPServer для запуска/остановки в main и тестах."""

    def __init__(
        self,
        host: str,
        port: int,
        db_path: str,
        admin_token: str,
        admin_user_ids: Iterable[int],
        conversation_service: ConversationService | None = None,
    ) -> None:
        self.host = host
        self.db_path = db_path
        self.admin_token = admin_token
        self.admin_user_ids = set(admin_user_ids)
        self.conversation_service = conversation_service or ConversationService()
        self.metrics = PrometheusMetrics()
        handler = self._build_handler()
        self._server = ThreadingHTTPServer((host, port), handler)
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="admin-stats-api",
            daemon=True,
        )
        self._thread.start()
        logger.info("Admin stats API started on http://%s:%s", self.host, self.port)

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=5)

    def _build_handler(self):
        parent = self

        class AdminStatsRequestHandler(BaseHTTPRequestHandler):
            server_version = "EnglishTutorAdminStats/1.0"

            def do_GET(self) -> None:  # noqa: N802 - stdlib API name
                started_at = time.perf_counter()
                path = urlparse(self.path).path
                try:
                    if path == "/metrics":
                        self._handle_metrics()
                        return
                    if path == "/admin/stats":
                        self._handle_stats()
                        return
                    if path.startswith("/admin/users/"):
                        self._handle_user_inspection(path)
                        return
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                finally:
                    if path != "/metrics":
                        self._record_metrics(started_at)

            def do_POST(self) -> None:  # noqa: N802 - stdlib API name
                started_at = time.perf_counter()
                path = urlparse(self.path).path
                try:
                    if path == "/onboarding/level":
                        self._handle_onboarding_level()
                        return
                    if path == "/onboarding/topic":
                        self._handle_onboarding_topic()
                        return
                    if path == "/dialogue/start":
                        self._handle_dialogue_start()
                        return
                    if path == "/skip-tts":
                        self._handle_skip_tts()
                        return
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                finally:
                    self._record_metrics(started_at)

            def _record_metrics(self, started_at: float) -> None:
                status = getattr(self, "_last_status", HTTPStatus.INTERNAL_SERVER_ERROR)
                parent.metrics.observe_request(
                    status_code=int(status),
                    latency_seconds=time.perf_counter() - started_at,
                )

            def _handle_metrics(self) -> None:
                body = parent.metrics.render().encode("utf-8")
                self._last_status = HTTPStatus.OK
                self.send_response(HTTPStatus.OK.value)
                self.send_header(
                    "Content-Type", "text/plain; version=0.0.4; charset=utf-8"
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _handle_stats(self) -> None:
                if not _is_authenticated(self.headers, parent.admin_token):
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                if not _is_authorized(self.headers, parent.admin_user_ids):
                    self._send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
                    return

                try:
                    stats = asyncio.run(collect_admin_statistics(parent.db_path))
                except Exception:
                    logger.exception("Failed to collect admin statistics")
                    self._send_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": "stats_unavailable"},
                    )
                    return

                self._send_json(HTTPStatus.OK, stats.as_dict())

            def _handle_user_inspection(self, path: str) -> None:
                if not _is_authenticated(self.headers, parent.admin_token):
                    self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                    return
                if not _is_authorized(self.headers, parent.admin_user_ids):
                    self._send_json(HTTPStatus.FORBIDDEN, {"error": "forbidden"})
                    return

                raw_user_id = path.removeprefix("/admin/users/")
                if not raw_user_id or "/" in raw_user_id:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                try:
                    user_id = int(raw_user_id)
                except ValueError:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST, {"error": "invalid_user_id"}
                    )
                    return

                try:
                    inspection = asyncio.run(
                        collect_user_inspection(
                            parent.db_path,
                            user_id,
                            parent.admin_user_ids,
                        )
                    )
                except Exception:
                    logger.exception("Failed to inspect user %s", user_id)
                    self._send_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": "user_inspection_unavailable"},
                    )
                    return

                if not inspection:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "user_not_found"})
                    return

                self._send_json(HTTPStatus.OK, inspection.as_dict())

            def _handle_onboarding_level(self) -> None:
                from bot.handlers.start import LEVELS, TOPICS

                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"}
                    )
                    return

                try:
                    raw_body = (
                        self.rfile.read(content_length).decode("utf-8")
                        if content_length
                        else "{}"
                    )
                    payload = json.loads(raw_body)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                    return

                if not isinstance(payload, dict):
                    self._send_json(
                        HTTPStatus.BAD_REQUEST, {"error": "invalid_payload"}
                    )
                    return

                raw_level = payload.get("level")
                if raw_level is None:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "missing_level"})
                    return
                if not isinstance(raw_level, str):
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "invalid_level", "allowed_levels": LEVELS},
                    )
                    return

                level = raw_level.strip().upper()
                if level not in LEVELS:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "invalid_level", "allowed_levels": LEVELS},
                    )
                    return

                session_id = self.headers.get("X-Session-Id", "").strip()
                if not session_id:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST, {"error": "missing_session_id"}
                    )
                    return

                save_onboarding_level(session_id, level)
                self._send_json(
                    HTTPStatus.OK,
                    {"status": "ok", "level": level, "topics": TOPICS},
                )

            def _handle_onboarding_topic(self) -> None:
                from bot.handlers.start import TOPICS

                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"}
                    )
                    return

                try:
                    raw_body = (
                        self.rfile.read(content_length).decode("utf-8")
                        if content_length
                        else "{}"
                    )
                    payload = json.loads(raw_body)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                    return

                if not isinstance(payload, dict):
                    self._send_json(
                        HTTPStatus.BAD_REQUEST, {"error": "invalid_payload"}
                    )
                    return

                raw_topic = payload.get("topic")
                if raw_topic is None:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "missing_topic"})
                    return
                if not isinstance(raw_topic, str):
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "invalid_topic", "allowed_topics": TOPICS},
                    )
                    return

                topic = raw_topic.strip().lower().replace(" ", "_")
                if topic not in TOPICS:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "invalid_topic", "allowed_topics": TOPICS},
                    )
                    return

                session_id = self.headers.get("X-Session-Id", "").strip()
                if not session_id:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST, {"error": "missing_session_id"}
                    )
                    return

                save_onboarding_topic(session_id, topic)
                self._send_json(
                    HTTPStatus.OK,
                    {"status": "ok", "topic": topic, "next_step": "start_lesson"},
                )

            def _handle_dialogue_start(self) -> None:
                session_id = self.headers.get("X-Session-Id", "").strip()
                if not session_id:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST, {"error": "missing_session_id"}
                    )
                    return

                session = get_onboarding_session(session_id) or {}
                missing = [key for key in ("level", "topic") if not session.get(key)]
                if missing:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "missing_onboarding_state", "missing": missing},
                    )
                    return

                try:
                    result = parent.conversation_service.start_conversation(
                        session_id=session_id,
                        level=session["level"],
                        topic=session["topic"],
                    )
                except Exception:
                    logger.exception(
                        "Failed to start dialogue for session %s", session_id
                    )
                    self._send_json(
                        HTTPStatus.INTERNAL_SERVER_ERROR,
                        {"error": "dialogue_start_unavailable"},
                    )
                    return

                self._send_json(HTTPStatus.OK, result)

            def _handle_skip_tts(self) -> None:
                session_id = self.headers.get("X-Session-Id", "").strip()
                if not session_id:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST, {"error": "missing_session_id"}
                    )
                    return

                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST, {"error": "invalid_content_length"}
                    )
                    return

                try:
                    raw_body = (
                        self.rfile.read(content_length).decode("utf-8")
                        if content_length
                        else "{}"
                    )
                    payload = json.loads(raw_body)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
                    return

                if not isinstance(payload, dict):
                    self._send_json(
                        HTTPStatus.BAD_REQUEST, {"error": "invalid_payload"}
                    )
                    return

                raw_response_id = payload.get("response_id")
                if raw_response_id is None:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST, {"error": "missing_response_id"}
                    )
                    return
                if not isinstance(raw_response_id, str):
                    self._send_json(
                        HTTPStatus.BAD_REQUEST, {"error": "invalid_response_id"}
                    )
                    return

                response_id = raw_response_id.strip()
                if not response_id:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST, {"error": "missing_response_id"}
                    )
                    return

                raw_text = payload.get("text", "")
                if not isinstance(raw_text, str):
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_text"})
                    return

                mark_text_response_tts_skipped(session_id, response_id, raw_text)
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "response_id": response_id,
                        "tts_status": "skipped",
                    },
                )

            def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib name
                logger.info("Admin stats API: " + format, *args)

            def _send_json(self, status: HTTPStatus, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self._last_status = status
                self.send_response(status.value)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return AdminStatsRequestHandler


def create_admin_stats_server(
    host: str,
    port: int,
    db_path: str,
    admin_token: str,
    admin_user_ids: Iterable[int],
    conversation_service: ConversationService | None = None,
) -> AdminStatsServer:
    """Создаёт, но не запускает admin stats HTTP server."""
    return AdminStatsServer(
        host,
        port,
        db_path,
        admin_token,
        admin_user_ids,
        conversation_service=conversation_service,
    )


def create_admin_stats_server_from_env(db_path: str) -> AdminStatsServer | None:
    """Создаёт server по env, если endpoint включён и настроен.

    Env:
        ADMIN_API_ENABLED=true
        ADMIN_API_HOST=127.0.0.1
        ADMIN_API_PORT=8080
        ADMIN_API_TOKEN=<bearer token>
        ADMIN_USER_IDS=123,456
    """
    if os.getenv("ADMIN_API_ENABLED", "false").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return None

    token = os.getenv("ADMIN_API_TOKEN", "").strip()
    admin_ids = parse_admin_user_ids(os.getenv("ADMIN_USER_IDS"))
    if not token:
        raise ValueError("ADMIN_API_TOKEN is required when ADMIN_API_ENABLED=true")
    if not admin_ids:
        raise ValueError("ADMIN_USER_IDS is required when ADMIN_API_ENABLED=true")

    host = os.getenv("ADMIN_API_HOST", "127.0.0.1")
    port = int(os.getenv("ADMIN_API_PORT", "8080"))
    return create_admin_stats_server(host, port, db_path, token, admin_ids)
