"""Конфигурация тестов — добавляет корень проекта в sys.path."""

import asyncio
import sys
from pathlib import Path

import pytest

# Добавляем корень проекта в sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def close_db_connections_after_test():
    """Не оставляем aiosqlite worker threads между тестами."""
    yield

    from bot.db import close_all_connections

    asyncio.run(close_all_connections())
