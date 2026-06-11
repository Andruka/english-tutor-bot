"""Ежедневный Telegram-дайджест прогресса.

Сервис не вызывает LLM: он собирает уже имеющиеся метрики из SQLite,
форматирует короткий HTML-safe текст и отправляет его в локальное digest_time
пользователя не чаще одного раза за локальный день.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from html import escape
from json import JSONDecodeError, loads
from typing import Optional
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.db import ReminderSettings, ReminderSettingsRepository, UserRepository
from bot.services.progress_service import ACHIEVEMENT_DEFINITIONS

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 60
TELEGRAM_MESSAGE_LIMIT = 4096
PROGRESS_TEST_PLACEHOLDER = (
    "скоро появится; пока считаем прогресс по диалогам, словам и streak"
)
DEFAULT_TIMEZONE = "Europe/Moscow"


@dataclass
class DailyDigestData:
    user_id: int
    local_date: date
    timezone: str
    dialogues_today: int
    total_dialogues: int
    avg_rating_today: float | None
    corrections_today: int
    words_added_today: int
    words_due: int
    words_mastered: int
    streak: int
    achievements_today: list[str]
    progress_test_status: str = PROGRESS_TEST_PLACEHOLDER


def safe_zoneinfo(timezone_name: str | None) -> ZoneInfo:
    """Возвращает валидный ZoneInfo, fallback — Europe/Moscow."""
    try:
        return ZoneInfo(timezone_name or DEFAULT_TIMEZONE)
    except (KeyError, TypeError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def local_day_bounds_utc(target_date: date, tz: ZoneInfo) -> tuple[str, str]:
    """Границы локального дня как UTC-naive строки для SQLite сравнения.

    В текущей схеме SQLite default timestamps выглядят как
    ``YYYY-MM-DD HH:MM:SS`` без timezone. Это UTC-время от SQLite, поэтому
    границы тоже приводятся к UTC и форматируются тем же образом.
    """
    start_local = datetime.combine(target_date, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return (
        start_utc.strftime("%Y-%m-%d %H:%M:%S"),
        end_utc.strftime("%Y-%m-%d %H:%M:%S"),
    )


async def collect_daily_digest(
    conn,
    user_id: int,
    tz: ZoneInfo | str,
    target_date: Optional[date] = None,
) -> DailyDigestData:
    """Собирает метрики дайджеста за локальный день пользователя."""
    zone = safe_zoneinfo(tz if isinstance(tz, str) else getattr(tz, "key", None))
    local_date = target_date or datetime.now(zone).date()
    start_utc, end_utc = local_day_bounds_utc(local_date, zone)

    user_repo = UserRepository(conn)
    user = await user_repo.get(user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")

    cursor = await conn.execute(
        "SELECT COUNT(*) FROM dialogues WHERE user_id = ?", (user_id,)
    )
    row = await cursor.fetchone()
    total_dialogues = row[0] if row else 0

    cursor = await conn.execute(
        """
        SELECT COUNT(*) AS cnt, AVG(NULLIF(rating, 0)) AS avg_rating
        FROM dialogues
        WHERE user_id = ? AND timestamp >= ? AND timestamp < ?
        """,
        (user_id, start_utc, end_utc),
    )
    row = await cursor.fetchone()
    local_dialogue_count = row[0] if row else 0
    avg_rating_today = row[1] if row and row[1] is not None else None

    cursor = await conn.execute(
        """
        SELECT corrections FROM dialogues
        WHERE user_id = ? AND timestamp >= ? AND timestamp < ?
        """,
        (user_id, start_utc, end_utc),
    )
    correction_rows = await cursor.fetchall()
    corrections_today = 0
    for correction_row in correction_rows:
        try:
            corrections = loads(correction_row[0] or "[]")
            if isinstance(corrections, list):
                corrections_today += len(corrections)
        except (JSONDecodeError, TypeError):
            logger.debug("Skipping invalid corrections JSON for user %s", user_id)

    cursor = await conn.execute(
        """
        SELECT COUNT(*) FROM dictionary
        WHERE user_id = ? AND created_at >= ? AND created_at < ?
        """,
        (user_id, start_utc, end_utc),
    )
    row = await cursor.fetchone()
    words_added_today = row[0] if row else 0

    now_utc = (
        datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    )
    cursor = await conn.execute(
        """
        SELECT COUNT(*) FROM dictionary
        WHERE user_id = ? AND (next_review IS NULL OR next_review <= ?)
        """,
        (user_id, now_utc),
    )
    row = await cursor.fetchone()
    words_due = row[0] if row else 0

    cursor = await conn.execute(
        "SELECT COUNT(*) FROM dictionary WHERE user_id = ? AND level = 'mastered'",
        (user_id,),
    )
    row = await cursor.fetchone()
    words_mastered = row[0] if row else 0

    cursor = await conn.execute(
        """
        SELECT achievement_id FROM achievements
        WHERE user_id = ? AND earned_at = ?
        ORDER BY earned_at, achievement_id
        """,
        (user_id, local_date.isoformat()),
    )
    achievement_rows = await cursor.fetchall()
    achievements_today = [
        ACHIEVEMENT_DEFINITIONS.get(row[0], {}).get("name", row[0])
        for row in achievement_rows
    ]

    # users.dialogues_today остаётся источником по плану, но локальный COUNT
    # страхует тесты и будущие записи, если счётчик ещё не обновлён.
    dialogues_today = max(user.dialogues_today or 0, local_dialogue_count)

    return DailyDigestData(
        user_id=user_id,
        local_date=local_date,
        timezone=zone.key,
        dialogues_today=dialogues_today,
        total_dialogues=total_dialogues,
        avg_rating_today=avg_rating_today,
        corrections_today=corrections_today,
        words_added_today=words_added_today,
        words_due=words_due,
        words_mastered=words_mastered,
        streak=user.streak or 0,
        achievements_today=achievements_today,
    )


def format_daily_digest(data: DailyDigestData) -> str:
    """Форматирует HTML-safe текст дайджеста для Telegram."""
    if data.dialogues_today == 0:
        dialogue_line = (
            "Сегодня практики не было — можно сделать короткий 5-минутный урок сейчас."
        )
    else:
        details = [f"всего диалогов: {data.total_dialogues}"]
        if data.avg_rating_today is not None and data.avg_rating_today > 0:
            details.append(f"средняя оценка: {data.avg_rating_today:.1f}/10")
        if data.corrections_today > 0:
            details.append(f"исправлений: {data.corrections_today}")
        dialogue_line = "Хорошая работа — " + ", ".join(details) + "."

    if data.streak == 0:
        streak_label = "дней"
        streak_line = "Начни серию сегодня — один короткий урок уже считается."
    elif data.streak == 1:
        streak_label = "день"
        streak_line = "Серия началась — закрепи её завтра."
    else:
        streak_label = (
            "дня"
            if 2 <= data.streak % 10 <= 4 and data.streak % 100 not in (12, 13, 14)
            else "дней"
        )
        streak_line = "Продолжай серию — стабильность важнее длины урока."

    if data.achievements_today:
        shown = [escape(name) for name in data.achievements_today[:3]]
        achievements = "\n".join(f"• {name}" for name in shown)
        if len(data.achievements_today) > 3:
            achievements += f"\n• ещё {len(data.achievements_today) - 3}"
    else:
        achievements = "нет новых — следующие уже близко"

    if data.words_due > 0:
        cta_line = f"Повтори {data.words_due} слов: /dictionary"
    elif data.dialogues_today == 0:
        cta_line = "Начать урок: просто отправь сообщение боту"
    else:
        cta_line = "Завтра продолжим: один короткий диалог сохранит темп."

    text = (
        "📊 <b>Твой прогресс за сегодня</b>\n\n"
        f"💬 <b>Диалоги:</b> {data.dialogues_today}\n"
        f"{escape(dialogue_line)}\n\n"
        "📚 <b>Слова:</b>\n"
        f"• Новых сегодня: {data.words_added_today}\n"
        f"• Ждут повторения: {data.words_due}\n"
        f"• Освоено всего: {data.words_mastered}\n\n"
        f"🔥 <b>Streak:</b> {data.streak} {streak_label}\n"
        f"{escape(streak_line)}\n\n"
        f"🏆 <b>Достижения сегодня:</b> {achievements}\n\n"
        f"🧪 <b>Тест прогресса:</b> {escape(data.progress_test_status)}\n\n"
        f"{escape(cta_line)}"
    )
    return text[:TELEGRAM_MESSAGE_LIMIT]


class DailyDigestSender:
    """Фоновая отправка дайджестов по локальному digest_time."""

    def __init__(
        self,
        bot: Bot,
        reminder_repo: ReminderSettingsRepository,
        user_repo: UserRepository,
    ):
        self.bot = bot
        self.reminder_repo = reminder_repo
        self.user_repo = user_repo
        self._task = None
        self._stop_event = None

    @staticmethod
    def get_digest_keyboard(words_due: int = 0) -> InlineKeyboardMarkup:
        rows = [
            [InlineKeyboardButton(text="🎯 Начать урок", callback_data="start_dialog")]
        ]
        if words_due > 0:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="📚 Повторить слова", callback_data="dictionary_review"
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔕 Отключить дайджест", callback_data="digest_off"
                )
            ]
        )
        return InlineKeyboardMarkup(inline_keyboard=rows)

    @staticmethod
    def _local_now(settings: ReminderSettings, now: datetime | None = None) -> datetime:
        tz = safe_zoneinfo(settings.timezone)
        if now is None:
            return datetime.now(tz)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(tz)

    @staticmethod
    def _is_due(settings: ReminderSettings, local_now: datetime) -> bool:
        if not settings.digest_enabled:
            return False
        local_date = local_now.date().isoformat()
        if settings.last_digest_date == local_date:
            return False
        try:
            hour, minute = [int(part) for part in settings.digest_time.split(":", 1)]
            digest_time = time(hour=hour, minute=minute)
        except (ValueError, TypeError):
            digest_time = time(hour=21, minute=0)
        return local_now.time().replace(second=0, microsecond=0) >= digest_time

    async def _send_digest(self, settings: ReminderSettings, local_date: date) -> None:
        data = await collect_daily_digest(
            self.reminder_repo.conn,
            user_id=settings.user_id,
            tz=settings.timezone,
            target_date=local_date,
        )
        await self.bot.send_message(
            chat_id=settings.user_id,
            text=format_daily_digest(data),
            reply_markup=self.get_digest_keyboard(data.words_due),
        )
        await self.reminder_repo.set_last_digest(
            settings.user_id, local_date.isoformat()
        )
        logger.info("Daily digest sent to user %d", settings.user_id)

    async def check_and_send_digests(self, now: datetime | None = None) -> int:
        """Проверяет настройки и отправляет due-дайджесты. Возвращает sent_count."""
        settings_list = await self.reminder_repo.get_all_digest_enabled()
        sent_count = 0
        for settings in settings_list:
            local_now = self._local_now(settings, now)
            if not self._is_due(settings, local_now):
                continue
            try:
                await self._send_digest(settings, local_now.date())
                sent_count += 1
            except Exception as exc:  # noqa: BLE001 — изолируем сбой одного пользователя
                logger.warning(
                    "Failed to send daily digest to user %d: %s",
                    settings.user_id,
                    exc,
                    exc_info=True,
                )
        return sent_count

    async def _run_loop(self) -> None:
        import asyncio

        logger.info("Daily digest loop started (check interval: %ds)", CHECK_INTERVAL)
        while not self._stop_event.is_set():
            try:
                await self.check_and_send_digests()
            except Exception as exc:  # noqa: BLE001
                logger.error("Daily digest check error: %s", exc, exc_info=True)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=CHECK_INTERVAL)
            except asyncio.TimeoutError:
                pass
        logger.info("Daily digest loop stopped")

    def start(self) -> None:
        import asyncio

        if self._task is not None and not self._task.done():
            logger.warning("Daily digest service already running")
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Daily digest service started")

    async def stop(self) -> None:
        import asyncio

        if self._task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Daily digest service stop timed out, cancelling")
            self._task.cancel()
        self._task = None
        logger.info("Daily digest service stopped")
