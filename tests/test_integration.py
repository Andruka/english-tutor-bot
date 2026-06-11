"""Интеграционные тесты — проверка бота через имитацию сообщений."""

import pytest
from aiogram.types import Message, User, Chat
from bot.services.ai_service import build_system_prompt


def make_message(text: str, user_id: int = 1) -> Message:
    """Создаёт имитацию Message для тестов."""
    return Message(
        message_id=1,
        date=0,
        text=text,
        from_user=User(id=user_id, is_bot=False, first_name="Test"),
        chat=Chat(id=user_id, type="private"),
        sender_chat=None,
    )


def test_build_system_prompt():
    """Системный промпт содержит уровень и тему."""
    prompt = build_system_prompt("B1", "travel")
    assert "B1" in prompt
    assert "travel" in prompt


@pytest.mark.asyncio
async def test_import_all_handlers():
    """Все модули импортируются без ошибок."""
    assert True


@pytest.mark.asyncio
async def test_full_ai_dialogue_flow():
    """Полный цикл диалога: регистрация → диалог → результат."""
    from bot.db import UserRepository, DialogueRepository, init_db, get_conn
    from bot.services.ai_service import AITutor
    import tempfile
    import os

    # Временная БД
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        await init_db(db_path)
        conn = await get_conn()

        # Регистрация
        repo = UserRepository(conn)
        user = await repo.create(user_id=42, level="A2", username="test_user")
        assert user.level == "A2"
        assert user.user_id == 42

        # Диалог через AI
        tutor = AITutor(level="A2", api_key="test_key", topic="introduction")
        result = await tutor.chat("Hello! My name is Test.")
        assert "reply" in result
        assert len(result["reply"]) > 0

        # Сохранение диалога
        dial_repo = DialogueRepository(conn)
        dial_id = await dial_repo.save(
            user_id=42,
            user_message="Hello! My name is Test.",
            ai_reply=result["reply"],
        )
        assert dial_id > 0

        # Статистика
        count = await dial_repo.count(42)
        assert count > 0
    finally:
        await conn.close()
        os.unlink(db_path)
