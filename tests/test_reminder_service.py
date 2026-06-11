"""Тесты reminder_service (K004) — уведомления и streak-напоминания."""

import pytest
import pytest_asyncio
import tempfile
from unittest.mock import AsyncMock
from datetime import date, timedelta

from aiogram import Bot

from bot.db import (
    ReminderSettingsRepository,
    ReminderSettings,
    UserRepository,
    init_db,
)
from bot.services.reminder_service import (
    ReminderService,
    parse_remind_time,
    REMINDER_TEXT,
)


@pytest_asyncio.fixture
async def db():
    """Временная БД для тестов."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    await init_db(f.name)

    import aiosqlite

    conn = await aiosqlite.connect(f.name)
    conn.row_factory = aiosqlite.Row
    yield conn
    await conn.close()

    import os

    os.unlink(f.name)


@pytest_asyncio.fixture
async def seeded_db(db):
    """БД с пользователями и настройками напоминаний."""
    user_repo = UserRepository(db)
    rem_repo = ReminderSettingsRepository(db)

    # 4 пользователя
    await user_repo.create(1000, "A1", "no_remind")  # без напоминаний
    await user_repo.create(1001, "A1", "with_remind")  # с напоминанием
    await user_repo.create(1002, "A1", "studied_today")  # уже занимался сегодня
    await user_repo.create(1003, "A1", "streak_user")  # с высоким streak

    # Настройки напоминаний
    # user 1001 — обычное напоминание на 10:00
    await rem_repo.upsert(
        ReminderSettings(user_id=1001, remind_time="10:00", enabled=True)
    )
    # user 1002 — тоже напоминание, но отметим что занимался
    await rem_repo.upsert(
        ReminderSettings(user_id=1002, remind_time="10:00", enabled=True)
    )
    # user 1003 — напоминание + streak
    await rem_repo.upsert(
        ReminderSettings(user_id=1003, remind_time="10:00", enabled=True)
    )

    # User 1002 занимался сегодня
    today = date.today()
    yesterday = today - timedelta(days=1)
    await db.execute(
        "UPDATE users SET dialogues_today = 3, last_dialogue_date = ?, streak = 5 WHERE user_id = 1002",
        (today.isoformat(),),
    )
    # User 1003: high streak, занимался вчера, сегодня нет
    await db.execute(
        "UPDATE users SET dialogues_today = 0, last_dialogue_date = ?, streak = 7 WHERE user_id = 1003",
        (yesterday.isoformat(),),
    )
    await db.commit()

    yield db


# ─── parse_remind_time ─────────────────────────────────────────────


class TestParseRemindTime:
    def test_valid_hh_mm(self):
        assert parse_remind_time("09:00") == "09:00"

    def test_valid_h_m(self):
        assert parse_remind_time("9:30") == "09:30"

    def test_valid_hour_only(self):
        assert parse_remind_time("21") == "21:00"

    def test_valid_single_digit_hour(self):
        assert parse_remind_time("8") == "08:00"

    def test_midnight(self):
        assert parse_remind_time("00:00") == "00:00"

    def test_noon(self):
        assert parse_remind_time("12:00") == "12:00"

    def test_edge_max(self):
        assert parse_remind_time("23:59") == "23:59"

    def test_invalid_hour_too_high(self):
        assert parse_remind_time("24:00") is None

    def test_invalid_minute(self):
        assert parse_remind_time("12:60") is None

    def test_invalid_format(self):
        assert parse_remind_time("abc") is None

    def test_negative_hour(self):
        assert parse_remind_time("-1:00") is None

    def test_empty(self):
        assert parse_remind_time("") is None

    def test_whitespace(self):
        assert parse_remind_time("  10:30  ") == "10:30"

    def test_trailing_garbage(self):
        # "09:00am" — разобьётся на 3 части
        assert parse_remind_time("09:00am") is None


# ─── ReminderService — _should_notify_today ────────────────────────


class TestShouldNotifyToday:
    @pytest.mark.asyncio
    async def test_no_settings_returns_false(self, db):
        """Без настроек — не отправляем."""
        service = ReminderService(
            bot=AsyncMock(spec=Bot),
            reminder_repo=ReminderSettingsRepository(db),
            user_repo=UserRepository(db),
        )
        result = await service._should_notify_today(9999, date.today())
        assert result is False

    @pytest.mark.asyncio
    async def test_disabled_returns_false(self, seeded_db):
        """Отключённые напоминания — не отправляем."""
        rem_repo = ReminderSettingsRepository(seeded_db)
        await rem_repo.set_enabled(1001, False)

        service = ReminderService(
            bot=AsyncMock(spec=Bot),
            reminder_repo=rem_repo,
            user_repo=UserRepository(seeded_db),
        )
        result = await service._should_notify_today(1001, date.today())
        assert result is False

    @pytest.mark.asyncio
    async def test_already_notified_today_returns_false(self, seeded_db):
        """Уже отправили сегодня — не дублируем."""
        rem_repo = ReminderSettingsRepository(seeded_db)
        today = date.today()
        await rem_repo.set_last_notification(1001, today.isoformat())

        service = ReminderService(
            bot=AsyncMock(spec=Bot),
            reminder_repo=rem_repo,
            user_repo=UserRepository(seeded_db),
        )
        result = await service._should_notify_today(1001, today)
        assert result is False

    @pytest.mark.asyncio
    async def test_already_studied_today_returns_false(self, seeded_db):
        """Уже занимался сегодня — не напоминаем."""
        service = ReminderService(
            bot=AsyncMock(spec=Bot),
            reminder_repo=ReminderSettingsRepository(seeded_db),
            user_repo=UserRepository(seeded_db),
        )
        result = await service._should_notify_today(1002, date.today())
        assert result is False

    @pytest.mark.asyncio
    async def test_enabled_no_notifications_yet_returns_true(self, seeded_db):
        """Всё включено, сегодня не занимался — можно отправлять."""
        service = ReminderService(
            bot=AsyncMock(spec=Bot),
            reminder_repo=ReminderSettingsRepository(seeded_db),
            user_repo=UserRepository(seeded_db),
        )
        result = await service._should_notify_today(1001, date.today())
        assert result is True


# ─── ReminderService — _get_notification_text ──────────────────────


class TestGetNotificationText:
    @pytest.mark.asyncio
    async def test_regular_reminder(self, seeded_db):
        """Если занимался вчера и сегодня нет — обычное напоминание."""
        service = ReminderService(
            bot=AsyncMock(spec=Bot),
            reminder_repo=ReminderSettingsRepository(seeded_db),
            user_repo=UserRepository(seeded_db),
        )
        today = date.today()

        # User 1001: у него dialogues_today=0, last_dialogue_date=None (новый юзер)
        text = await service._get_notification_text(1001, today)
        assert text == REMINDER_TEXT

    @pytest.mark.asyncio
    async def test_streak_warning_missed_yesterday(self, seeded_db):
        """Streak ≥ 3, не занимался вчера — предупреждение."""
        service = ReminderService(
            bot=AsyncMock(spec=Bot),
            reminder_repo=ReminderSettingsRepository(seeded_db),
            user_repo=UserRepository(seeded_db),
        )
        today = date.today()

        # User 1003: streak=7, занимался вчера, сегодня нет
        text = await service._get_notification_text(1003, today)
        # must contain streak warning (7 days)
        assert "стрик 7" in text
        assert "под угрозой" in text

    @pytest.mark.asyncio
    async def test_already_studied_today_returns_none(self, seeded_db):
        """Если уже занимался — None."""
        service = ReminderService(
            bot=AsyncMock(spec=Bot),
            reminder_repo=ReminderSettingsRepository(seeded_db),
            user_repo=UserRepository(seeded_db),
        )
        text = await service._get_notification_text(1002, date.today())
        assert text is None


# ─── ReminderService — _send_reminder ──────────────────────────────


class TestSendReminder:
    @pytest.mark.asyncio
    async def test_sends_to_user(self, seeded_db):
        """Отправляет сообщение пользователю."""
        bot = AsyncMock(spec=Bot)
        service = ReminderService(
            bot=bot,
            reminder_repo=ReminderSettingsRepository(seeded_db),
            user_repo=UserRepository(seeded_db),
        )
        await service._send_reminder(1001)
        assert bot.send_message.await_count == 1

    @pytest.mark.asyncio
    async def test_sends_with_keyboard(self, seeded_db):
        """В сообщении есть кнопки."""
        bot = AsyncMock(spec=Bot)
        service = ReminderService(
            bot=bot,
            reminder_repo=ReminderSettingsRepository(seeded_db),
            user_repo=UserRepository(seeded_db),
        )
        await service._send_reminder(1001)
        args, kwargs = bot.send_message.await_args
        assert "reply_markup" in kwargs

    @pytest.mark.asyncio
    async def test_marks_notification_date(self, seeded_db):
        """После отправки проставляется дата."""
        bot = AsyncMock(spec=Bot)
        rem_repo = ReminderSettingsRepository(seeded_db)
        service = ReminderService(
            bot=bot,
            reminder_repo=rem_repo,
            user_repo=UserRepository(seeded_db),
        )
        today = date.today()

        await service._send_reminder(1001)
        settings = await rem_repo.get(1001)
        assert settings.last_notification_date == today.isoformat()

    @pytest.mark.asyncio
    async def test_skips_if_already_notified(self, seeded_db):
        """Нет повторной отправки, если уже отмечали."""
        bot = AsyncMock(spec=Bot)
        rem_repo = ReminderSettingsRepository(seeded_db)
        today = date.today()
        await rem_repo.set_last_notification(1001, today.isoformat())

        service = ReminderService(
            bot=bot,
            reminder_repo=rem_repo,
            user_repo=UserRepository(seeded_db),
        )
        await service._send_reminder(1001)
        # Не должно уйти повторно
        assert bot.send_message.await_count == 0

    @pytest.mark.asyncio
    async def test_handles_bot_exception_gracefully(self, seeded_db):
        """При ошибке отправки — не падает."""
        bot = AsyncMock(spec=Bot)
        bot.send_message.side_effect = Exception("Chat not found")
        service = ReminderService(
            bot=bot,
            reminder_repo=ReminderSettingsRepository(seeded_db),
            user_repo=UserRepository(seeded_db),
        )
        # Не должно выбросить исключение
        await service._send_reminder(1001)
        assert bot.send_message.await_count == 1


# ─── ReminderService — start / stop ────────────────────────────────


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_task(self, db):
        """start() создаёт asyncio.Task."""
        service = ReminderService(
            bot=AsyncMock(spec=Bot),
            reminder_repo=ReminderSettingsRepository(db),
            user_repo=UserRepository(db),
        )
        service.start()
        assert service._task is not None
        assert not service._task.done()
        await service.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, db):
        """stop() останавливает задачу."""
        service = ReminderService(
            bot=AsyncMock(spec=Bot),
            reminder_repo=ReminderSettingsRepository(db),
            user_repo=UserRepository(db),
        )
        service.start()
        await service.stop()
        assert service._task is None

    @pytest.mark.asyncio
    async def test_double_start_noop(self, db):
        """Повторный start не создаёт новую задачу."""
        service = ReminderService(
            bot=AsyncMock(spec=Bot),
            reminder_repo=ReminderSettingsRepository(db),
            user_repo=UserRepository(db),
        )
        service.start()
        task1 = service._task
        service.start()  # noop
        assert service._task is task1
        await service.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self, db):
        """stop() без start не падает."""
        service = ReminderService(
            bot=AsyncMock(spec=Bot),
            reminder_repo=ReminderSettingsRepository(db),
            user_repo=UserRepository(db),
        )
        await service.stop()
        assert service._task is None


# ─── ReminderService — keyboard ────────────────────────────────────


class TestKeyboard:
    def test_get_remind_keyboard_has_buttons(self):
        """Клавиатура содержит ожидаемые кнопки."""
        kb = ReminderService.get_remind_keyboard()
        assert kb.inline_keyboard is not None
        # flat list of callback data
        callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "start_dialog" in callbacks
        assert "remind_off" in callbacks
