"""Тесты REST API административной статистики."""

import asyncio
import json
import urllib.error
import urllib.request

import pytest


def _get_json(url: str, token: str, admin_user_id: str = "42"):
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Admin-User-Id": admin_user_id,
        },
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict, session_id: str = "session-1"):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Session-Id": session_id,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def _get_text(url: str):
    request = urllib.request.Request(url)
    with urllib.request.urlopen(request, timeout=3) as response:
        return (
            response.status,
            response.headers.get("Content-Type", ""),
            response.read().decode("utf-8"),
        )


def _post_json_expect_error(url: str, payload: dict, session_id: str = "session-1"):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Session-Id": session_id},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=3)
    return exc.value.code, json.loads(exc.value.read().decode("utf-8"))


def _metric_value(metrics_text: str, metric_name: str) -> float:
    for line in metrics_text.splitlines():
        if line.startswith(metric_name + " "):
            return float(line.rsplit(" ", 1)[1])
    raise AssertionError(f"metric {metric_name!r} not found in:\n{metrics_text}")


@pytest.mark.asyncio
async def test_admin_stats_endpoint_returns_counts_sessions_and_load(
    tmp_path, monkeypatch
):
    """GET /admin/stats отдаёт user_count, active_sessions и system_load для админа."""
    from bot.db import UserRepository, get_conn, init_db
    from bot.handlers import dialogue
    from bot.admin_api import create_admin_stats_server

    db_path = tmp_path / "admin_stats.db"
    await init_db(str(db_path))
    conn = await get_conn()
    repo = UserRepository(conn)
    await repo.create(1, "A1", "alice")
    await repo.create(2, "B1", "bob")

    monkeypatch.setattr(
        dialogue, "_tutor_sessions", {1: object(), 2: object(), 3: object()}
    )
    monkeypatch.setattr("bot.admin_api.os.getloadavg", lambda: (0.1, 0.2, 0.3))

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(db_path),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        url = f"http://127.0.0.1:{server.port}/admin/stats"

        status, payload = _get_json(url, "secret-token", "42")

        assert status == 200
        assert payload == {
            "user_count": 2,
            "active_sessions": 3,
            "system_load": [0.1, 0.2, 0.3],
        }
    finally:
        server.stop()
        await conn.close()


def test_admin_stats_endpoint_requires_bearer_token(tmp_path):
    """GET /admin/stats без корректного bearer-токена возвращает 401."""
    from bot.admin_api import create_admin_stats_server

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        request = urllib.request.Request(f"http://127.0.0.1:{server.port}/admin/stats")

        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)

        assert exc.value.code == 401
    finally:
        server.stop()


def test_admin_stats_endpoint_requires_authorized_admin_user(tmp_path):
    """GET /admin/stats с неадминским X-Admin-User-Id возвращает 403."""
    from bot.admin_api import create_admin_stats_server

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/admin/stats",
            headers={"Authorization": "Bearer secret-token", "X-Admin-User-Id": "7"},
        )

        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)

        assert exc.value.code == 403
    finally:
        server.stop()


