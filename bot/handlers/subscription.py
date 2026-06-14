"""Хендлер подписки — /subscribe, pre_checkout_query, successful_payment."""

import logging
from datetime import datetime, timedelta, timezone

from typing import Union

from aiogram import Router, F
from aiogram.types import (
    Message,
    PreCheckoutQuery,
    LabeledPrice,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import Command

from bot.db import UserRepository, get_conn
from bot.services.subscription_service import (
    SUBSCRIPTION_PLANS,
    PROVIDER_TOKEN,
    get_user_subscription_status,
    activate_trial,
    has_active_trial,
    TRIAL_DURATION_DAYS,
)
from bot.keyboards import subscription_kb, subscription_status_kb, main_menu_kb

logger = logging.getLogger(__name__)

router = Router()

# provider_token для ЮKassa (устанавливается при старте бота)
# В main.py: set_provider_token(os.getenv("YOOKASSA_PROVIDER_TOKEN", ""))


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    """Показывает тарифы с кнопками подписки."""
    conn = await get_conn()
    repo = UserRepository(conn)
    try:
        user = await repo.get(message.from_user.id)
        has_trial = user is not None and not user.trial_taken
        in_trial = user is not None and user.trial_taken and user.subscription
        sub_active = user is not None and user.subscription

        lines = [
            "<b>💎 Тарифы</b>\n\n",
            "<b>⭐ Premium</b>\n",
            "• Безлимитные диалоги с AI\n",
            "• Исправление ошибок и разбор грамматики\n",
            "• Персональный словарь\n",
            "• Все режимы обучения\n",
            "• Голосовые ответы (TTS)\n",
            "• Микро-уроки и статистика\n",
        ]
        premium_monthly = SUBSCRIPTION_PLANS["monthly"]
        premium_yearly = SUBSCRIPTION_PLANS["yearly"]
        lines.append(f"• {premium_monthly['price_rub']}₽/мес или {premium_yearly['price_rub']}₽/год\n\n")

        lines.append("<b>💎 Pro (всё из Premium +)</b>\n")
        lines.append("• Приоритетная AI-модель (более качественные ответы)\n")
        lines.append("• Детальный анализ произношения\n")
        lines.append("• Расширенная статистика прогресса\n")
        pro_monthly = SUBSCRIPTION_PLANS["pro_monthly"]
        pro_yearly = SUBSCRIPTION_PLANS["pro_yearly"]
        lines.append(f"• {pro_monthly['price_rub']}₽/мес или {pro_yearly['price_rub']}₽/год\n")

        if has_trial and not in_trial and not sub_active:
            lines.append(f"\n🆓 Есть {TRIAL_DURATION_DAYS}-дневный триал Premium!")

        await message.answer(
            "".join(lines),
            reply_markup=subscription_kb(
                has_trial=has_trial,
                in_trial=in_trial,
                subscription_active=sub_active,
            ),
        )
    finally:
        await conn.close()


async def _check_trial(message: Message) -> bool:
    """Проверяет и показывает статус триала.

    Returns:
        True если триал можно активировать, False если уже использован или активен.
    """
    conn = await get_conn()
    repo = UserRepository(conn)
    try:
        user = await repo.get(message.from_user.id)
        if user is None:
            return True  # новый пользователь — триал доступен

        if user.trial_taken:
            active = await has_active_trial(user, repo)
            if active:
                await message.answer(
                    "✨ У тебя уже активен Premium-триал!\n"
                    f"Осталось дней: {status['days_left'] if (status := await get_user_subscription_status(user, repo))['active'] else 0}"
                )
            else:
                await message.answer(
                    "⏳ Твой триал Premium уже закончился.\n"
                    "Оформи подписку: /subscribe"
                )
            return False
        return True
    finally:
        await conn.close()


@router.message(Command("trial"))
async def cmd_trial(message: Message):
    """Активирует 3-дневный триал Premium."""
    conn = await get_conn()
    repo = UserRepository(conn)
    try:
        ok = await activate_trial(message.from_user.id, repo)
        if ok:
            await message.answer(
                f"🎉 <b>Premium-триал активирован на {TRIAL_DURATION_DAYS} дня!</b>\n\n"
                "Тебе доступны все функции без ограничений:\n"
                "• Безлимитные диалоги с AI\n"
                "• Исправление ошибок и разбор грамматики\n"
                "• Персональный словарь и статистика\n"
                "• Микро-уроки и трекинг прогресса\n\n"
                "Через 3 дня триал закончится — можно будет оформить подписку: /subscribe\n"
                "А пока — просто продолжай заниматься английским! 🚀",
                reply_markup=main_menu_kb(
                    subscription_active=True,
                    trial_available=False,
                    tier="premium",
                ),
            )
        else:
            await message.answer(
                "❌ Ты уже использовал пробный период.\n"
                "Оформи подписку: /subscribe"
            )
    finally:
        await conn.close()


@router.message(Command("pay_monthly"))
async def cmd_pay_monthly(message: Message):
    """Создаёт инвойс на месячную подписку Premium."""
    await _create_invoice(message, "monthly")


@router.message(Command("pay_yearly"))
async def cmd_pay_yearly(message: Message):
    """Создаёт инвойс на годовую подписку Premium."""
    await _create_invoice(message, "yearly")


@router.message(Command("pro_monthly"))
async def cmd_pro_monthly(message: Message):
    """Создаёт инвойс на месячную подписку Pro."""
    await _create_invoice(message, "pro_monthly")


@router.message(Command("pro_yearly"))
async def cmd_pro_yearly(message: Message):
    """Создаёт инвойс на годовую подписку Pro."""
    await _create_invoice(message, "pro_yearly")


async def _create_invoice(source: Union[Message, CallbackQuery], plan_id: str):
    """Создаёт счёт на оплату через ЮKassa.

    Принимает Message или CallbackQuery — извлекает нужные атрибуты.
    """
    # Нормализуем: получаем Message и user_id из любого типа
    if isinstance(source, CallbackQuery):
        message = source.message
        user_id = source.from_user.id
    else:
        message = source
        user_id = source.from_user.id

    plan = SUBSCRIPTION_PLANS.get(plan_id)
    if plan is None:
        await message.answer("Неизвестный тариф.")
        return

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

    if not token or len(token) < 10:
        await message.answer(
            "💳 Оплата временно недоступна.\n"
            "ЮKassa ещё не подключена — скоро заработает!\n"
            "Пока все функции бота бесплатны."
        )
        return

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
