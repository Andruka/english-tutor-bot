"""Хендлеры для настройки ежедневных напоминаний (/remind).

Поддерживает:
- /remind — показать текущие настройки
- /remind on/off — включить/отключить напоминания
- /remind HH:MM — установить время напоминания
- /remind timezone <IANA> — установить часовой пояс
- Callback: remind_off, remind_on
"""

import logging

from aiogram import Router, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import Command

from bot.db import ReminderSettingsRepository, get_conn
from bot.services.reminder_service import parse_remind_time, POPULAR_TIMEZONES

router = Router()
logger = logging.getLogger(__name__)


# ─── Клавиатуры ────────────────────────────────────────────────────────


def settings_keyboard(
    enabled: bool, remind_time: str, timezone: str
) -> InlineKeyboardMarkup:
    """Клавиатура настроек напоминаний."""
    toggle_text = "🔕 Выключить" if enabled else "🔔 Включить"
    toggle_data = "remind_off" if enabled else "remind_on"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=toggle_text, callback_data=toggle_data)],
            [
                InlineKeyboardButton(
                    text="🕐 Сменить время", callback_data="remind_change_time"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🌍 Сменить часовой пояс",
                    callback_data="remind_change_tz",
                ),
            ],
        ]
    )


def timezone_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора часового пояса."""
    rows = []
    for i in range(0, len(POPULAR_TIMEZONES), 3):
        chunk = POPULAR_TIMEZONES[i : i + 3]
        rows.append(
            [
                InlineKeyboardButton(
                    text=tz.split("/")[-1], callback_data=f"remind_tz:{tz}"
                )
                for tz in chunk
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── /remind ───────────────────────────────────────────────────────────


@router.message(Command("remind"))
@router.message(F.text == "🔔 Напоминания")
async def cmd_remind(message: Message):
    """Показать текущие настройки напоминаний."""
    user_id = message.from_user.id
    conn = await get_conn()
    repo = ReminderSettingsRepository(conn)

    settings = await repo.ensure_user(user_id)

    status = "✅ Включены" if settings.enabled else "❌ Отключены"
    text = (
        f"🔔 <b>Напоминания</b>\n\n"
        f"Статус: {status}\n"
        f"Время: <code>{settings.remind_time}</code>\n"
        f"Часовой пояс: <code>{settings.timezone}</code>\n\n"
        f"<i>Бот будет напоминать о занятиях каждый день в указанное время.</i>"
    )

    await message.reply(
        text,
        reply_markup=settings_keyboard(
            settings.enabled, settings.remind_time, settings.timezone
        ),
    )


# ─── Команды быстрой настройки (текстовые) ─────────────────────────────


@router.message(Command("remind_on"))
async def cmd_remind_on(message: Message):
    """Включить напоминания."""
    user_id = message.from_user.id
    conn = await get_conn()
    repo = ReminderSettingsRepository(conn)

    await repo.ensure_user(user_id)
    await repo.set_enabled(user_id, True)

    await message.reply("✅ Напоминания включены!")


@router.message(Command("remind_off"))
async def cmd_remind_off(message: Message):
    """Отключить напоминания."""
    user_id = message.from_user.id
    conn = await get_conn()
    repo = ReminderSettingsRepository(conn)

    await repo.ensure_user(user_id)
    await repo.set_enabled(user_id, False)

    await message.reply("🔕 Напоминания отключены. Включить: /remind_on")


@router.message(Command("remind_time"))
async def cmd_remind_time(message: Message):
    """Установить время напоминания.

    Использование: /remind_time HH:MM
    """
    user_id = message.from_user.id
    args = message.text[len("/remind_time ") :].strip()

    if not args:
        await message.reply(
            "Укажите время: <code>/remind_time 09:00</code>\n"
            "Можно также: <code>/remind_time 9</code> (9:00)"
        )
        return

    parsed = parse_remind_time(args)
    if parsed is None:
        await message.reply(
            "❌ Неправильный формат времени. Используйте HH:MM, например <code>09:00</code>"
        )
        return

    conn = await get_conn()
    repo = ReminderSettingsRepository(conn)

    await repo.ensure_user(user_id)
    await repo.set_time(user_id, parsed)

    await message.reply(f"✅ Время напоминания установлено: <code>{parsed}</code>")


@router.message(Command("remind_tz"))
async def cmd_remind_tz(message: Message):
    """Установить часовой пояс.

    Использование: /remind_tz Europe/Moscow
    """
    user_id = message.from_user.id
    args = message.text[len("/remind_tz ") :].strip()

    if not args:
        tz_list = "\n".join(f"  <code>{tz}</code>" for tz in POPULAR_TIMEZONES)
        await message.reply(
            f"Укажите часовой пояс: <code>/remind_tz Europe/Moscow</code>\n\n"
            f"<b>Популярные:</b>\n{tz_list}"
        )
        return

    from zoneinfo import available_timezones

    available = available_timezones()
    if args not in available:
        await message.reply(f"❌ Часовой пояс <code>{args}</code> не найден.")
        return

    conn = await get_conn()
    repo = ReminderSettingsRepository(conn)

    await repo.ensure_user(user_id)
    await repo.conn.execute(
        "UPDATE reminder_settings SET timezone = ? WHERE user_id = ?",
        (args, user_id),
    )
    await repo.conn.commit()

    await message.reply(f"✅ Часовой пояс установлен: <code>{args}</code>")


# ─── Callback-обработчики ─────────────────────────────────────────────


@router.callback_query(F.data == "remind_on")
async def cb_remind_on(callback: CallbackQuery):
    """Включить напоминания (из инлайн-кнопки)."""
    user_id = callback.from_user.id
    conn = await get_conn()
    repo = ReminderSettingsRepository(conn)

    await repo.ensure_user(user_id)
    await repo.set_enabled(user_id, True)

    await callback.message.edit_reply_markup(
        reply_markup=settings_keyboard(True, "", "")
    )
    await callback.answer("✅ Напоминания включены")


@router.callback_query(F.data == "remind_off")
async def cb_remind_off(callback: CallbackQuery):
    """Отключить напоминания (из инлайн-кнопки)."""
    user_id = callback.from_user.id
    conn = await get_conn()
    repo = ReminderSettingsRepository(conn)

    await repo.set_enabled(user_id, False)

    await callback.message.edit_reply_markup(
        reply_markup=settings_keyboard(False, "", "")
    )
    await callback.answer("🔕 Напоминания отключены")


@router.callback_query(F.data == "remind_change_time")
async def cb_remind_change_time(callback: CallbackQuery):
    """Показать инструкцию по смене времени."""
    await callback.message.answer(
        "Установите время командой:\n"
        "<code>/remind_time 09:00</code> — в 9 утра\n"
        "<code>/remind_time 21:30</code> — в 21:30\n"
        "<code>/remind_time 9</code> — тоже 9:00"
    )
    await callback.answer()


@router.callback_query(F.data == "remind_change_tz")
async def cb_remind_change_tz(callback: CallbackQuery):
    """Показать выбор часового пояса."""
    await callback.message.answer(
        "Выберите часовой пояс:",
        reply_markup=timezone_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("remind_tz:"))
async def cb_remind_select_tz(callback: CallbackQuery):
    """Установить часовой пояс из инлайн-кнопки."""
    user_id = callback.from_user.id
    tz = callback.data[len("remind_tz:") :]

    from zoneinfo import available_timezones

    if tz not in available_timezones():
        await callback.answer("❌ Неизвестный часовой пояс", show_alert=True)
        return

    conn = await get_conn()
    repo = ReminderSettingsRepository(conn)

    await repo.ensure_user(user_id)
    await repo.conn.execute(
        "UPDATE reminder_settings SET timezone = ? WHERE user_id = ?",
        (tz, user_id),
    )
    await repo.conn.commit()

    await callback.message.edit_text(
        callback.message.text + f"\n\n✅ Часовой пояс: <code>{tz}</code>"
    )
    await callback.answer(f"✅ Часовой пояс установлен: {tz}")
