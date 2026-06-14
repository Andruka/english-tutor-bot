"""Subscription Service — планы, проверки, автоматическое отзыв."""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Цены в рублях (копейках для Telegram Payments)
SUBSCRIPTION_PLANS = {
    "monthly": {
        "name": "Premium Месячная",
        "tier": "premium",
        "price_rub": 199,
        "price_kopecks": 19900,
        "duration_days": 30,
    },
    "yearly": {
        "name": "Premium Годовая",
        "tier": "premium",
        "price_rub": 1490,
        "price_kopecks": 149000,
        "duration_days": 365,
    },
    "pro_monthly": {
        "name": "Pro Месячная",
        "tier": "pro",
        "price_rub": 499,
        "price_kopecks": 49900,
        "duration_days": 30,
    },
    "pro_yearly": {
        "name": "Pro Годовая",
        "tier": "pro",
        "price_rub": 3990,
        "price_kopecks": 399000,
        "duration_days": 365,
    },
}

# Токен провайдера ЮKassa — получается в BotFather
# В .env: YOOKASSA_PROVIDER_TOKEN=...
PROVIDER_TOKEN: Optional[str] = None

TRIAL_DURATION_DAYS = 3


def set_provider_token(token: str):
    """Устанавливает provider_token для ЮKassa."""
    global PROVIDER_TOKEN
    PROVIDER_TOKEN = token


async def get_user_subscription_status(user, repo) -> dict:
    """Проверяет статус подписки и автоматически отзывает истёкшие."""
    if not user.subscription and not user.subscription_expiry:
        return {"active": False, "days_left": 0, "tier": "basic"}

    if user.subscription_expiry:
        try:
            expiry = datetime.fromisoformat(user.subscription_expiry)
            now = datetime.now(timezone.utc)
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            days_left = (expiry - now).days
        except (ValueError, TypeError):
            return {"active": False, "days_left": 0, "tier": "basic"}

        if days_left <= 0:
            await repo.set_subscription(user.user_id, False, user.subscription_expiry)
            return {"active": False, "days_left": 0, "tier": "basic"}

        tier = user.subscription_tier if hasattr(user, 'subscription_tier') else "premium"
        return {"active": user.subscription, "days_left": days_left, "tier": tier}

    return {"active": False, "days_left": 0, "tier": "basic"}


async def check_and_update_subscription(user_id: int, repo) -> bool:
    """Проверяет и обновляет статус подписки. Возвращает active."""
    user = await repo.get(user_id)
    if user is None:
        return False
    status = await get_user_subscription_status(user, repo)
    return status["active"]


async def activate_trial(user_id: int, repo) -> bool:
    """Активирует 3-дневный триал Premium.

    Возвращает True, если триал активирован.
    Если триал уже был использован — возвращает False.
    """
    user = await repo.get(user_id)
    if user is None:
        return False
    if user.trial_taken:
        return False
    await repo.set_trial(user_id)
    logger.info("Trial activated for user %d (3 days)", user_id)
    return True


async def has_active_trial(user, repo) -> bool:
    """Проверяет, активен ли у пользователя триал Premium.

    Триал активен, если trial_taken=True, subscription=True и срок не истёк.
    """
    if not user.trial_taken:
        return False
    status = await get_user_subscription_status(user, repo)
    return status["active"]


async def has_pro_features(user) -> bool:
    """Проверяет, имеет ли пользователь доступ к Pro-фичам.

    Pro-функции:
    - Приоритетная AI-модель (более качественные ответы)
    - Детальный анализ произношения
    - Расширенная статистика
    """
    if not user.subscription:
        return False
    tier = user.subscription_tier if hasattr(user, 'subscription_tier') else "basic"
    return tier == "pro"


async def create_invoice_link(plan_id: str, user_id: int) -> str:
    """Генерирует ссылку на оплату через ЮKassa.

    При реальной интеграции создаётся Invoice через Bot API.
    Сейчас возвращаем заглушку.
    """
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if plan is None:
        raise ValueError(f"Unknown plan: {plan_id}")
    return f"yookassa://invoice/{user_id}/{plan_id}/{plan['price_kopecks']}"
