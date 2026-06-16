"""Tests for FastAPI Mini App exercise endpoints."""

import json
import time
from urllib.parse import urlencode

import hashlib
import hmac

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
async def test_exercises_require_auth(tmp_path):
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "exercises.db"
    await init_db(str(db_path))
    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)

    resp = client.get("/api/exercises?type=gap_fill")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_exercises_gap_fill_structure(tmp_path):
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "exercises_gap.db"
    await init_db(str(db_path))
    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)
    headers = {"X-Telegram-Init-Data": _signed_init_data("bot-token", user_id=111)}

    resp = client.get("/api/exercises?type=gap_fill&level=A1&topic=daily_routine", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["exercise_id"]
    assert data["type"] == "gap_fill"
    assert data["level"] == "A1"
    assert data["prompt"]
    assert data["payload"]
    # Must not leak answers
    serialized = json.dumps(data, ensure_ascii=False)
    assert "correct_answer" not in serialized
    assert "expected" not in serialized


@pytest.mark.asyncio
async def test_exercises_choice_structure(tmp_path):
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "exercises_choice.db"
    await init_db(str(db_path))
    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)
    headers = {"X-Telegram-Init-Data": _signed_init_data("bot-token", user_id=222)}

    resp = client.get("/api/exercises?type=choice&level=A2&topic=travel", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "choice"
    assert data["level"] == "A2"
    payload = data["payload"]
    assert payload
    assert isinstance(payload.get("choices"), list)
    assert len(payload["choices"]) >= 2


@pytest.mark.asyncio
async def test_exercises_translation_structure(tmp_path):
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "exercises_trans.db"
    await init_db(str(db_path))
    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)
    headers = {"X-Telegram-Init-Data": _signed_init_data("bot-token", user_id=333)}

    resp = client.get("/api/exercises?type=translation&level=B1&topic=food", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "translation"
    assert data["level"] == "B1"


@pytest.mark.asyncio
async def test_exercises_invalid_type_returns_400(tmp_path):
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "exercises_invalid.db"
    await init_db(str(db_path))
    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)
    headers = {"X-Telegram-Init-Data": _signed_init_data("bot-token", user_id=444)}

    resp = client.get("/api/exercises?type=unknown", headers=headers)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_exercises_check_correct_answer_gap_fill(tmp_path):
    """Verify correct answer via possible_answers from gap_fill payload."""
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "exercises_check_ok.db"
    await init_db(str(db_path))
    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)
    headers = {"X-Telegram-Init-Data": _signed_init_data("bot-token", user_id=555)}

    ex = client.get("/api/exercises?type=gap_fill&level=A1&topic=daily_routine", headers=headers).json()
    ex_id = ex["exercise_id"]
    possible = ex["payload"].get("possible_answers", [])

    for candidate in possible:
        resp = client.post(
            "/api/exercises/check",
            headers=headers,
            json={"exercise_id": ex_id, "answer": candidate},
        )
        assert resp.status_code == 200
        result = resp.json()
        if result["correct"]:
            assert result["expected"]
            assert "explanation" in result
            return  # found the correct one

    pytest.fail(f"no correct answer found in possible_answers={possible}")


@pytest.mark.asyncio
async def test_exercises_check_correct_answer_choice(tmp_path):
    """Verify correct answer for choice exercises via payload choices."""
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "exercises_check_choice.db"
    await init_db(str(db_path))
    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)
    headers = {"X-Telegram-Init-Data": _signed_init_data("bot-token", user_id=556)}

    ex = client.get("/api/exercises?type=choice&level=A1&topic=daily_routine", headers=headers).json()
    ex_id = ex["exercise_id"]
    # choice payload has a flat list of string choices
    choices = ex["payload"].get("choices", [])
    assert isinstance(choices, list) and choices, "choice payload must have choices"

    for candidate in choices:
        resp = client.post(
            "/api/exercises/check",
            headers=headers,
            json={"exercise_id": ex_id, "answer": candidate},
        )
        assert resp.status_code == 200
        result = resp.json()
        if result["correct"]:
            assert result["expected"]
            assert "explanation" in result
            return

    pytest.fail(f"no correct answer found in choices={choices}")


@pytest.mark.asyncio
async def test_exercises_check_wrong_answer(tmp_path):
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "exercises_check_wrong.db"
    await init_db(str(db_path))
    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)
    headers = {"X-Telegram-Init-Data": _signed_init_data("bot-token", user_id=666)}

    ex = client.get("/api/exercises?type=gap_fill&level=A1&topic=daily_routine", headers=headers).json()
    ex_id = ex["exercise_id"]

    resp = client.post(
        "/api/exercises/check",
        headers=headers,
        json={"exercise_id": ex_id, "answer": "DEFINITELY_WRONG_ANSWER_XYZ"},
    )
    assert resp.status_code == 200
    result = resp.json()
    assert result["correct"] is False
    assert result["expected"]
    assert "explanation" in result


@pytest.mark.asyncio
async def test_exercises_check_unknown_exercise_returns_404(tmp_path):
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "exercises_unknown.db"
    await init_db(str(db_path))
    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)
    headers = {"X-Telegram-Init-Data": _signed_init_data("bot-token", user_id=777)}

    resp = client.post(
        "/api/exercises/check",
        headers=headers,
        json={"exercise_id": "non_existent_id", "answer": "test"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_exercises_check_requires_auth(tmp_path):
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "exercises_check_auth.db"
    await init_db(str(db_path))
    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)

    resp = client.post(
        "/api/exercises/check",
        json={"exercise_id": "x", "answer": "y"},
    )
    assert resp.status_code == 401