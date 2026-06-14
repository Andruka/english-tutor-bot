"""Тесты хендлеров — имитация команд и сообщений.

Message в aiogram 3 — frozen Pydantic, поэтому mock через patch.object на классе.
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from aiogram.types import Message, User, Chat


def make_message(
    text: str,
    user_id: int = 1,
    username: str = "TestUser",
    first_name: str = "Test",
) -> Message:
    """Создаёт имитацию Message для тестов хендлеров."""
    return Message(
        message_id=user_id,
        date=0,
        text=text,
        from_user=User(
            id=user_id, is_bot=False, first_name=first_name, username=username
        ),
        chat=Chat(id=user_id, type="private"),
        sender_chat=None,
        # bot создадим отдельно, если нужно
    )


@pytest.mark.asyncio
async def test_cmd_start_new_user():
    """/start для нового пользователя предлагает выбор уровня."""
    from bot.handlers.start import cmd_start
    from bot.db import init_db
    import tempfile
    import os

    # Инициализируем тестовую БД
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    import bot.db as bdb

    old_db_path = bdb._db_path
    bdb._db_path = db_path
    await init_db(db_path)

    try:
        with patch.object(Message, "answer", new_callable=AsyncMock) as mock_answer:
            msg = make_message("/start", user_id=100)
            await cmd_start(msg, command=SimpleNamespace(args=None))
            mock_answer.assert_called_once()
            text = mock_answer.call_args[0][0]
            assert "Привет" in text or "уровень" in text.lower()
            text_lower = text.lower()
            assert any(kw in text_lower for kw in ["a1", "a2", "выбери"])
    finally:
        bdb._db_path = old_db_path
        os.unlink(db_path)


@pytest.mark.asyncio
async def test_cmd_start_new_user_offers_placement_test_or_manual_level_choice():
    """Новый пользователь в onboarding видит inline-выбор: тест или ручной уровень."""
    from bot.handlers.start import cmd_start
    from bot.db import init_db
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    import bot.db as bdb

    old_db_path = bdb._db_path
    bdb._db_path = db_path
    await init_db(db_path)

    try:
        with patch.object(Message, "answer", new_callable=AsyncMock) as mock_answer:
            msg = make_message("/start", user_id=101)
            await cmd_start(msg, command=SimpleNamespace(args=None))

            mock_answer.assert_called_once()
            reply_markup = mock_answer.call_args.kwargs["reply_markup"]
            rows = reply_markup.inline_keyboard
            assert rows[0][0].text == "🎯 Пройти тест"
            assert rows[0][0].callback_data == "onboarding_start_placement"
            assert rows[1][0].text == "✋ Выбрать уровень сам"
            assert rows[1][0].callback_data == "onboarding_choose_level"
    finally:
        bdb._db_path = old_db_path
        os.unlink(db_path)


@pytest.mark.asyncio
async def test_onboarding_choose_level_shows_existing_level_keyboard():
    """Inline-выбор ручного уровня открывает текущую reply-клавиатуру уровней."""
    from bot.handlers.start import cb_onboarding_choose_level

    callback = SimpleNamespace(
        message=SimpleNamespace(answer=AsyncMock()),
        answer=AsyncMock(),
    )

    await cb_onboarding_choose_level(callback)

    callback.answer.assert_awaited_once()
    callback.message.answer.assert_awaited_once()
    reply_markup = callback.message.answer.await_args.kwargs["reply_markup"]
    assert [row[0].text for row in reply_markup.keyboard] == [
        "A1",
        "A2",
        "B1",
        "B2",
        "C1",
    ]


@pytest.mark.asyncio
async def test_onboarding_start_placement_delegates_to_placement_handler():
    """Inline-выбор теста запускает placement flow для пользователя callback."""
    from bot.handlers import start

    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=202),
        message=SimpleNamespace(message_id=33),
        answer=AsyncMock(),
    )

    with patch.object(start, "_start_new_test", new_callable=AsyncMock) as mock_start_test:
        await start.cb_onboarding_start_placement(callback)

    callback.answer.assert_awaited_once()
    mock_start_test.assert_awaited_once_with(202, callback.message)


@patch.object(Message, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_help(mock_answer):
    """/help показывает справку."""
    from bot.handlers.start import cmd_help

    msg = make_message("/help")
    await cmd_help(msg)

    mock_answer.assert_called_once()
    text = mock_answer.call_args[0][0]
    assert "команды" in text.lower() or "/start" in text


@pytest.mark.asyncio
async def test_cmd_stats_without_user():
    """/stats для незарегистрированного пользователя."""
    from bot.handlers.dialogue import cmd_stats
    from bot.db import init_db
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    import bot.db as bdb

    old_db_path = bdb._db_path
    bdb._db_path = db_path
    await init_db(db_path)

    try:
        with patch.object(Message, "answer", new_callable=AsyncMock) as mock_answer:
            msg = make_message("/stats", user_id=9999)
            await cmd_stats(msg)
            mock_answer.assert_called_once()
            text = mock_answer.call_args[0][0]
            assert "/start" in text
    finally:
        bdb._db_path = old_db_path
        os.unlink(db_path)


@patch.object(Message, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_new_session(mock_answer):
    """/new сбрасывает сессию."""
    from bot.handlers.dialogue import cmd_new, _tutor_sessions

    _tutor_sessions[42] = "dummy"

    msg = make_message("/new", user_id=42)
    await cmd_new(msg)

    assert 42 not in _tutor_sessions
    mock_answer.assert_called_once()
    text = mock_answer.call_args[0][0]
    assert "Новая" in text or "сессия" in text.lower()


@patch.object(Message, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_stats_with_data(mock_answer):
    """/stats для пользователя с диалогами, навыками и словами."""
    from bot.handlers.dialogue import cmd_stats
    from bot.db import UserRepository, init_db, DictionaryRepository, DialogueRepository
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    import bot.db as bdb

    old_db_path = bdb._db_path
    bdb._db_path = db_path
    await init_db(db_path)

    try:
        conn = await bdb.get_conn()
        repo = UserRepository(conn)
        await repo.create(user_id=202, level="B1", username="stats_user")
        await conn.close()

        conn = await bdb.get_conn()
        dia_repo = DialogueRepository(conn)
        await dia_repo.save(202, "Hello", "Hi there!", rating=4)
        await dia_repo.save(202, "How are you?", "I'm fine", rating=5)
        dict_repo = DictionaryRepository(conn)
        await dict_repo.add_word(202, "hello", "привет")
        await dict_repo.add_word(202, "world", "мир")
        from bot.services.progress_service import SkillProgressRepository

        skill_repo = SkillProgressRepository(conn)
        await skill_repo.award_points(202, "vocabulary", 30)
        await skill_repo.award_points(202, "grammar", 20)
        await conn.close()

        msg = make_message("/stats", user_id=202)
        await cmd_stats(msg)
        mock_answer.assert_called_once()
        text = mock_answer.call_args[0][0]
        assert "Прогресс-панель" in text
        assert "Streak" in text
        assert "Диалогов" in text
        assert "Слов" in text
        assert "Средняя оценка" in text
        assert "Навыки" in text
        assert "Достижения" in text
    finally:
        bdb._db_path = old_db_path
        os.unlink(db_path)


@patch.object(Message, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_stats_shows_avg_rating(mock_answer):
    """/stats показывает среднюю оценку."""
    from bot.handlers.dialogue import cmd_stats
    from bot.db import UserRepository, init_db, DialogueRepository
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    import bot.db as bdb

    old_db_path = bdb._db_path
    bdb._db_path = db_path
    await init_db(db_path)

    try:
        conn = await bdb.get_conn()
        repo = UserRepository(conn)
        await repo.create(user_id=203, level="A2", username="rating_user")
        await conn.close()

        conn = await bdb.get_conn()
        dia_repo = DialogueRepository(conn)
        await dia_repo.save(203, "Hi", "Hello", rating=5)
        await dia_repo.save(203, "Bye", "Goodbye", rating=3)
        await conn.close()

        msg = make_message("/stats", user_id=203)
        await cmd_stats(msg)
        mock_answer.assert_called_once()
        text = mock_answer.call_args[0][0]
        assert "Средняя оценка" in text
        assert "4" in text  # (5+3)/2 = 4.0
    finally:
        bdb._db_path = old_db_path
        os.unlink(db_path)


@pytest.mark.asyncio
async def test_topic_selection():
    """Выбор темы через текст в handle_text_dialogue."""
    from bot.handlers.dialogue import handle_text_dialogue, _user_topics
    from bot.db import UserRepository, init_db, get_conn
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    import bot.db as bdb

    old_db_path = bdb._db_path
    bdb._db_path = db_path
    await init_db(db_path)

    conn = await get_conn()
    try:
        repo = UserRepository(conn)
        await repo.create(user_id=999, level="A2", username="topic_test")
        await conn.close()

        with patch.object(Message, "answer", new_callable=AsyncMock) as mock_answer:
            msg = make_message("travel", user_id=999)
            await handle_text_dialogue(msg)
            assert _user_topics.get(999) == "travel"
            mock_answer.assert_called_once()
            text = mock_answer.call_args[0][0]
            assert "Travel" in text or "travel" in text.lower()
    finally:
        bdb._db_path = old_db_path
        os.unlink(db_path)
