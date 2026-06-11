"""Фоновая рассылка ежедневных напоминаний и streak-уведомлений (K004).

Цикл каждую минуту проверяет, кому из пользователей пора отправить напоминание:
- Не отправляет, если пользователь уже занимался сегодня.
- При streak ≥ 3 и пропуске вчерашнего дня → мотивационное предупреждение.
- При обычном пропуске → вежливое напоминание.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from zoneinfo import ZoneInfo

from bot.db import (
    ReminderSettingsRepository,
    UserRepository,
)

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 60  # Проверка каждые 60 секунд

# ─── Тексты сообщений ──────────────────────────────────────────────────

REMINDER_TEXT = (
    "🔔 Пора заниматься английским!\n\n"
    "Всего 5–10 минут в день помогут сохранить прогресс. "
    "Начни прямо сейчас — просто отправь сообщение боту! 🚀"
)

STREAK_WARNING_TEXT = (
    "🔥 Твой стрик {streak} дней под угрозой!\n\n"
    "Ты пропустил вчерашний день. "
    "Занимайся сегодня, чтобы не потерять прогресс! "
    "Отправь любое сообщение и продолжи серию. 💪"
)

STREAK_LOST_TEXT = (
    "😢 Твой стрик {streak} дней прерван.\n\n"
    "Но ничего страшного — начни новую серию сегодня! "
    "Лучший день для нового стрика — прямо сейчас. "
    "Просто напиши сообщение боту 🌟"
)

# ─── Основной сервис ───────────────────────────────────────────────────


class ReminderService:
    """Сервис для фоновой рассылки напоминаний."""

    def __init__(
        self,
        bot: Bot,
        reminder_repo: ReminderSettingsRepository,
        user_repo: UserRepository,
    ):
        self.bot = bot
        self.reminder_repo = reminder_repo
        self.user_repo = user_repo
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._today = date.today()

    @staticmethod
    def get_remind_keyboard() -> InlineKeyboardMarkup:
        """Клавиатура к напоминанию."""
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🎯 Начать урок", callback_data="start_dialog"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="🔕 Отключить напоминания",
                        callback_data="remind_off",
                    ),
                ],
            ]
        )

    async def _should_notify_today(self, user_id: int, today: date) -> bool:
        """Проверяет, нужно ли отправлять уведомление пользователю сегодня.

        Возвращает False, если уведомление уже было отправлено сегодня
        или пользователь уже занимался.
        """
        settings = await self.reminder_repo.get(user_id)
        if not settings or not settings.enabled:
            return False

        # Уже отправили уведомление сегодня?
        if settings.last_notification_date == today.isoformat():
            return False

        # Пользователь уже занимался сегодня?
        user = await self.user_repo.get(user_id)
        if user and user.last_dialogue_date == today and user.dialogues_today > 0:
            # Отмечаем дату, чтобы не проверять повторно
            await self.reminder_repo.set_last_notification(user_id, today.isoformat())
            return False

        return True

    async def _get_notification_text(self, user_id: int, today: date) -> Optional[str]:
        """Определяет текст уведомления в зависимости от состояния streak.

        Returns:
            Текст сообщения, или None если отправлять не нужно.
        """
        if not await self._should_notify_today(user_id, today):
            return None

        user = await self.user_repo.get(user_id)
        if not user:
            return None

        streak = user.streak
        yesterday = today - timedelta(days=1)

        # Пользователь занимался вчера?
        studied_yesterday = (
            user.last_dialogue_date == yesterday and user.dialogues_today > 0
        )

        if not studied_yesterday:
            if streak >= 3:
                return STREAK_WARNING_TEXT.format(streak=streak)
            elif streak > 0:
                return STREAK_LOST_TEXT.format(streak=streak)

        return REMINDER_TEXT

    async def _send_reminder(self, user_id: int) -> None:
        """Отправляет напоминание одному пользователю."""
        try:
            text = await self._get_notification_text(user_id, self._today)
            if text is None:
                return

            await self.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=self.get_remind_keyboard(),
            )

            logger.info("Reminder sent to user %d", user_id)

            # Отмечаем дату отправки
            await self.reminder_repo.set_last_notification(
                user_id, self._today.isoformat()
            )
        except Exception as e:
            logger.warning("Failed to send reminder to user %d: %s", user_id, e)

    async def check_and_notify(self) -> None:
        """Проверяет время и отправляет напоминания всем, кому пора."""
        self._today = date.today()

        # Получаем всех включённых пользователей
        cursor = await self.reminder_repo.conn.execute(
            "SELECT * FROM reminder_settings WHERE enabled = 1"
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()

        sent_count = 0
        for row in rows:
            settings = self.reminder_repo._row_to_settings(row)
            if not settings:
                continue

            # Вычисляем локальное время пользователя
            try:
                tz = ZoneInfo(settings.timezone)
            except (KeyError, TypeError):
                tz = ZoneInfo("Europe/Moscow")

            local_now = datetime.now(tz)
            local_hhmm = local_now.strftime("%H:%M")

            if local_hhmm != settings.remind_time:
                continue

            await self._send_reminder(settings.user_id)
            sent_count += 1

        if sent_count > 0:
            logger.info(
                "Sent %d reminders at %s UTC",
                sent_count,
                datetime.now(timezone.utc).strftime("%H:%M"),
            )

    async def _run_loop(self) -> None:
        """Основной цикл проверки напоминаний."""
        logger.info(
            "Reminder service loop started (check interval: %ds)", CHECK_INTERVAL
        )
        while not self._stop_event.is_set():
            try:
                await self.check_and_notify()
            except Exception as e:
                logger.error("Reminder check error: %s", e, exc_info=True)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=CHECK_INTERVAL)
            except asyncio.TimeoutError:
                pass  # normal — continue loop

        logger.info("Reminder service loop stopped")

    def start(self) -> None:
        """Запускает фоновый цикл напоминаний."""
        if self._task is not None and not self._task.done():
            logger.warning("Reminder service already running")
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Reminder service started")

    async def stop(self) -> None:
        """Останавливает фоновый цикл."""
        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Reminder service stop timed out, cancelling")
            self._task.cancel()
        self._task = None
        logger.info("Reminder service stopped")


# ─── Утилиты ───────────────────────────────────────────────────────────


def parse_remind_time(text: str) -> Optional[str]:
    """Парсит время из текста в формате HH:MM.

    Поддерживает: "09:00", "9:00", "21:30", "9", "21".
    """
    text = text.strip()

    if ":" in text:
        parts = text.split(":")
        try:
            hour = int(parts[0])
            minute = int(parts[1])
        except (ValueError, IndexError):
            return None
    else:
        try:
            hour = int(text)
            minute = 0
        except ValueError:
            return None

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None

    return f"{hour:02d}:{minute:02d}"


# Часовые пояса РФ и популярные
POPULAR_TIMEZONES = [
    "Europe/Kaliningrad",
    "Europe/Moscow",
    "Europe/Samara",
    "Asia/Yekaterinburg",
    "Asia/Omsk",
    "Asia/Krasnoyarsk",
    "Asia/Irkutsk",
    "Asia/Yakutsk",
    "Asia/Vladivostok",
    "Asia/Kamchatka",
    "Europe/London",
    "Europe/Berlin",
    "Europe/Helsinki",
    "Asia/Almaty",
    "Asia/Tashkent",
]