@pytest.mark.asyncio
async def test_admin_can_inspect_user_details_by_id(tmp_path):
    """GET /admin/users/{id} отдаёт профиль, activity logs и permissions для админа."""
    from bot.admin_api import create_admin_stats_server
    from bot.db import DialogueRepository, UserRepository, get_conn, init_db

    db_path = tmp_path / "admin_inspect.db"
    await init_db(str(db_path))
    conn = await get_conn()
    users = UserRepository(conn)
    dialogues = DialogueRepository(conn)
    await users.create(7, "B1", "student")
    await users.set_subscription(7, True, "2030-01-01T00:00:00+00:00")
    await dialogues.save(
        user_id=7,
        topic="travel",
        user_message="I go to London yesterday",
        ai_reply="I went to London yesterday.",
        rating=4,
        corrections=[{"from": "go", "to": "went"}],
    )
    await dialogues.save(
        user_id=7,
        topic="food",
        user_message="I like soup",
        ai_reply="Great sentence!",
        rating=5,
        corrections=[],
    )

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(db_path),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        status, payload = _get_json(
            f"http://127.0.0.1:{server.port}/admin/users/7",
            "secret-token",
            "42",
        )

        assert status == 200
        assert payload["profile"] == {
            "user_id": 7,
            "level": "B1",
            "username": "student",
            "dialogues_today": 0,
            "last_dialogue_date": None,
            "subscription": True,
            "subscription_tier": "premium",
            "subscription_expiry": "2030-01-01T00:00:00+00:00",
            "trial_taken": False,
            "streak": 0,
            "created_at": payload["profile"]["created_at"],
        }
        assert payload["activity"]["dialogue_count"] == 2
        assert payload["activity"]["correction_count"] == 1
        assert [log["topic"] for log in payload["activity"]["recent_dialogues"]] == [
            "food",
            "travel",
        ]
        assert payload["activity"]["recent_dialogues"][1]["corrections"] == [
            {"from": "go", "to": "went"}
        ]
        assert payload["permissions"] == {"is_admin": False, "can_inspect_users": False}
    finally:
        server.stop()
        await conn.close()


def test_admin_user_inspection_requires_authorized_admin_user(tmp_path):
    """GET /admin/users/{id} с неадминским X-Admin-User-Id возвращает 403."""
    from bot.admin_api import create_admin_stats_server

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/admin/users/7",
            headers={"Authorization": "Bearer secret-token", "X-Admin-User-Id": "7"},
        )

        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)

        assert exc.value.code == 403
    finally:
        server.stop()


def test_admin_user_inspection_rejects_non_existent_user(tmp_path):
    """GET /admin/users/{id} для несуществующего user_id возвращает 404."""
    from bot.admin_api import create_admin_stats_server
    from bot.db import init_db

    db_path = tmp_path / "user_inspect_404.db"
    asyncio.run(init_db(str(db_path)))

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(db_path),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/admin/users/999",
            headers={"Authorization": "Bearer secret-token", "X-Admin-User-Id": "42"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)
        assert exc.value.code == 404
        err = json.loads(exc.value.read().decode("utf-8"))
        assert err["error"] == "user_not_found"
    finally:
        server.stop()


def test_admin_user_inspection_rejects_non_numeric_user_id(tmp_path):
    """GET /admin/users/{id} с нечисловым user_id возвращает 400."""
    from bot.admin_api import create_admin_stats_server

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "bad_user.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/admin/users/abc",
            headers={"Authorization": "Bearer secret-token", "X-Admin-User-Id": "42"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)
        assert exc.value.code == 400
        err = json.loads(exc.value.read().decode("utf-8"))
        assert err["error"] == "invalid_user_id"
    finally:
        server.stop()


def test_onboarding_level_selection_returns_topics_and_saves_session(tmp_path):
    """POST /onboarding/level сохраняет допустимый уровень в session state и отдаёт темы."""
    from bot.admin_api import create_admin_stats_server, get_onboarding_session
    from bot.handlers.start import TOPICS

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        status, payload = _post_json(
            f"http://127.0.0.1:{server.port}/onboarding/level",
            {"level": "B1"},
            session_id="student-session",
        )

        assert status == 200
        assert payload == {"status": "ok", "level": "B1", "topics": TOPICS}
        assert get_onboarding_session("student-session") == {"level": "B1"}
    finally:
        server.stop()


def test_onboarding_level_selection_rejects_invalid_level(tmp_path):
    """POST /onboarding/level с недопустимым level возвращает 400."""
    from bot.admin_api import create_admin_stats_server

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/onboarding/level",
            data=json.dumps({"level": "native"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Session-Id": "bad-level"},
            method="POST",
        )

        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)

        assert exc.value.code == 400
        assert json.loads(exc.value.read().decode("utf-8")) == {
            "error": "invalid_level",
            "allowed_levels": ["A1", "A2", "B1", "B2", "C1"],
        }
    finally:
        server.stop()


