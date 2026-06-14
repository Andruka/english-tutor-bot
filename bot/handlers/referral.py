"""Handlers для реферальной системы."""

import logging
from aiogram import Router, types
from aiogram.filters import Command, CommandObject

from bot.db import get_conn, UserRepository, ReferralRewardRepository
from bot.services.referral_service import generate_referral_link, REFERRAL_REWARD_REFERER_DAYS

logger = logging.getLogger(__name__)

router = Router(name="referral")


@router.message(Command("referral"))
async def cmd_referral(message: types.Message, command: CommandObject):
    """Показывает реферальную ссылку и статистику."""
    user_id = message.from_user.id
    conn = await get_conn()
    user_repo = UserRepository(conn)
    reward_repo = ReferralRewardRepository(conn)

    user = await user_repo.get(user_id)
    if not user:
        await message.answer("⚠️ Сначала зарегистрируйся через /start")
        return

    referral_link = generate_referral_link(user_id)
    referral_count = await user_repo.get_referral_count(user_id)
    rewards = await reward_repo.get_by_user(user_id)
    total_earned = sum(r.reward_value for r in rewards if r.claimed)

    text = (
        f"🤝 <b>Реферальная программа</b>\n\n"
        f"Приведи друга и получи {REFERRAL_REWARD_REFERER_DAYS} дней Premium!\n"
        f"Твой друг тоже получит 3 дня Premium в подарок.\n\n"
        f"👥 <b>Приглашено:</b> {referral_count}\n"
        f"🎁 <b>Заработано дней Premium:</b> {total_earned}\n\n"
        f"🔗 <b>Твоя ссылка:</b>\n<code>{referral_link}</code>\n\n"
        f"<i>Просто отправь её другу. Когда он зарегистрируется, "
        f"вы оба получите бонус!</i>"
    )

    await message.answer(
        text,
        reply_markup=types.InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    types.InlineKeyboardButton(
                        text="📤 Поделиться ссылкой",
                        url=f"https://t.me/share/url?url={referral_link}&text=🎯 Занимайся английским с ИИ-тьютором бесплатно! Присоединяйся по моей ссылке и получи 3 дня Premium 🚀",
                    )
                ],
            ]
        ),
    )