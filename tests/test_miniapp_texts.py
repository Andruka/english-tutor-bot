"""Tests for FastAPI Mini App text library endpoints."""

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
async def test_texts_require_auth(tmp_path):
    """All text endpoints return 401 without valid init data."""
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "texts_auth.db"
    await init_db(str(db_path))
    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)

    for path in ["/api/texts/catalog", "/api/texts", "/api/texts/progress", "/api/texts/1",
                  "/api/texts/1/start", "/api/texts/1/complete"]:
        if path in ("/api/texts/1/start", "/api/texts/1/complete"):
            resp = client.post(path, headers={})
        else:
            resp = client.get(path, headers={})
        assert resp.status_code == 401, f"{path} should require auth"


@pytest.mark.asyncio
async def test_texts_catalog_empty_and_seeded(tmp_path):
    """Catalog returns levels and categories with counts."""
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "texts_cat.db"
    await init_db(str(db_path))
    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)
    headers = {"X-Telegram-Init-Data": _signed_init_data("bot-token", user_id=1)}

    # Empty DB — should return empty arrays
    resp = client.get("/api/texts/catalog", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert "levels" in payload
    assert "categories" in payload
    assert all(l["count"] == 0 for l in payload["levels"])  # no seed yet

    # Seed texts
    async with aiosqlite.connect(str(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        from bot.services.text_library_service import seed_texts
        await seed_texts(conn=conn)

    # Now catalog should have counts > 0
    resp = client.get("/api/texts/catalog", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert any(l["count"] > 0 for l in payload["levels"])
    # Check structure of a level item
    for l in payload["levels"]:
        assert "level" in l
        assert "count" in l
        assert "label" in l
    for c in payload["categories"]:
        assert "category" in c
        assert "count" in c
        assert "label" in c


@pytest.mark.asyncio
async def test_texts_list_with_level_filter(tmp_path):
    """List texts returns seeded texts, filterable by level."""
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "texts_list.db"
    await init_db(str(db_path))
    async with aiosqlite.connect(str(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        from bot.services.text_library_service import seed_texts
        await seed_texts(conn=conn)

    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)
    headers = {"X-Telegram-Init-Data": _signed_init_data("bot-token", user_id=2)}

    # All texts
    resp = client.get("/api/texts", headers=headers)
    assert resp.status_code == 200
    all_texts = resp.json()["texts"]
    assert len(all_texts) > 0

    # Check structure
    t = all_texts[0]
    assert "id" in t
    assert "title" in t
    assert "level" in t
    assert "category" in t
    assert "category_label" in t
    assert "word_count" in t
    assert "paragraph_count" in t

    # Filter by level
    resp = client.get("/api/texts?level=A1", headers=headers)
    assert resp.status_code == 200
    a1_texts = resp.json()["texts"]
    assert all(t["level"] == "A1" for t in a1_texts)
    assert len(a1_texts) < len(all_texts)  # not all texts are A1


@pytest.mark.asyncio
async def test_texts_get_by_id(tmp_path):
    """Get a single text by ID returns full content and paragraphs."""
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "texts_get.db"
    await init_db(str(db_path))
    async with aiosqlite.connect(str(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        from bot.services.text_library_service import seed_texts
        await seed_texts(conn=conn)

    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)
    headers = {"X-Telegram-Init-Data": _signed_init_data("bot-token", user_id=3)}

    resp = client.get("/api/texts", headers=headers)
    text_id = resp.json()["texts"][0]["id"]

    resp = client.get(f"/api/texts/{text_id}", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert "text" in payload
    assert "paragraphs" in payload
    assert payload["text"]["id"] == text_id
    assert payload["text"]["title"]
    assert payload["text"]["content"]
    assert payload["text"]["word_count"] > 0
    assert len(payload["paragraphs"]) > 0

    # 404 for non-existent
    resp = client.get("/api/texts/99999", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_texts_start_and_complete_flow(tmp_path):
    """Start → get progress → complete flow works."""
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "texts_flow.db"
    await init_db(str(db_path))
    async with aiosqlite.connect(str(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        from bot.services.text_library_service import seed_texts
        await seed_texts(conn=conn)

    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)
    user_id = 42
    headers = {"X-Telegram-Init-Data": _signed_init_data("bot-token", user_id=user_id)}

    resp = client.get("/api/texts", headers=headers)
    text_id = resp.json()["texts"][0]["id"]

    # Initial state — no progress
    resp = client.get(f"/api/texts/{text_id}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["progress"] is None

    # Start reading
    resp = client.post(f"/api/texts/{text_id}/start", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["progress"]["status"] == "started"

    # Verify progress now shows started
    resp = client.get(f"/api/texts/{text_id}", headers=headers)
    assert resp.json()["progress"]["status"] == "started"

    # Complete reading
    resp = client.post(f"/api/texts/{text_id}/complete", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["progress"]["status"] == "completed"

    # Verify completed
    resp = client.get(f"/api/texts/{text_id}", headers=headers)
    assert resp.json()["progress"]["status"] == "completed"

    # 404 for start/complete on non-existent text
    resp = client.post("/api/texts/99999/start", headers=headers)
    assert resp.status_code == 404

    resp = client.post("/api/texts/99999/complete", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_texts_progress_endpoint(tmp_path):
    """Progress endpoint returns stats for the user."""
    from bot.db import init_db
    from bot.miniapp_api import create_miniapp_api

    db_path = tmp_path / "texts_prog.db"
    await init_db(str(db_path))
    async with aiosqlite.connect(str(db_path)) as conn:
        conn.row_factory = aiosqlite.Row
        from bot.services.text_library_service import seed_texts
        await seed_texts(conn=conn)

    app = create_miniapp_api(db_path=str(db_path), bot_token="bot-token")
    client = TestClient(app)
    user_id = 99
    headers = {"X-Telegram-Init-Data": _signed_init_data("bot-token", user_id=user_id)}

    # Before any activity
    resp = client.get("/api/texts/progress", headers=headers)
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["total_texts"] > 0
    assert stats["started"] == 0
    assert stats["completed"] == 0
    assert stats["completion_rate"] == 0.0
    assert stats["bookmarks"] == []

    # Start and complete one text
    resp = client.get("/api/texts", headers=headers)
    text_id = resp.json()["texts"][0]["id"]
    client.post(f"/api/texts/{text_id}/start", headers=headers)
    client.post(f"/api/texts/{text_id}/complete", headers=headers)

    resp = client.get("/api/texts/progress", headers=headers)
    stats = resp.json()
    assert stats["started"] >= 1
    assert stats["completed"] >= 1
    assert stats["completion_rate"] > 0
