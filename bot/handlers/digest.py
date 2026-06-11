"""Хендлер команд управления ежедневным дайджестом (K009).

Паттерн повторяет reminder.py:
- /digest — показать настройки + клавиатура
- /digest_on — включить
- /digest_off — отключить
- /digest_time HH:MM — установить время
- Инлайн-кнопки для быстрого управления
"""

import logging

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db import get_conn, ReminderSettingsRepository
from bot.services.daily_digest_service import (
    collect_daily_digest,
    format_daily_digest,
)
from bot.services.reminder_service import parse_remind_time

logger = logging.getLogger(__name__)
router = Router(name="digest")


# ─── Клавиатура настроек ────────────────────────────────────────────


def digests_settings_keyboard(enabled: bool, digest_time: str) -> InlineKeyboardBuilder:
    """Клавиатура для настройки дайджеста."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Отправить сейчас", callback_data="digest_send_now")
    if enabled:
        kb.button(text="🔕 Отключить", callback_data="digest_off")
    else:
        kb.button(text="🔔 Включить", callback_data="digest_on")
    kb.button(text=f"⏰ Время: {digest_time}", callback_data="digest_change_time")
    kb.adjust(1, 1, 1)
    return kb.as_markup()


# ─── /digest ────────────────────────────────────────────────────────


@router.message(Command("digest"))
async def cmd_digest(message: Message):
    """Показывает настройки дайджеста."""
    user_id = message.from_user.id
    conn = await get_conn()
    try:
        repo = ReminderSettingsRepository(conn)
        await repo.ensure_user(user_id)
        settings = await repo.get(user_id)

        status = (
            "✅ Включён" if (settings and settings.digest_enabled) else "❌ Отключён"
        )
        digest_time = settings.digest_time if settings else "21:00"

        text = (
            f"📊 <b>Ежедневный дайджест</b>\n\n"
            f"Статус: {status}\n"
            f"⏰ Время: {digest_time}\n\n"
            f"📋 Дайджест показывает твой прогресс за день: "
            f"диалоги, новые слова, streak и рекомендации."
        )

        markup = digests_settings_keyboard(
            enabled=(settings and settings.digest_enabled),
            digest_time=digest_time,
        )
        await message.reply(text, reply_markup=markup)
    finally:
        await conn.close()


# ─── /digest_on ─────────────────────────────────────────────────────


@router.message(Command("digest_on"))
async def cmd_digest_on(message: Message):
    """Включает ежедневный дайджест."""
    user_id = message.from_user.id
    conn = await get_conn()
    try:
        repo = ReminderSettingsRepository(conn)
        await repo.ensure_user(user_id)
        await repo.set_digest_enabled(user_id, True)
        await message.reply(
            "✅ Дайджест включён! Ты будешь получать статистику прогресса ежедневно."
        )
    finally:
        await conn.close()


# ─── /digest_off ────────────────────────────────────────────────────


@router.message(Command("digest_off"))
async def cmd_digest_off(message: Message):
    """Отключает ежедневный дайджест."""
    user_id = message.from_user.id
    conn = await get_conn()
    try:
        repo = ReminderSettingsRepository(conn)
        await repo.ensure_user(user_id)
        await repo.set_digest_enabled(user_id, False)
        await message.reply(
            "🔕 Дайджест отключён. Чтобы включить снова — используй /digest_on."
        )
    finally:
        await conn.close()


# ─── /digest_time HH:MM ─────────────────────────────────────────────


@router.message(Command("digest_time"))
async def cmd_digest_time(message: Message, command: CommandObject):
    """Устанавливает время дайджеста HH:MM."""
    user_id = message.from_user.id
    args = command.args

    if not args:
        await message.reply(
            "⏰ Укажите время в формате HH:MM.\n"
            "Например: <code>/digest_time 21:00</code>"
        )
        return

    parsed = parse_remind_time(args)
    if parsed is None:
        await message.reply(
            "❌ Неправильный формат. Используй <code>HH:MM</code> "
            "(например, <code>/digest_time 21:00</code>)"
        )
        return

    conn = await get_conn()
    try:
        repo = ReminderSettingsRepository(conn)
        await repo.ensure_user(user_id)
        await repo.set_digest_time(user_id, parsed)
        await message.reply(f"✅ Время дайджеста установлено: <b>{parsed}</b>")
    finally:
        await conn.close()


# ─── Callback-обработчики ───────────────────────────────────────────


@router.callback_query(F.data == "digest_on")
async def cb_digest_on(callback: CallbackQuery):
    """Инлайн-кнопка включения дайджеста."""
    user_id = callback.from_user.id
    conn = await get_conn()
    try:
        repo = ReminderSettingsRepository(conn)
        await repo.ensure_user(user_id)
        await repo.set_digest_enabled(user_id, True)
        settings = await repo.get(user_id)

        await callback.answer("✅ Дайджест включён")
        await callback.message.edit_reply_markup(
            reply_markup=digests_settings_keyboard(
                enabled=True,
                digest_time=settings.digest_time,
            )
        )
    finally:
        await conn.close()


@router.callback_query(F.data == "digest_off")
async def cb_digest_off(callback: CallbackQuery):
    """Инлайн-кнопка отключения дайджеста."""
    user_id = callback.from_user.id
    conn = await get_conn()
    try:
        repo = ReminderSettingsRepository(conn)
        await repo.ensure_user(user_id)
        await repo.set_digest_enabled(user_id, False)
        settings = await repo.get(user_id)

        await callback.answer("🔕 Дайджест отключён")
        await callback.message.edit_reply_markup(
            reply_markup=digests_settings_keyboard(
                enabled=False,
                digest_time=settings.digest_time,
            )
        )
    finally:
        await conn.close()


@router.callback_query(F.data == "digest_change_time")
async def cb_digest_change_time(callback: CallbackQuery):
    """Инлайн-кнопка смены времени."""
    await callback.message.answer(
        "⏰ Укажите новое время командой /digest_time HH:MM\n"
        "Например: /digest_time 21:00"
    )
    await callback.answer()


@router.callback_query(F.data == "digest_send_now")
async def cb_digest_send_now(callback: CallbackQuery):
    """Инлайн-кнопка принудительной отправки дайджеста сейчас."""
    user_id = callback.from_user.id
    conn = await get_conn()
    try:
        repo = ReminderSettingsRepository(conn)
        settings = await repo.get(user_id)
        tz = settings.timezone if settings else "Europe/Moscow"

        data = await collect_daily_digest(conn, user_id, tz)
        text = format_daily_digest(data)

        await callback.message.answer(text, parse_mode="HTML")
        await callback.answer("📊 Вот твой прогресс!")
    finally:
        await conn.close()
