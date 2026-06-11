"""Cron-проверка истекающих подписок — фоновый asyncio-цикл.

Запускается внутри бота как create_task и каждые N минут проверяет,
не истекли ли подписки. Истёкшие отзывает (subscription=0) и
опционально уведомляет пользователя.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Bot

from bot.db import UserRepository, get_conn

logger = logging.getLogger(__name__)

# Интервал проверки по умолчанию (секунды)
DEFAULT_CHECK_INTERVAL = 3600  # 1 час
# Минимальный интервал (для тестов)
MIN_CHECK_INTERVAL = 10


async def find_expired_subscriptions() -> list[dict]:
    """Находит всех пользователей с истёкшей подпиской.

    Возвращает список словарей: {user_id, username, subscription_expiry}.
    """
    conn = await get_conn()
    expired_list = []

    try:
        cursor = await conn.execute(
            """SELECT user_id, username, subscription_expiry
               FROM users
               WHERE subscription = 1
                 AND subscription_expiry IS NOT NULL
                 AND subscription_expiry <= ?""",
            (datetime.now(timezone.utc).isoformat(),),
        )
        rows = await cursor.fetchall()
        for row in rows:
            expired_list.append(
                {
                    "user_id": row["user_id"],
                    "username": row["username"] or "",
                    "subscription_expiry": row["subscription_expiry"],
                }
            )
    except Exception as e:
        logger.error("Failed to query expired subscriptions: %s", e)
    finally:
        await conn.close()

    return expired_list


async def find_almost_expired_subscriptions(
    hours_left: int = 24,
) -> list[dict]:
    """Находит пользователей, у которых подписка истекает через <hours_left> часов.

    Для отправки предупреждений.
    """
    conn = await get_conn()
    try:
        warning_threshold = (
            datetime.now(timezone.utc) + timedelta(hours=hours_left)
        ).isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()

        cursor = await conn.execute(
            """SELECT user_id, username, subscription_expiry
               FROM users
               WHERE subscription = 1
                 AND subscription_expiry IS NOT NULL
                 AND subscription_expiry > ?
                 AND subscription_expiry <= ?""",
            (now_iso, warning_threshold),
        )
        rows = await cursor.fetchall()
        return [
            {
                "user_id": row["user_id"],
                "username": row["username"] or "",
                "subscription_expiry": row["subscription_expiry"],
            }
            for row in rows
        ]
    except Exception as e:
        logger.error("Failed to query almost-expired subscriptions: %s", e)
        return []
    finally:
        await conn.close()


async def revoke_subscription(user_id: int, expiry: Optional[str] = None) -> bool:
    """Отзывает подписку пользователя (subscription=0).

    Args:
        user_id: ID пользователя.
        expiry: Старое значение subscription_expiry (сохраняется как есть).

    Returns:
        True если подписка была активна и отозвана.
    """
    conn = await get_conn()
    repo = UserRepository(conn)
    try:
        user = await repo.get(user_id)
        if user is None or not user.subscription:
            return False

        await repo.set_subscription(user_id, False, expiry or user.subscription_expiry)
        logger.info(
            "Subscription revoked for user %d (expired: %s)",
            user_id,
            expiry or user.subscription_expiry,
        )
        return True
    except Exception as e:
        logger.error("Failed to revoke subscription for user %d: %s", user_id, e)
        return False
    finally:
        await conn.close()


async def revoke_all_expired() -> list[dict]:
    """Находит и отзывает все истёкшие подписки.

    Returns:
        Список отозванных записей {user_id, username} для уведомлений.
    """
    expired = await find_expired_subscriptions()
    revoked = []
    for entry in expired:
        ok = await revoke_subscription(
            entry["user_id"], entry.get("subscription_expiry")
        )
        if ok:
            revoked.append({"user_id": entry["user_id"], "username": entry["username"]})

    if revoked:
        logger.info("Revoked %d expired subscription(s)", len(revoked))
    return revoked


async def notify_user_expired(bot: Bot, user_id: int, username: str = "") -> bool:
    """Уведомляет пользователя об истечении подписки."""
    try:
        await bot.send_message(
            user_id,
            "⏳ <b>Подписка истекла</b>\n\n"
            "Твой доступ к AI-репетитору без лимитов закончился. "
            "Чтобы продолжить пользоваться без ограничений, "
            "оформи новую подписку:\n"
            "  /subscribe\n\n"
            "Бесплатный лимит (5 диалогов/день) снова активен. "
            "Продолжай заниматься! 📚",
        )
        logger.info("Notified user %d about expired subscription", user_id)
        return True
    except Exception as e:
        logger.warning("Failed to notify user %d about expiry: %s", user_id, e)
        return False


async def notify_users_expired(bot: Bot, user_ids: list[dict]) -> int:
    """Уведомляет список пользователей об истечении подписки.

    Args:
        bot: Экземпляр Bot.
        user_ids: Список {user_id, username}.

    Returns:
        Количество успешных уведомлений.
    """
    count = 0
    for entry in user_ids:
        if await notify_user_expired(bot, entry["user_id"], entry.get("username", "")):
            count += 1
    return count


async def check_once_and_notify(
    bot: Optional[Bot] = None,
    notify: bool = True,
) -> int:
    """Одна итерация: найти и отозвать истёкшие, опционально уведомить.

    Args:
        bot: Экземпляр Bot для уведомлений. Если None — без уведомлений.
        notify: Отправлять уведомления.

    Returns:
        Количество отозванных подписок.
    """
    revoked = await revoke_all_expired()
    if notify and bot and revoked:
        sent = await notify_users_expired(bot, revoked)
        logger.info("Sent %d/%d expiry notifications", sent, len(revoked))
    return len(revoked)


async def subscription_checker_loop(
    bot: Optional[Bot] = None,
    interval: int = DEFAULT_CHECK_INTERVAL,
    notify: bool = True,
):
    """Фоновая asyncio-задача: проверяет и отзывает истёкшие подписки.

    Запускается через asyncio.create_task().

    Args:
        bot: Экземпляр Bot для уведомлений. Если None — без уведомлений.
        interval: Интервал проверки в секундах.
        notify: Отправлять ли уведомления пользователям при отзыве.
    """
    if interval < MIN_CHECK_INTERVAL:
        interval = MIN_CHECK_INTERVAL

    logger.info(
        "Subscription checker started (interval=%ds, notify=%s)", interval, notify
    )

    while True:
        try:
            await asyncio.sleep(interval)
            count = await check_once_and_notify(bot=bot, notify=notify)
            if count:
                logger.info("Subscription check: revoked %d subscription(s)", count)
        except asyncio.CancelledError:
            logger.info("Subscription checker cancelled")
            break
        except Exception as e:
            logger.error("Subscription checker error: %s", e)


def start_subscription_checker(
    bot: Optional[Bot] = None,
    interval: int = DEFAULT_CHECK_INTERVAL,
    notify: bool = True,
) -> asyncio.Task:
    """Запускает фоновую проверку подписок.

    Вызывается из main.py.

    Args:
        bot: Экземпляр Bot для уведомлений.
        interval: Интервал проверки (сек).
        notify: Отправлять уведомления при отзыве.

    Returns:
        asyncio.Task — сохранить для graceful shutdown.
    """
    return asyncio.create_task(
        subscription_checker_loop(bot=bot, interval=interval, notify=notify)
    )