def test_onboarding_level_selection_requires_level_field(tmp_path):
    """POST /onboarding/level без поля level возвращает 400."""
    from bot.admin_api import create_admin_stats_server

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/onboarding/level",
            data=json.dumps({}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Session-Id": "missing-level",
            },
            method="POST",
        )

        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)

        assert exc.value.code == 400
        assert json.loads(exc.value.read().decode("utf-8")) == {
            "error": "missing_level"
        }
    finally:
        server.stop()


def test_onboarding_topic_selection_returns_next_step_and_saves_session(tmp_path):
    """POST /onboarding/topic сохраняет допустимую тему независимо от выбора уровня."""
    from bot.admin_api import create_admin_stats_server, get_onboarding_session

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        status, payload = _post_json(
            f"http://127.0.0.1:{server.port}/onboarding/topic",
            {"topic": "travel"},
            session_id="topic-only-session",
        )

        assert status == 200
        assert payload == {
            "status": "ok",
            "topic": "travel",
            "next_step": "start_lesson",
        }
        assert get_onboarding_session("topic-only-session") == {"topic": "travel"}
    finally:
        server.stop()


def test_onboarding_topic_selection_rejects_invalid_topic(tmp_path):
    """POST /onboarding/topic с недопустимым topic возвращает 400."""
    from bot.admin_api import create_admin_stats_server
    from bot.handlers.start import TOPICS

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/onboarding/topic",
            data=json.dumps({"topic": "taxes"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Session-Id": "bad-topic"},
            method="POST",
        )

        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)

        assert exc.value.code == 400
        assert json.loads(exc.value.read().decode("utf-8")) == {
            "error": "invalid_topic",
            "allowed_topics": TOPICS,
        }
    finally:
        server.stop()


def test_onboarding_topic_selection_requires_topic_field(tmp_path):
    """POST /onboarding/topic без поля topic возвращает 400."""
    from bot.admin_api import create_admin_stats_server

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/onboarding/topic",
            data=json.dumps({}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Session-Id": "missing-topic",
            },
            method="POST",
        )

        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)

        assert exc.value.code == 400
        assert json.loads(exc.value.read().decode("utf-8")) == {
            "error": "missing_topic"
        }
    finally:
        server.stop()


class FakeConversationService:
    def __init__(self):
        self.calls = []

    def start_conversation(self, *, session_id: str, level: str, topic: str):
        self.calls.append({"session_id": session_id, "level": level, "topic": topic})
        return {
            "conversation_id": "conv-test-1",
            "message": "Hello B1 learner! Let's talk about travel.",
            "metadata": {"level": level, "topic": topic},
        }


def test_dialogue_start_returns_initial_message_and_initializes_conversation(tmp_path):
    """POST /dialogue/start берёт level/topic из session state и стартует первый диалог."""
    from bot.admin_api import (
        create_admin_stats_server,
        save_onboarding_level,
        save_onboarding_topic,
    )

    conversation_service = FakeConversationService()
    save_onboarding_level("ready-session", "B1")
    save_onboarding_topic("ready-session", "travel")
    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
        conversation_service=conversation_service,
    )
    try:
        server.start()
        status, payload = _post_json(
            f"http://127.0.0.1:{server.port}/dialogue/start",
            {},
            session_id="ready-session",
        )

        assert status == 200
        assert payload == {
            "conversation_id": "conv-test-1",
            "message": "Hello B1 learner! Let's talk about travel.",
            "metadata": {"level": "B1", "topic": "travel"},
        }
        assert conversation_service.calls == [
            {"session_id": "ready-session", "level": "B1", "topic": "travel"}
        ]
    finally:
        server.stop()


def test_dialogue_start_requires_level_and_topic_in_session(tmp_path):
    """POST /dialogue/start без level/topic в session state возвращает 400."""
    from bot.admin_api import create_admin_stats_server, save_onboarding_level

    conversation_service = FakeConversationService()
    save_onboarding_level("missing-topic-session", "A2")
    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
        conversation_service=conversation_service,
    )
    try:
        server.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/dialogue/start",
            data=json.dumps({}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Session-Id": "missing-topic-session",
            },
            method="POST",
        )

        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)

        assert exc.value.code == 400
        assert json.loads(exc.value.read().decode("utf-8")) == {
            "error": "missing_onboarding_state",
            "missing": ["topic"],
        }
        assert conversation_service.calls == []
    finally:
        server.stop()


