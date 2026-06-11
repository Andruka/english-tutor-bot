"""Тесты хендлера /remind (K004) — настройка напоминаний.

Message в aiogram 3 — frozen Pydantic, поэтому mock через patch.object на классе.
CallbackQuery.message тоже frozen — edit_reply_markup и edit_text мокаем аналогично.
"""

import pytest
import pytest_asyncio
import tempfile
from unittest.mock import AsyncMock, patch
from datetime import date

from aiogram.types import Message, CallbackQuery, User, Chat

from bot.handlers.reminder import (
    cmd_remind,
    cmd_remind_on,
    cmd_remind_off,
    cmd_remind_time,
    cmd_remind_tz,
    cb_remind_on,
    cb_remind_off,
    cb_remind_change_time,
    cb_remind_change_tz,
    cb_remind_select_tz,
    settings_keyboard,
)
from bot.db import ReminderSettingsRepository, init_db


@pytest_asyncio.fixture
async def db():
    """Временная БД для тестов."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    import bot.db as bdb

    old_path = bdb._db_path
    bdb._db_path = f.name
    await init_db(f.name)

    import aiosqlite

    conn = await aiosqlite.connect(f.name)
    conn.row_factory = aiosqlite.Row
    yield conn
    await conn.close()

    os.unlink(f.name)
    bdb._db_path = old_path


import os  # noqa: E402


def _fake_message(text: str, user_id: int = 100) -> Message:
    """Создаёт минимальный объект Message для тестов."""
    return Message(
        message_id=1,
        date=date.today(),
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Test"),
        text=text,
    )


def _fake_callback(data: str, user_id: int = 100) -> CallbackQuery:
    """Создаёт минимальный CallbackQuery для тестов."""
    tgm_user = User(id=user_id, is_bot=False, first_name="Test")
    msg = Message(
        message_id=1,
        date=date.today(),
        chat=Chat(id=user_id, type="private"),
        from_user=tgm_user,
        text="🔔 Напоминания",
    )
    return CallbackQuery(
        id="cb1",
        from_user=tgm_user,
        chat_instance="inst1",
        message=msg,
        data=data,
    )


# ─── /remind ──────────────────────────────────────────────────────


@patch.object(Message, "reply", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_remind_shows_settings(mock_reply, db):
    """/remind показывает настройки пользователя."""
    with patch("bot.handlers.reminder.get_conn", return_value=db):
        msg = _fake_message("/remind")
        await cmd_remind(msg)

        mock_reply.assert_awaited_once()
        args, kwargs = mock_reply.await_args
        assert "Напоминания" in args[0]
        assert "10:00" in args[0]  # дефолтное время
        assert "включены" in args[0].lower()
        assert "reply_markup" in kwargs


@patch.object(Message, "reply", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_remind_after_off(mock_reply, db):
    """После отключения показывает статус отключено."""
    rem_repo = ReminderSettingsRepository(db)
    await rem_repo.ensure_user(100)
    await rem_repo.set_enabled(100, False)

    with patch("bot.handlers.reminder.get_conn", return_value=db):
        msg = _fake_message("/remind")
        await cmd_remind(msg)

        args, _ = mock_reply.await_args
        assert "отключены" in args[0].lower()


# ─── /remind_on / /remind_off ─────────────────────────────────────


@patch.object(Message, "reply", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_remind_on(mock_reply, db):
    """/remind_on включает напоминания."""
    with patch("bot.handlers.reminder.get_conn", return_value=db):
        msg = _fake_message("/remind_on")
        await cmd_remind_on(msg)

        mock_reply.assert_awaited_once()
        args, _ = mock_reply.await_args
        assert "включены" in args[0].lower()

        repo = ReminderSettingsRepository(db)
        settings = await repo.get(100)
        assert settings is not None
        assert settings.enabled is True


@patch.object(Message, "reply", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_remind_off(mock_reply, db):
    """/remind_off отключает напоминания."""
    rem_repo = ReminderSettingsRepository(db)
    await rem_repo.ensure_user(100)

    with patch("bot.handlers.reminder.get_conn", return_value=db):
        msg = _fake_message("/remind_off")
        await cmd_remind_off(msg)

        mock_reply.assert_awaited_once()
        args, _ = mock_reply.await_args
        assert "отключены" in args[0].lower()

        repo = ReminderSettingsRepository(db)
        settings = await repo.get(100)
        assert settings.enabled is False


@patch.object(Message, "reply", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_remind_time_valid(mock_reply, db):
    """/remind_time HH:MM устанавливает время."""
    with patch("bot.handlers.reminder.get_conn", return_value=db):
        msg = _fake_message("/remind_time 14:30")
        await cmd_remind_time(msg)

        mock_reply.assert_awaited_once()
        args, _ = mock_reply.await_args
        assert "14:30" in args[0]

        repo = ReminderSettingsRepository(db)
        settings = await repo.get(100)
        assert settings.remind_time == "14:30"


@patch.object(Message, "reply", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_remind_time_no_args(mock_reply, db):
    """Без аргументов — показывает подсказку."""
    with patch("bot.handlers.reminder.get_conn", return_value=db):
        msg = _fake_message("/remind_time")
        await cmd_remind_time(msg)

        mock_reply.assert_awaited_once()
        args, _ = mock_reply.await_args
        assert "Укажите время" in args[0]


@patch.object(Message, "reply", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_remind_time_invalid(mock_reply, db):
    """Невалидный формат — ошибка."""
    with patch("bot.handlers.reminder.get_conn", return_value=db):
        msg = _fake_message("/remind_time 25:00")
        await cmd_remind_time(msg)

        mock_reply.assert_awaited_once()
        args, _ = mock_reply.await_args
        assert "Неправильный" in args[0]


@patch.object(Message, "reply", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_remind_time_hour_only(mock_reply, db):
    """/remind_time 9 → 09:00."""
    with patch("bot.handlers.reminder.get_conn", return_value=db):
        msg = _fake_message("/remind_time 9")
        await cmd_remind_time(msg)

        args, _ = mock_reply.await_args
        assert "09:00" in args[0]


# ─── /remind_tz ────────────────────────────────────────────────────


@patch.object(Message, "reply", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_remind_tz_valid(mock_reply, db):
    """/remind_tz Europe/Moscow — устанавливает часовой пояс."""
    with patch("bot.handlers.reminder.get_conn", return_value=db):
        msg = _fake_message("/remind_tz Europe/Moscow")
        await cmd_remind_tz(msg)

        mock_reply.assert_awaited_once()
        args, _ = mock_reply.await_args
        assert "Europe/Moscow" in args[0]

        repo = ReminderSettingsRepository(db)
        settings = await repo.get(100)
        assert settings.timezone == "Europe/Moscow"


@patch.object(Message, "reply", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_remind_tz_no_args(mock_reply, db):
    """Без аргументов — показывает список популярных."""
    with patch("bot.handlers.reminder.get_conn", return_value=db):
        msg = _fake_message("/remind_tz")
        await cmd_remind_tz(msg)

        mock_reply.assert_awaited_once()
        args, _ = mock_reply.await_args
        assert "Укажите часовой пояс" in args[0]
        assert "Europe/Moscow" in args[0]


@patch.object(Message, "reply", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cmd_remind_tz_invalid(mock_reply, db):
    """Неизвестный часовой пояс — ошибка."""
    with patch("bot.handlers.reminder.get_conn", return_value=db):
        msg = _fake_message("/remind_tz Mars/Olympus")
        await cmd_remind_tz(msg)

        mock_reply.assert_awaited_once()
        args, _ = mock_reply.await_args
        assert "не найден" in args[0]


# ─── Callback: remind_on / remind_off ──────────────────────────────


@patch.object(Message, "edit_reply_markup", new_callable=AsyncMock)
@patch.object(CallbackQuery, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cb_remind_on(mock_answer, mock_edit, db):
    """Инлайн-кнопка включения."""
    with patch("bot.handlers.reminder.get_conn", return_value=db):
        cb = _fake_callback("remind_on")
        await cb_remind_on(cb)

        mock_answer.assert_awaited_once_with("✅ Напоминания включены")

        repo = ReminderSettingsRepository(db)
        settings = await repo.get(100)
        assert settings.enabled is True


@patch.object(Message, "edit_reply_markup", new_callable=AsyncMock)
@patch.object(CallbackQuery, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cb_remind_off(mock_answer, mock_edit, db):
    """Инлайн-кнопка отключения."""
    rem_repo = ReminderSettingsRepository(db)
    await rem_repo.ensure_user(100)

    with patch("bot.handlers.reminder.get_conn", return_value=db):
        cb = _fake_callback("remind_off")
        await cb_remind_off(cb)

        mock_answer.assert_awaited_once_with("🔕 Напоминания отключены")

        repo = ReminderSettingsRepository(db)
        settings = await repo.get(100)
        assert settings.enabled is False


# ─── Callback: remind_change_time / remind_change_tz ──────────────


@patch.object(Message, "answer", new_callable=AsyncMock)
@patch.object(CallbackQuery, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cb_remind_change_time(mock_answer_cb, mock_msg_answer, db):
    """Инлайн-кнопка смены времени: показывает инструкцию."""
    cb = _fake_callback("remind_change_time")
    await cb_remind_change_time(cb)

    mock_msg_answer.assert_awaited_once()
    args, _ = mock_msg_answer.await_args
    assert "/remind_time" in args[0]


@patch.object(Message, "answer", new_callable=AsyncMock)
@patch.object(CallbackQuery, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cb_remind_change_tz(mock_answer_cb, mock_msg_answer, db):
    """Инлайн-кнопка смены часового пояса: показывает выбор."""
    cb = _fake_callback("remind_change_tz")
    await cb_remind_change_tz(cb)

    mock_msg_answer.assert_awaited_once()
    args, kwargs = mock_msg_answer.await_args
    assert "Выберите" in args[0]
    assert "reply_markup" in kwargs


# ─── Callback: remind_tz:XXX ─────────────────────────────────────


@patch.object(Message, "edit_text", new_callable=AsyncMock)
@patch.object(CallbackQuery, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cb_remind_select_tz(mock_answer, mock_edit, db):
    """Выбор часового пояса из инлайн-кнопки."""
    with patch("bot.handlers.reminder.get_conn", return_value=db):
        cb = _fake_callback("remind_tz:Europe/Moscow")
        await cb_remind_select_tz(cb)

        mock_answer.assert_awaited_once_with(
            "✅ Часовой пояс установлен: Europe/Moscow"
        )

        repo = ReminderSettingsRepository(db)
        settings = await repo.get(100)
        assert settings.timezone == "Europe/Moscow"


@patch.object(CallbackQuery, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_cb_remind_select_tz_invalid(mock_answer, db):
    """Неизвестный часовой пояс из кнопки — предупреждение."""
    cb = _fake_callback("remind_tz:Mars/Olympus")
    await cb_remind_select_tz(cb)

    mock_answer.assert_awaited_once_with("❌ Неизвестный часовой пояс", show_alert=True)


# ─── settings_keyboard ─────────────────────────────────────────────


class TestSettingsKeyboard:
    def test_keyboard_has_expected_buttons(self):
        """Клавиатура содержит нужные кнопки."""
        kb = settings_keyboard(
            enabled=True, remind_time="10:00", timezone="Europe/Moscow"
        )
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "remind_off" in callbacks  # toggle off
        assert "remind_change_time" in callbacks
        assert "remind_change_tz" in callbacks

    def test_keyboard_disabled_shows_on(self):
        """При отключённом — кнопка включения."""
        kb = settings_keyboard(
            enabled=False, remind_time="10:00", timezone="Europe/Moscow"
        )
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "remind_on" in callbacks
        assert "remind_off" not in callbacks
