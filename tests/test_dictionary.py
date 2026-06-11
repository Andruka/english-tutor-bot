"""Тесты SRS-словаря и DictionaryRepository."""

import pytest
import pytest_asyncio
import tempfile
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from aiogram.types import Message, User, Chat, CallbackQuery

from bot.db import init_db, get_conn, DictionaryRepository


def make_message(text: str, user_id: int = 1) -> Message:
    return Message(
        message_id=user_id,
        date=0,
        text=text,
        from_user=User(
            id=user_id, is_bot=False, first_name="Test", username="TestUser"
        ),
        chat=Chat(id=user_id, type="private"),
        sender_chat=None,
    )


def make_callback(data: str, user_id: int = 1) -> CallbackQuery:
    msg = make_message("/dict", user_id=user_id)
    return CallbackQuery(
        id="cb1",
        from_user=User(id=user_id, is_bot=False, first_name="Test"),
        chat_instance="test",
        message=msg,
        data=data,
    )


@pytest_asyncio.fixture
async def dict_db():
    """Создаёт временную БД с таблицей dictionary."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    import bot.db as bdb

    old_path = bdb._db_path
    bdb._db_path = db_path
    await init_db(db_path)
    yield db_path
    bdb._db_path = old_path
    os.unlink(db_path)


@pytest_asyncio.fixture
async def repo(dict_db):
    conn = await get_conn()
    return DictionaryRepository(conn)


# ─── Repository Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_word(repo):
    entry = await repo.add_word(1, "hello", "привет", "Hello, how are you?")
    assert entry is not None
    assert entry.word == "hello"
    assert entry.translation == "привет"
    assert entry.context == "Hello, how are you?"
    assert entry.level == "new"


@pytest.mark.asyncio
async def test_add_duplicate_word(repo):
    await repo.add_word(1, "hello", "привет")
    entry2 = await repo.add_word(1, "hello", "привет")
    # Должен вернуть существующую запись
    assert entry2 is not None
    assert entry2.word == "hello"


@pytest.mark.asyncio
async def test_get_by_word(repo):
    await repo.add_word(1, "yesterday", "вчера")
    entry = await repo.get_by_word(1, "YESTERDAY")  # case-insensitive
    assert entry is not None
    assert entry.word == "yesterday"


@pytest.mark.asyncio
async def test_get_word_by_id(repo):
    entry = await repo.add_word(1, "book", "книга")
    found = await repo.get_word_by_id(entry.word_id)
    assert found is not None
    assert found.word == "book"


@pytest.mark.asyncio
async def test_count(repo):
    await repo.add_word(1, "apple", "яблоко")
    await repo.add_word(1, "banana", "банан")
    await repo.add_word(2, "cherry", "вишня")  # другой пользователь
    assert await repo.count(1) == 2
    assert await repo.count(2) == 1


@pytest.mark.asyncio
async def test_get_due_words_new(repo):
    """Новые слова должны появляться на повторение на следующий день."""
    await repo.add_word(1, "hello", "привет")
    due = await repo.get_due_words(1)
    # Новое слово — на повторение через 1 день, так что сейчас оно не в due
    assert len(due) == 0


@pytest.mark.asyncio
async def test_get_due_words_none(repo):
    """Слово с future next_review не должно быть в due."""
    from bot.db import get_conn

    conn = await get_conn()
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    await conn.execute(
        "INSERT INTO dictionary (user_id, word, translation, next_review) VALUES (?, ?, ?, ?)",
        (1, "later", "позже", future),
    )
    await conn.commit()
    due = await repo.get_due_words(1)
    assert len(due) == 0


@pytest.mark.asyncio
async def test_sm2_review_quality_0(repo):
    """quality=0 (забыл) → сброс интервала и повторений."""
    entry = await repo.add_word(1, "test", "тест")
    updated = await repo.mark_reviewed(entry.word_id, quality=0)
    assert updated.interval_days == 1
    assert updated.repetitions == 0
    assert updated.level == "learning"


@pytest.mark.asyncio
async def test_sm2_review_quality_3(repo):
    """quality=3 (знаю) → увеличение интервала."""
    entry = await repo.add_word(1, "test", "тест")
    updated = await repo.mark_reviewed(entry.word_id, quality=3)
    assert updated.interval_days in [1, 3]  # 1-й повтор = 1 день
    assert updated.repetitions == 1
    assert updated.level == "reviewing"


@pytest.mark.asyncio
async def test_sm2_mastered_level(repo):
    """После 5 успешных повторений — уровень mastered."""
    entry = await repo.add_word(1, "master", "освоить")
    for q in [3, 3, 3, 3, 3]:
        entry = await repo.mark_reviewed(entry.word_id, quality=q)
    assert entry.level == "mastered"


@pytest.mark.asyncio
async def test_remove_word(repo):
    entry = await repo.add_word(1, "temp", "временный")
    assert await repo.remove_word(entry.word_id)
    assert await repo.get_word_by_id(entry.word_id) is None


@pytest.mark.asyncio
async def test_get_all(repo):
    await repo.add_word(1, "a", "а")
    await repo.add_word(1, "b", "б")
    all_words = await repo.get_all(1)
    assert len(all_words) == 2


# ─── Handler Tests ────────────────────────────────────────────────────────────


@patch.object(Message, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_dict_empty(mock_answer):
    """/dict для пустого словаря."""
    from bot.handlers.dictionary import cmd_dict
    from bot.db import init_db
    import tempfile
    import os
    import bot.db as bdb

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    old_path = bdb._db_path
    bdb._db_path = db_path
    await init_db(db_path)

    try:
        msg = make_message("/dict", user_id=1)
        await cmd_dict(msg)
        mock_answer.assert_called_once()
        text = mock_answer.call_args[0][0]
        assert "0" in text or "словарь" in text.lower()
    finally:
        bdb._db_path = old_path
        os.unlink(db_path)


@patch.object(Message, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_add_word(mock_answer):
    """/add hello = привет."""
    from bot.handlers.dictionary import cmd_add_word
    from bot.db import init_db
    import tempfile
    import os
    import bot.db as bdb

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    old_path = bdb._db_path
    bdb._db_path = db_path
    await init_db(db_path)

    try:
        msg = make_message("/add hello = привет", user_id=1)
        await cmd_add_word(msg)
        mock_answer.assert_called_once()
        text = mock_answer.call_args[0][0]
        assert "hello" in text
        assert "добавлено" in text
    finally:
        bdb._db_path = old_path
        os.unlink(db_path)


@patch.object(Message, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_add_help(mock_answer):
    """/add без аргументов показывает справку."""
    from bot.handlers.dictionary import cmd_add_word

    msg = make_message("/add", user_id=1)
    await cmd_add_word(msg)
    mock_answer.assert_called_once()
    text = mock_answer.call_args[0][0]
    assert "/add" in text or "Как добавить" in text


@patch.object(Message, "answer_document", new_callable=AsyncMock)
@patch.object(Message, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_export_csv(mock_answer, mock_answer_doc):
    """/export_csv с несколькими словами."""
    from bot.handlers.dictionary import cmd_export_csv
    from bot.db import init_db, DictionaryRepository, get_conn
    import tempfile
    import os
    import bot.db as bdb

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    old_path = bdb._db_path
    bdb._db_path = db_path
    await init_db(db_path)

    try:
        # Добавляем тестовые слова
        conn = await get_conn()
        repo = DictionaryRepository(conn)
        await repo.add_word(1, "hello", "привет", context="Hello world")
        await repo.add_word(1, "cat", "кошка", context="My cat is cute")

        msg = make_message("/export_csv", user_id=1)
        await cmd_export_csv(msg)

        mock_answer_doc.assert_called_once()
        call_kwargs = mock_answer_doc.call_args[1]
        assert "caption" in call_kwargs
        assert "CSV" in call_kwargs["caption"]
        assert "2" in call_kwargs["caption"]

        # Проверяем содержимое файла
        file_arg = mock_answer_doc.call_args[0][0]
        content = file_arg.data.decode("utf-8")
        assert "\ufeff" in content  # BOM
        assert "word,translation" in content.replace(" ", "")
        assert "hello" in content
        assert "cat" in content
        assert "привет" in content
        assert "кошка" in content
    finally:
        bdb._db_path = old_path
        os.unlink(db_path)


@patch.object(Message, "answer_document", new_callable=AsyncMock)
@patch.object(Message, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_export_json(mock_answer, mock_answer_doc):
    """/export_json с несколькими словами."""
    from bot.handlers.dictionary import cmd_export_json
    from bot.db import init_db, DictionaryRepository, get_conn
    import tempfile
    import os
    import bot.db as bdb

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    old_path = bdb._db_path
    bdb._db_path = db_path
    await init_db(db_path)

    try:
        conn = await get_conn()
        repo = DictionaryRepository(conn)
        await repo.add_word(1, "hello", "привет", context="Hello world")
        await repo.add_word(1, "cat", "кошка", context="My cat is cute")

        msg = make_message("/export_json", user_id=1)
        await cmd_export_json(msg)

        mock_answer_doc.assert_called_once()
        call_kwargs = mock_answer_doc.call_args[1]
        assert "caption" in call_kwargs
        assert "JSON" in call_kwargs["caption"]
        assert "2" in call_kwargs["caption"]

        file_arg = mock_answer_doc.call_args[0][0]
        content = file_arg.data.decode("utf-8")
        assert "hello" in content
        assert "cat" in content
        assert "привет" in content
        assert '"context": "Hello world"' in content
    finally:
        bdb._db_path = old_path
        os.unlink(db_path)


@patch.object(Message, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_export_csv_empty(mock_answer):
    """/export_csv для пустого словаря."""
    from bot.handlers.dictionary import cmd_export_csv
    from bot.db import init_db
    import tempfile
    import os
    import bot.db as bdb

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    old_path = bdb._db_path
    bdb._db_path = db_path
    await init_db(db_path)

    try:
        msg = make_message("/export_csv", user_id=1)
        await cmd_export_csv(msg)
        mock_answer.assert_called_once()
        text = mock_answer.call_args[0][0]
        assert "пока нет" in text
    finally:
        bdb._db_path = old_path
        os.unlink(db_path)


@patch.object(Message, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_export_json_empty(mock_answer):
    """/export_json для пустого словаря."""
    from bot.handlers.dictionary import cmd_export_json
    from bot.db import init_db
    import tempfile
    import os
    import bot.db as bdb

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    old_path = bdb._db_path
    bdb._db_path = db_path
    await init_db(db_path)

    try:
        msg = make_message("/export_json", user_id=1)
        await cmd_export_json(msg)
        mock_answer.assert_called_once()
        text = mock_answer.call_args[0][0]
        assert "пока нет" in text
    finally:
        bdb._db_path = old_path
        os.unlink(db_path)
