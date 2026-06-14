"""Tests for E204 learning path recommendations."""

import os
import tempfile
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
import pytest_asyncio
from aiogram.types import Chat, Message, User


class DummyMessage:
    def __init__(self, user_id: int = 1):
        self.from_user = User(id=user_id, is_bot=False, first_name="Test")
        self.answer = AsyncMock()


def make_message(text: str, user_id: int = 1) -> Message:
    return Message(
        message_id=user_id,
        date=0,
        text=text,
        from_user=User(id=user_id, is_bot=False, first_name="Test"),
        chat=Chat(id=user_id, type="private"),
        sender_chat=None,
    )


@pytest_asyncio.fixture
async def db():
    """Creates an isolated DB and points bot.db.get_conn() to it."""
    import bot.db as bdb
    from bot.db import init_db

    old_db_path = bdb._db_path
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp.name
    tmp.close()
    await init_db(db_path)
    async with aiosqlite.connect(db_path) as conn:
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()
            bdb._db_path = old_db_path
            os.unlink(db_path)


@pytest.mark.asyncio
async def test_learning_path_recommends_topic_from_frequent_correction_category(db):
    """E204: история ошибок должна определять следующий урок."""
    from bot.db import DialogueRepository, UserRepository
    from bot.services.learning_path_service import build_learning_path

    await UserRepository(db).create(204, "A2", "learner")
    dialogues = DialogueRepository(db)
    await dialogues.save(
        204,
        "I have dog",
        "I have a dog",
        topic="family",
        rating=3,
        corrections=[
            {
                "original": "I have dog",
                "corrected": "I have a dog",
                "category": "articles",
            }
        ],
    )
    await dialogues.save(
        204,
        "She is teacher",
        "She is a teacher",
        topic="work",
        rating=3,
        corrections=[
            {
                "original": "She is teacher",
                "corrected": "She is a teacher",
                "category": "grammar/articles",
            }
        ],
    )

    recommendation = await build_learning_path(204, db)

    assert recommendation["recommended_topic"] == "Articles (a/an/the)"
    assert recommendation["weak_areas"][0]["name"] == "Articles"
    assert recommendation["weak_areas"][0]["count"] == 2
    assert "артик" in recommendation["reason"].lower()


@pytest.mark.asyncio
async def test_learning_path_fallback_uses_level_when_history_is_empty(db):
    """E204: без истории /learnpath должен давать безопасный стартовый урок."""
    from bot.db import UserRepository
    from bot.services.learning_path_service import build_learning_path

    await UserRepository(db).create(205, "B1", "newbie")

    recommendation = await build_learning_path(205, db)

    assert recommendation["recommended_topic"] == "Free Talk diagnostic"
    assert "B1" in recommendation["reason"]
    assert recommendation["weak_areas"] == []


@pytest.mark.asyncio
async def test_cmd_learnpath_renders_personal_recommendation(db):
    """E204: команда /learnpath показывает следующий урок в чате."""
    from bot.db import DialogueRepository, UserRepository
    from bot.handlers.dialogue import cmd_learnpath

    await UserRepository(db).create(206, "A2", "learner")
    await DialogueRepository(db).save(
        206,
        "Yesterday I go home",
        "Yesterday I went home",
        topic="daily_routine",
        rating=2,
        corrections=[{"original": "I go", "corrected": "I went", "category": "tense"}],
    )

    message = make_message("/learnpath", user_id=206)
    with patch.object(Message, "answer", new_callable=AsyncMock) as mock_answer:
        await cmd_learnpath(message)

    text = mock_answer.call_args.args[0]
    assert "Learning Path" in text
    assert "Past Simple vs Present Perfect" in text
    assert "1 ошибка" in text or "1 ошибок" in text


@pytest.mark.asyncio
async def test_cmd_learnpath_asks_to_start_when_user_missing(db):
    """E204: незарегистрированный пользователь получает понятный ответ."""
    from bot.handlers.dialogue import cmd_learnpath

    message = make_message("/learnpath", user_id=999999)
    with patch.object(Message, "answer", new_callable=AsyncMock) as mock_answer:
        await cmd_learnpath(message)

    assert "начни с команды /start" in mock_answer.call_args.args[0]
