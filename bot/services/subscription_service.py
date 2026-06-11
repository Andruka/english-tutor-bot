"""Subscription Service — планы, проверки, автоматическое отзыв."""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Цены в рублях (копейках для Telegram Payments)
SUBSCRIPTION_PLANS = {
    "monthly": {
        "name": "Месячная",
        "price_rub": 199,
        "price_kopecks": 19900,
        "duration_days": 30,
    },
    "yearly": {
        "name": "Годовая",
        "price_rub": 1490,
        "price_kopecks": 149000,
        "duration_days": 365,
    },
}

# Токен провайдера ЮKassa — получается в BotFather
# В .env: YOOKASSA_PROVIDER_TOKEN=...
PROVIDER_TOKEN: Optional[str] = None


def set_provider_token(token: str):
    """Устанавливает provider_token для ЮKassa."""
    global PROVIDER_TOKEN
    PROVIDER_TOKEN = token


async def get_user_subscription_status(user, repo) -> dict:
    """Проверяет статус подписки и автоматически отзывает истёкшие."""
    if not user.subscription and not user.subscription_expiry:
        return {"active": False, "days_left": 0}

    if user.subscription_expiry:
        try:
            expiry = datetime.fromisoformat(user.subscription_expiry)
            now = datetime.now(timezone.utc)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            days_left = (expiry - now).days
        except (ValueError, TypeError):
            return {"active": False, "days_left": 0}

        if days_left <= 0:
            await repo.set_subscription(user.user_id, False, user.subscription_expiry)
            return {"active": False, "days_left": 0}

        return {"active": user.subscription, "days_left": days_left}

    return {"active": False, "days_left": 0}


async def check_and_update_subscription(user_id: int, repo) -> bool:
    """Проверяет и обновляет статус подписки. Возвращает active."""
    user = await repo.get(user_id)
    if user is None:
        return False
    status = await get_user_subscription_status(user, repo)
    return status["active"]


async def create_invoice_link(plan_id: str, user_id: int) -> str:
    """Генерирует ссылку на оплату через ЮKassa.

    При реальной интеграции создаётся Invoice через Bot API.
    Сейчас возвращаем заглушку.
    """
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if plan is None:
        raise ValueError(f"Unknown plan: {plan_id}")
    return f"yookassa://invoice/{user_id}/{plan_id}/{plan['price_kopecks']}"