def test_dialogue_start_default_service_builds_level_topic_greeting(tmp_path):
    """Default conversation service создаёт conversation_id и приветствие по level/topic."""
    from bot.admin_api import (
        create_admin_stats_server,
        save_onboarding_level,
        save_onboarding_topic,
    )

    save_onboarding_level("default-service-session", "A1")
    save_onboarding_topic("default-service-session", "food")
    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        status, payload = _post_json(
            f"http://127.0.0.1:{server.port}/dialogue/start",
            {},
            session_id="default-service-session",
        )

        assert status == 200
        assert payload["conversation_id"]
        assert "A1" in payload["message"]
        assert "food" in payload["message"]
        assert payload["metadata"] == {"level": "A1", "topic": "food"}
    finally:
        server.stop()


def test_skip_tts_marks_text_response_as_skipped(tmp_path):
    """POST /skip-tts помечает конкретный текстовый ответ как пропущенный для TTS."""
    from bot.admin_api import create_admin_stats_server, get_text_response_state

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        status, payload = _post_json(
            f"http://127.0.0.1:{server.port}/skip-tts",
            {"response_id": "resp-1", "text": "Hello! Let's practice."},
            session_id="student-session",
        )

        assert status == 200
        assert payload == {
            "status": "ok",
            "response_id": "resp-1",
            "tts_status": "skipped",
        }
        assert get_text_response_state("student-session", "resp-1") == {
            "text": "Hello! Let's practice.",
            "tts_status": "skipped",
        }
    finally:
        server.stop()


def test_skip_tts_requires_response_id(tmp_path):
    """POST /skip-tts без response_id возвращает 400 и не обновляет состояние."""
    from bot.admin_api import create_admin_stats_server, get_text_response_state

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/skip-tts",
            data=json.dumps({"text": "No response id"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Session-Id": "bad-skip-session",
            },
            method="POST",
        )

        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)

        assert exc.value.code == 400
        assert json.loads(exc.value.read().decode("utf-8")) == {
            "error": "missing_response_id"
        }
        assert get_text_response_state("bad-skip-session", "") is None
    finally:
        server.stop()


def test_skip_tts_is_idempotent_on_already_skipped_response(tmp_path):
    """POST /skip-tts дважды для одного response_id — вторая отправка возвращает тот же результат."""
    from bot.admin_api import create_admin_stats_server, get_text_response_state

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        url = f"http://127.0.0.1:{server.port}/skip-tts"
        payload = {"response_id": "resp-double", "text": "Double tap."}

        status1, body1 = _post_json(url, payload, session_id="double-session")
        assert status1 == 200
        assert body1["tts_status"] == "skipped"

        status2, body2 = _post_json(url, payload, session_id="double-session")
        assert status2 == 200
        assert body2 == {
            "status": "ok",
            "response_id": "resp-double",
            "tts_status": "skipped",
        }
        assert get_text_response_state("double-session", "resp-double") == {
            "text": "Double tap.",
            "tts_status": "skipped",
        }
    finally:
        server.stop()


