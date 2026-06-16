"""Mini App FastAPI server entrypoint.

Usage:
    cd /projects/english-tutor-bot
    .venv/bin/uvicorn mini_app.main:app --host 0.0.0.0 --port 8081

Environment:
    TELEGRAM_BOT_TOKEN   — required for init data validation
    DB_PATH              — default: data/tutor.db
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import aiosqlite
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import FileResponse

# Ensure project root is on sys.path so bot.miniapp_api resolves
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from bot.db import init_db
from bot.miniapp_api import create_miniapp_api
from bot.services.text_library_service import seed_texts

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DB_PATH = os.environ.get("DB_PATH", str(_project_root / "data" / "tutor.db"))


async def _init_and_seed() -> None:
    """Ensure DB is initialized and seeded before first request."""
    await init_db(DB_PATH)
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        await seed_texts(conn=conn)


# Create the API app (FastAPI instance with placement + text endpoints)
app = create_miniapp_api(db_path=DB_PATH, bot_token=BOT_TOKEN)


@app.on_event("startup")
async def on_startup() -> None:
    await _init_and_seed()

# Mount static files — serves index.html at / and other static assets
static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


# Catch-all for SPA: serve index.html for any unmatched path that might be a client-side route
# (StaticFiles with html=True handles subdirectory index.html; this covers other unmatched paths)
_static_index = static_dir / "index.html"


@app.get("/{path:path}")
async def spa_fallback(request: Request, path: str):
    # Don't interfere with API routes
    if path.startswith("api/") or path == "health":
        from starlette.responses import JSONResponse
        return JSONResponse({"detail": "Not found"}, status_code=404)
    # Serve index.html for SPA routes
    return FileResponse(str(_static_index))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("mini_app.main:app", host="0.0.0.0", port=8081, reload=True)