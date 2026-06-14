"""Tests for E205 micro-lessons based on user mistakes."""

from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import Chat, Message, User


def make_message(text: str, user_id: int = 1) -> Message:
    return Message(
        message_id=user_id,
        date=0,
        text=text,
        from_user=User(id=user_id, is_bot=False, first_name="Test"),
        chat=Chat(id=user_id, type="private"),
        sender_chat=None,
    )


@pytest.fixture
async def lesson_db(tmp_path):
    import bot.db as bdb
    from bot.db import UserRepository, get_conn, init_db

    old_db_path = bdb._db_path
    db_path = str(tmp_path / "lessons.db")
    bdb._db_path = db_path
    await init_db(db_path)
    conn = await get_conn()
    await UserRepository(conn).create(123, "A2", "lesson_user")
    try:
        yield conn
    finally:
        await conn.close()
        bdb._db_path = old_db_path


@pytest.mark.asyncio
async def test_generate_micro_lesson_uses_frequent_correction_and_persists(lesson_db):
    """E205: lesson is generated from frequent user errors and saved."""
    from bot.db import DialogueRepository, MicroLessonRepository
    from bot.services.micro_lesson_service import generate_micro_lesson

    dialogue_repo = DialogueRepository(lesson_db)
    await dialogue_repo.save(
        123,
        "Yesterday I go to school",
        "Use went with yesterday.",
        topic="daily_routine",
        rating=3,
        corrections=[
            {
                "original": "I go",
                "corrected": "I went",
                "category": "tense",
                "explanation": "После yesterday нужен Past Simple.",
            }
        ],
    )

    lesson = await generate_micro_lesson(123, "A2", lesson_db)

    assert lesson.lesson_id > 0
    assert "Past Simple" in lesson.topic
    assert "Почему" in lesson.explanation
    assert len(lesson.examples) >= 2
    assert lesson.exercise
    assert lesson.answer_key
    assert lesson.source_errors[0]["original"] == "I go"

    saved = await MicroLessonRepository(lesson_db).get_latest_active(123)
    assert saved is not None
    assert saved.lesson_id == lesson.lesson_id


@pytest.mark.asyncio
async def test_generate_micro_lesson_falls_back_for_new_user(lesson_db):
    """E205: new users get a safe CEFR default lesson without AI/network."""
    from bot.services.micro_lesson_service import generate_micro_lesson

    lesson = await generate_micro_lesson(123, "A2", lesson_db)

    assert lesson.lesson_id > 0
    assert lesson.topic
    assert lesson.source_errors == []
    assert "3 минуты" in lesson.explanation or "мини-урок" in lesson.explanation
    assert lesson.exercise


@pytest.mark.asyncio
async def test_check_lesson_attempt_persists_result(lesson_db):
    """E205: exercise answer can be checked and saved as an attempt."""
    from bot.services.micro_lesson_service import (
        check_lesson_attempt,
        generate_micro_lesson,
    )

    lesson = await generate_micro_lesson(123, "A2", lesson_db)
    result = await check_lesson_attempt(
        123, lesson.lesson_id, lesson.answer_key, lesson_db
    )

    assert result.is_correct is True
    assert result.attempt_id > 0
    assert "верно" in result.feedback.lower() or "отлично" in result.feedback.lower()


@pytest.mark.asyncio
async def test_check_lesson_attempt_wrong_answer_gives_actionable_feedback(lesson_db):
    """E205: wrong exercise answer gets a useful hint and is persisted."""
    from bot.services.micro_lesson_service import (
        check_lesson_attempt,
        generate_micro_lesson,
    )

    lesson = await generate_micro_lesson(123, "A2", lesson_db)
    result = await check_lesson_attempt(
        123, lesson.lesson_id, "I go yesterday", lesson_db
    )

    assert result.is_correct is False
    assert result.attempt_id > 0
    assert lesson.answer_key in result.feedback


@pytest.mark.asyncio
async def test_cmd_lesson_generates_and_checks_attempt(lesson_db):
    """E205: /lesson creates a lesson; /lesson <answer> checks the active exercise."""
    from bot.handlers.dialogue import cmd_lesson

    msg = make_message("/lesson", user_id=123)
    with patch("bot.handlers.dialogue.get_conn", return_value=lesson_db):
        with patch.object(Message, "answer", new_callable=AsyncMock) as mock_answer:
            await cmd_lesson(msg)

    first_text = mock_answer.call_args.args[0]
    assert "Мини-урок" in first_text
    assert "Упражнение" in first_text

    answer_msg = make_message("/lesson I went to school yesterday.", user_id=123)
    with patch("bot.handlers.dialogue.get_conn", return_value=lesson_db):
        with patch.object(Message, "answer", new_callable=AsyncMock) as mock_answer:
            await cmd_lesson(answer_msg)

    checked_text = mock_answer.call_args.args[0]
    assert "Ответ" in checked_text
    assert "верно" in checked_text.lower() or "попробуй" in checked_text.lower()


@pytest.mark.asyncio
async def test_cmd_lesson_requires_start_for_unknown_user(tmp_path):
    """E205: /lesson tells unknown users to run /start instead of crashing."""
    import bot.db as bdb
    from bot.db import get_conn, init_db
    from bot.handlers.dialogue import cmd_lesson

    old_db_path = bdb._db_path
    db_path = str(tmp_path / "unknown.db")
    bdb._db_path = db_path
    await init_db(db_path)
    conn = await get_conn()
    try:
        msg = make_message("/lesson", user_id=999)
        with patch("bot.handlers.dialogue.get_conn", return_value=conn):
            with patch.object(Message, "answer", new_callable=AsyncMock) as mock_answer:
                await cmd_lesson(msg)
        assert "начни с команды /start" in mock_answer.call_args.args[0]
    finally:
        await conn.close()
        bdb._db_path = old_db_path