def test_skip_tts_requires_session_id(tmp_path):
    """POST /skip-tts без X-Session-Id возвращает 400."""
    from bot.admin_api import create_admin_stats_server

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/skip-tts",
            data=json.dumps({"response_id": "r1", "text": "hi"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)
        assert exc.value.code == 400
        error = json.loads(exc.value.read().decode("utf-8"))
        assert error == {"error": "missing_session_id"}
    finally:
        server.stop()


def test_skip_tts_rejects_blank_response_id_after_strip(tmp_path):
    """POST /skip-tts с response_id из пробелов возвращает 400."""
    from bot.admin_api import create_admin_stats_server

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/skip-tts",
            data=json.dumps({"response_id": "   ", "text": "hi"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Session-Id": "blank-rid"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)
        assert exc.value.code == 400
        assert json.loads(exc.value.read().decode("utf-8")) == {
            "error": "missing_response_id"
        }
    finally:
        server.stop()


def test_skip_tts_rejects_non_string_response_id(tmp_path):
    """POST /skip-tts с числовым response_id возвращает 400."""
    from bot.admin_api import create_admin_stats_server

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/skip-tts",
            data=json.dumps({"response_id": 42, "text": "hi"}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Session-Id": "nonstr-rid"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)
        assert exc.value.code == 400
        assert json.loads(exc.value.read().decode("utf-8")) == {
            "error": "invalid_response_id"
        }
    finally:
        server.stop()


def test_skip_tts_rejects_invalid_json_body(tmp_path):
    """POST /skip-tts с некорректным JSON возвращает 400."""
    from bot.admin_api import create_admin_stats_server

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/skip-tts",
            data=b"not json at all",
            headers={"Content-Type": "application/json", "X-Session-Id": "bad-json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)
        assert exc.value.code == 400
        assert json.loads(exc.value.read().decode("utf-8")) == {"error": "invalid_json"}
    finally:
        server.stop()


def test_skip_tts_rejects_non_string_text(tmp_path):
    """POST /skip-tts с числовым text возвращает 400."""
    from bot.admin_api import create_admin_stats_server

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/skip-tts",
            data=json.dumps({"response_id": "r1", "text": 99}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Session-Id": "nonstr-text"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=3)
        assert exc.value.code == 400
        assert json.loads(exc.value.read().decode("utf-8")) == {"error": "invalid_text"}
    finally:
        server.stop()


def test_metrics_endpoint_returns_prometheus_text_with_zeroed_metrics(tmp_path):
    """GET /metrics отдаёт Prometheus text format с request/error counters и latency histogram."""
    from bot.admin_api import create_admin_stats_server

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()

        status, content_type, metrics = _get_text(
            f"http://127.0.0.1:{server.port}/metrics"
        )

        assert status == 200
        assert content_type.startswith("text/plain")
        assert "version=0.0.4" in content_type
        assert (
            "# HELP api_requests_total Total API requests handled by the admin HTTP server.\n"
            in metrics
        )
        assert "# TYPE api_requests_total counter\n" in metrics
        assert "api_requests_total 0.0\n" in metrics
        assert "# TYPE api_errors_total counter\n" in metrics
        assert "api_errors_total 0.0\n" in metrics
        assert "# TYPE api_request_latency_seconds histogram\n" in metrics
        assert 'api_request_latency_seconds_bucket{le="+Inf"} 0.0\n' in metrics
        assert "api_request_latency_seconds_count 0.0\n" in metrics
        assert "api_request_latency_seconds_sum 0.0\n" in metrics
    finally:
        server.stop()


def test_metrics_increment_requests_errors_and_latency_for_api_calls(tmp_path):
    """Метрики учитывают каждый non-/metrics API call, ошибки и duration histogram."""
    from bot.admin_api import create_admin_stats_server

    server = create_admin_stats_server(
        host="127.0.0.1",
        port=0,
        db_path=str(tmp_path / "empty.db"),
        admin_token="secret-token",
        admin_user_ids={42},
    )
    try:
        server.start()
        base_url = f"http://127.0.0.1:{server.port}"

        status, payload = _post_json(
            f"{base_url}/onboarding/level",
            {"level": "A2"},
            session_id="metrics-session",
        )
        error_status, error_payload = _post_json_expect_error(
            f"{base_url}/onboarding/topic",
            {"topic": "taxes"},
            session_id="metrics-session",
        )
        _, _, metrics = _get_text(f"{base_url}/metrics")

        assert status == 200
        assert payload["status"] == "ok"
        assert error_status == 400
        assert error_payload["error"] == "invalid_topic"
        assert _metric_value(metrics, "api_requests_total") == 2.0
        assert _metric_value(metrics, "api_errors_total") == 1.0
        assert _metric_value(metrics, "api_request_latency_seconds_count") == 2.0
        assert _metric_value(metrics, "api_request_latency_seconds_sum") > 0.0
        assert 'api_request_latency_seconds_bucket{le="+Inf"} 2.0\n' in metrics
    finally:
        server.stop()
