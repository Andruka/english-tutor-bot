"""Тесты для AI-репетитора английского — Increment 1: Core Chat Loop"""

import pytest
import pytest_asyncio
import aiosqlite
import os
import tempfile
from datetime import datetime


@pytest_asyncio.fixture
async def db():
    """Создаёт временную БД для каждого теста."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp.name
    tmp.close()

    # Импортируем и инициализируем
    import sys

    sys.path.insert(0, "/projects/profitable-telegram-bots-2026/english-tutor-bot")
    from bot.db import init_db

    await init_db(db_path)
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        yield conn

    os.unlink(db_path)


@pytest.mark.asyncio
async def test_create_user(db):
    """RED: Создание пользователя в БД."""
    from bot.db import UserRepository

    repo = UserRepository(db)
    user = await repo.create(
        user_id=12345,
        level="B1",
        username="testuser",
    )

    assert user is not None
    assert user.user_id == 12345
    assert user.level == "B1"
    assert user.username == "testuser"
    assert user.dialogues_today == 0
    assert user.subscription is False
    assert user.streak == 0
    assert isinstance(user.created_at, datetime)


@pytest.mark.asyncio
async def test_get_user(db):
    """RED: Получение пользователя по user_id."""
    from bot.db import UserRepository

    repo = UserRepository(db)
    await repo.create(user_id=12345, level="A2", username="testuser")

    user = await repo.get(12345)
    assert user is not None
    assert user.user_id == 12345
    assert user.level == "A2"


@pytest.mark.asyncio
async def test_get_user_not_found(db):
    """RED: Несуществующий пользователь возвращает None."""
    from bot.db import UserRepository

    repo = UserRepository(db)
    user = await repo.get(99999)
    assert user is None


@pytest.mark.asyncio
async def test_update_level(db):
    """RED: Обновление уровня пользователя."""
    from bot.db import UserRepository

    repo = UserRepository(db)
    await repo.create(user_id=12345, level="A2", username="testuser")

    updated = await repo.update_level(12345, "C1")
    assert updated.level == "C1"

    user = await repo.get(12345)
    assert user.level == "C1"


@pytest.mark.asyncio
async def test_daily_dialogue_limit(db):
    """RED: Счётчик диалогов сбрасывается каждый день."""
    from bot.db import UserRepository

    repo = UserRepository(db)
    await repo.create(user_id=12345, level="B1", username="testuser")

    # Симулируем 5 диалогов
    for _ in range(5):
        await repo.increment_dialogues(12345)

    user = await repo.get(12345)
    assert user.dialogues_today == 5

    # Должен быть заблокирован
    assert user.dialogues_today >= 5

    # Симулируем новый день
    await repo.reset_daily_dialogues()

    user = await repo.get(12345)
    assert user.dialogues_today == 0


@pytest.mark.asyncio
async def test_subscription_status(db):
    """RED: Статус подписки пользователя."""
    from bot.db import UserRepository

    repo = UserRepository(db)
    await repo.create(user_id=12345, level="B1", username="testuser")

    user = await repo.get(12345)
    assert user.subscription is False

    await repo.set_subscription(12345, True)
    user = await repo.get(12345)
    assert user.subscription is True


@pytest.mark.asyncio
async def test_save_dialogue(db):
    """RED: Сохранение истории диалога."""
    from bot.db import DialogueRepository

    repo = DialogueRepository(db)
    dialogue_id = await repo.save(
        user_id=12345,
        topic="introduction",
        user_message="Hello, my name is John",
        ai_reply="Hi John! Nice to meet you.",
        rating=4,
        corrections=[],
    )

    assert dialogue_id is not None

    history = await repo.get_history(12345, limit=10)
    assert len(history) == 1
    assert history[0].topic == "introduction"


@pytest.mark.asyncio
async def test_user_streak(db):
    """RED: Подсчёт streak (дней подряд)."""
    from bot.db import UserRepository

    repo = UserRepository(db)
    await repo.create(user_id=12345, level="B1", username="testuser")
    await repo.update_streak(12345)

    user = await repo.get(12345)
    assert user.streak >= 1
