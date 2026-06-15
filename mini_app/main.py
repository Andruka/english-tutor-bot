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

from fastapi.staticfiles import StaticFiles

# Ensure project root is on sys.path so bot.miniapp_api resolves
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from bot.miniapp_api import create_miniapp_api

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DB_PATH = os.environ.get("DB_PATH", str(_project_root / "data" / "tutor.db"))

# Create the API app (FastAPI instance with placement endpoints)
app = create_miniapp_api(db_path=DB_PATH, bot_token=BOT_TOKEN)

# Mount static files — serves index.html at / and other static assets
static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("mini_app.main:app", host="0.0.0.0", port=8081, reload=True)