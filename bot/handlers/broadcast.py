"""Админская команда контролируемой рассылки."""

from __future__ import annotations

import os

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.admin_api import parse_admin_user_ids
from bot.db import get_conn
from bot.services.broadcast_service import BroadcastService, parse_broadcast_target

router = Router()

DEFAULT_MESSAGES_PER_SECOND = 1.0


def _is_admin(message: Message) -> bool:
    return bool(
        message.from_user
        and message.from_user.id
        in parse_admin_user_ids(os.getenv("ADMIN_USER_IDS", ""))
    )


def parse_broadcast_command(text: str) -> tuple[bool, str, str]:
    """Parse /broadcast [--confirm] <target> <message text>."""
    parts = (text or "").split(maxsplit=3)
    if not parts or not parts[0].startswith("/broadcast"):
        raise ValueError("invalid command")

    confirmed = False
    if len(parts) >= 2 and parts[1] == "--confirm":
        confirmed = True
        if len(parts) < 4:
            raise ValueError("usage")
        target = parts[2]
        body = parts[3].strip()
    else:
        if len(parts) < 3:
            raise ValueError("usage")
        target = parts[1]
        body = (
            parts[2].strip() if len(parts) == 3 else parts[2] + " " + parts[3].strip()
        )

    if not body:
        raise ValueError("empty_message")
    parse_broadcast_target(target)  # validate target for clearer command errors
    return confirmed, target, body


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, bot: Bot) -> None:
    """Preview or execute an admin broadcast.

    Syntax:
      /broadcast all <text>
      /broadcast level:A1 <text>
      /broadcast subscription:true <text>
      /broadcast user:123,456 <text>

    The first command only previews. Repeat with --confirm to send.
    """
    if not _is_admin(message):
        await message.answer("⛔ Нет доступа к рассылке.")
        return

    try:
        confirmed, raw_target, body = parse_broadcast_command(message.text or "")
        target = parse_broadcast_target(raw_target)
    except ValueError:
        await message.answer(
            "Использование:\n"
            "/broadcast all <текст>\n"
            "/broadcast level:A1 <текст>\n"
            "/broadcast subscription:true <текст>\n"
            "/broadcast user:123,456 <текст>\n\n"
            "Для отправки повтори команду с --confirm после /broadcast."
        )
        return

    conn = await get_conn()
    service = BroadcastService(bot=bot, conn=conn)
    user_ids = await service.resolve_user_ids(target)

    if not confirmed:
        preview = body if len(body) <= 500 else body[:497] + "..."
        await message.answer(
            "⚠️ Подтверждение рассылки\n\n"
            f"Цель: {raw_target}\n"
            f"Получателей: {len(user_ids)}\n"
            f"Текст:\n{preview}\n\n"
            f"Чтобы отправить, выполни:\n/broadcast --confirm {raw_target} {body}"
        )
        return

    if not user_ids:
        await message.answer("Рассылка отменена: по выбранной цели нет получателей.")
        return

    result = await service.send(
        target=target,
        text=body,
        messages_per_second=DEFAULT_MESSAGES_PER_SECOND,
    )
    await message.answer(
        "✅ Готово: рассылка завершена.\n"
        f"Доставлено: {result.sent}/{result.total}\n"
        f"Ошибок: {result.failed}"
    )
