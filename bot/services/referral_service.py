"""Referral Service — генерация ссылок, начисление наград."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

REFERRAL_REWARD_REFERER_DAYS = 7   # реферер получает 7 дней Premium
REFERRAL_REWARD_REFERRED_DAYS = 3  # реферал получает 3 дня Premium

BOT_USERNAME = "ai_your_english_tutor_bot"


def generate_referral_link(user_id: int) -> str:
    """Генерирует реферальную ссылку вида https://t.me/bot?start=ref_<id>."""
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"


def parse_referral(start_data: str) -> Optional[int]:
    """Извлекает user_id реферера из start_data вида 'ref_<id>'.

    Возвращает user_id реферера или None, если формат не подходит.
    """
    if not start_data or not start_data.startswith("ref_"):
        return None
    try:
        return int(start_data[4:])
    except (ValueError, IndexError):
        return None


async def award_referral_bonus(
    user_repo, reward_repo, referred_user_id: int, referrer_id: int
) -> dict:
    """Начисляет бонусы рефереру и рефералу.

    Returns:
        dict с полями referrer_days, referred_days, referrer_reward_id, referred_reward_id
    """
    # Награда рефереру (7 дней Premium)
    referrer_expiry = (
        datetime.now(timezone.utc) + timedelta(days=REFERRAL_REWARD_REFERER_DAYS)
    ).isoformat()
    referrer_reward = await reward_repo.add_reward(
        user_id=referrer_id,
        referred_user_id=referred_user_id,
        reward_value=REFERRAL_REWARD_REFERER_DAYS,
    )

    # Награда рефералу (3 дня Premium)
    referred_expiry = (
        datetime.now(timezone.utc) + timedelta(days=REFERRAL_REWARD_REFERRED_DAYS)
    ).isoformat()
    referred_reward = await reward_repo.add_reward(
        user_id=referred_user_id,
        referred_user_id=referred_user_id,
        reward_value=REFERRAL_REWARD_REFERRED_DAYS,
    )

    # Начисляем подписку рефереру (суммируем с текущей)
    referrer = await user_repo.get(referrer_id)
    if referrer and referrer.subscription and referrer.subscription_expiry:
        try:
            current = datetime.fromisoformat(referrer.subscription_expiry)
            new_expiry = current + timedelta(days=REFERRAL_REWARD_REFERER_DAYS)
        except (ValueError, TypeError):
            new_expiry = datetime.now(timezone.utc) + timedelta(days=REFERRAL_REWARD_REFERER_DAYS)
    else:
        new_expiry = datetime.now(timezone.utc) + timedelta(days=REFERRAL_REWARD_REFERER_DAYS)

    await user_repo.set_subscription(
        referrer_id,
        active=True,
        expiry=new_expiry.isoformat(),
        tier="premium",
    )

    # Начисляем подписку рефералу
    await user_repo.set_subscription(
        referred_user_id,
        active=True,
        expiry=referred_expiry,
        tier="premium",
    )

    await reward_repo.mark_claimed(referrer_reward.id)
    await reward_repo.mark_claimed(referred_reward.id)

    return {
        "referrer_id": referrer_id,
        "referred_id": referred_user_id,
        "referrer_days": REFERRAL_REWARD_REFERER_DAYS,
        "referred_days": REFERRAL_REWARD_REFERRED_DAYS,
        "referrer_reward_id": referrer_reward.id,
        "referred_reward_id": referred_reward.id,
    }