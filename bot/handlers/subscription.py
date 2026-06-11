"""Хендлер подписки — /subscribe, pre_checkout_query, successful_payment."""

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router, F
from aiogram.types import Message, PreCheckoutQuery, LabeledPrice
from aiogram.filters import Command

from bot.db import UserRepository, get_conn
from bot.services.subscription_service import (
    SUBSCRIPTION_PLANS,
    PROVIDER_TOKEN,
    get_user_subscription_status,
)

logger = logging.getLogger(__name__)

router = Router()

# provider_token для ЮKassa (устанавливается при старте бота)
# В main.py: set_provider_token(os.getenv("YOOKASSA_PROVIDER_TOKEN", ""))


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    """Показывает список тарифов."""
    lines = ["<b>💎 Доступные тарифы:</b>\n"]

    for plan_id, plan in SUBSCRIPTION_PLANS.items():
        lines.append(
            f"<b>{plan['name']}</b> — {plan['price_rub']}₽\n"
            f"  {plan['duration_days']} дней доступа\n"
            f"  /pay_{plan_id} — оформить\n"
        )

    lines.append("\nОплата через ЮKassa — карты РФ, СБП, ЮMoney")
    lines.append("Напиши /pay_monthly или /pay_yearly для оформления.")

    await message.answer("\n".join(lines))


@router.message(Command("pay_monthly"))
async def cmd_pay_monthly(message: Message):
    """Создаёт инвойс на месячную подписку."""
    await _create_invoice(message, "monthly")


@router.message(Command("pay_yearly"))
async def cmd_pay_yearly(message: Message):
    """Создаёт инвойс на годовую подписку."""
    await _create_invoice(message, "yearly")


async def _create_invoice(message: Message, plan_id: str):
    """Создаёт счёт на оплату через ЮKassa."""
    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if plan is None:
        await message.answer("Неизвестный тариф.")
        return

    user_id = message.from_user.id

    # Проверяем, нет ли уже активной подписки
    conn = await get_conn()
    repo = UserRepository(conn)
    user = await repo.get(user_id)

    if user and user.subscription:
        status = await get_user_subscription_status(user, repo)
        if status["active"]:
            await message.answer(
                "✅ У тебя уже есть активная подписка!\n"
                f"Осталось дней: {status['days_left']}"
            )
            return

    prices = [LabeledPrice(label=plan["name"], amount=plan["price_kopecks"])]
    token = PROVIDER_TOKEN or ""

    await message.answer_invoice(
        title=f"Подписка «{plan['name']}»",
        description=f"Доступ к AI-репетитору английского на {plan['duration_days']} дней",
        provider_token=token,
        currency="RUB",
        prices=prices,
        payload=f"sub_{plan_id}_{user_id}",
        need_email=False,
        need_phone_number=False,
        need_name=False,
        need_shipping_address=False,
    )


@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    """Подтверждаем предварительный платёж."""
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    """Обрабатывает успешную оплату."""
    payload = message.successful_payment.invoice_payload

    # payload = sub_{plan_id}_{user_id}
    parts = payload.split("_")
    if len(parts) < 3:
        await message.answer("❌ Ошибка обработки платежа.")
        return

    plan_id = parts[1]
    user_id = int(parts[2])

    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if plan is None:
        await message.answer("❌ Неизвестный тариф.")
        return

    # Устанавливаем подписку
    conn = await get_conn()
    repo = UserRepository(conn)

    expiry = (
        datetime.now(timezone.utc) + timedelta(days=plan["duration_days"])
    ).isoformat()
    await repo.set_subscription(user_id, True, expiry)

    await message.answer(
        f"🎉 <b>Подписка оформлена!</b>\n\n"
        f"Тариф: {plan['name']}\n"
        f"Длительность: {plan['duration_days']} дней\n\n"
        f"Теперь у тебя нет лимита на диалоги! "
        f"Просто продолжай заниматься английским."
    )
