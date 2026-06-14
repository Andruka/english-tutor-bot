"""Handler для геймификации: /progress, /achievements, /rank, дерево навыков."""

import logging
from datetime import date

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db import get_conn, UserRepository, DialogueRepository
from bot.services.progress_service import (
    ACHIEVEMENT_DEFINITIONS,
    RANK_THRESHOLDS,
    SKILL_BRANCHES,
    AchievementRepository,
    SkillProgressRepository,
    WeeklyChallengeRepository,
    calculate_rank,
    format_achievements_text,
    get_skill_tree,
)

logger = logging.getLogger(__name__)

router = Router(name="gamification")

PROGRESS_ICONS = {
    "Platinum": "🏆",
    "Gold": "🥇",
    "Silver": "🥈",
    "Bronze": "🥉",
}


def _progress_bar(value: int, total: int = 100, width: int = 12) -> str:
    """Рисует прогресс-бар вида ██████░░░░ 60/100."""
    filled = min(value, total)
    fill_count = filled * width // total
    empty_count = width - fill_count
    bar = "█" * fill_count + "░" * empty_count
    return f"{bar} {filled}/{total}"


def _rank_icon(rank_name: str) -> str:
    return PROGRESS_ICONS.get(rank_name, "🎖️")


def build_progress_text(
    user_level: str,
    streak: int,
    dialogues_today: int,
    total_dialogues: int,
    skill_tree: list[dict],
    rank_name: str,
    weekly_challenge: dict,
    achievement_count: int,
    total_achievements: int,
) -> str:
    """Формирует красивое сообщение прогресса."""
    rank_icon = _rank_icon(rank_name)

    lines = [f"{rank_icon} <b>Твой прогресс</b>\n"]
    lines.append(f"📊 <b>Уровень английского:</b> {user_level}")
    lines.append(f"🏅 <b>Ранг:</b> {rank_icon} {rank_name}")

    streak_emoji = "🔥" if streak >= 7 else "⭐" if streak >= 3 else "🆕"
    lines.append(f"{streak_emoji} <b>Streak:</b> {streak} дней")
    lines.append(f"💬 <b>Диалогов:</b> {total_dialogues} всего  ·  {dialogues_today} сегодня")
    lines.append("")

    # Дерево навыков
    lines.append("📊 <b>Дерево навыков</b>")
    for branch in skill_tree:
        pts = branch["points"]
        lv = pts // 100
        nxt = 100 - (pts % 100)
        bar = _progress_bar(pts % 100, 100, 10)
        lines.append(f"{branch['icon']} {branch['name']}: <b>Lv {lv}</b> {bar}")
    lines.append("")

    # Недельный челлендж
    goal = weekly_challenge["goal"]
    progress = weekly_challenge["progress"]
    done = weekly_challenge["completed"]
    if done:
        lines.append("🎯 <b>Недельный челлендж:</b> ✅ Выполнен!")
    else:
        ch_bar = _progress_bar(progress, goal, 12)
        lines.append(f"🎯 <b>Недельный челлендж:</b> {ch_bar} диалогов")
    lines.append("")

    # Достижения
    lines.append(f"🏆 <b>Достижения:</b> {achievement_count} из {total_achievements}")

    return "\n".join(lines)


def build_achievements_text(
    user_achievements: list[dict],
    achievement_count: int,
) -> str:
    """Формирует сообщение со списком достижений."""
    total = len(ACHIEVEMENT_DEFINITIONS)
    earned_ids = {a["achievement_id"] for a in user_achievements}

    lines = ["🏆 <b>Твои достижения</b>\n"]
    lines.append(f"Получено: {achievement_count} из {total}\n")

    for ach_id, defn in ACHIEVEMENT_DEFINITIONS.items():
        if ach_id in earned_ids:
            lines.append(f"✅ {defn['name']}")
            lines.append(f"   {defn['desc']}")
        else:
            lines.append(f"🔒 {defn['name']}")
            lines.append(f"   {defn['desc']}")
        lines.append("")

    return "\n".join(lines)


async def get_common_data(user_id: int) -> dict | None:
    """Загружает данные для дашборда. Возвращает None если пользователь не найден."""
    conn = await get_conn()
    try:
        user_repo = UserRepository(conn)
        user = await user_repo.get(user_id)
        if user is None:
            return None

        ach_repo = AchievementRepository(conn)
        skill_repo = SkillProgressRepository(conn)
        challenge_repo = WeeklyChallengeRepository(conn)
        dial_repo = DialogueRepository(conn)
        total_dialogues = await dial_repo.count(user_id)
        skill_tree = await skill_repo.get_tree(user_id)
        achievements = await ach_repo.get_all(user_id)
        weekly_challenge = await challenge_repo.get_or_create_current(user_id)

        return {
            "user": user,
            "skill_tree": skill_tree,
            "achievements": achievements,
            "achievement_count": len(achievements),
            "total_achievements": len(ACHIEVEMENT_DEFINITIONS),
            "rank": calculate_rank(skill_tree),
            "weekly_challenge": weekly_challenge,
            "total_dialogues": total_dialogues,
        }
    finally:
        await conn.close()


def progress_keyboard() -> InlineKeyboardBuilder:
    """Клавиатура для страницы прогресса."""
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="🏆 Достижения", callback_data="gami_achievements"),
        InlineKeyboardButton(text="🔄 Обновить", callback_data="gami_refresh"),
    )
    b.row(InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu_main"))
    return b


def achievements_keyboard() -> InlineKeyboardBuilder:
    """Клавиатура для страницы достижений."""
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📊 Прогресс", callback_data="gami_progress"))
    b.row(InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu_main"))
    return b


# ── Команды ─────────────────────────────────────────────────────────────


@router.message(Command("progress", "achievements", "rank"))
async def cmd_progress(message: Message):
    """Показывает дашборд прогресса, достижений, дерева навыков."""
    user_id = message.from_user.id
    cmd = message.text.split()[0].lstrip("/")

    data = await get_common_data(user_id)
    if data is None:
        await message.answer("❓ Сначала зарегистрируйся — отправь /start")
        return

    if cmd == "achievements":
        text = build_achievements_text(data["achievements"], data["achievement_count"])
        await message.answer(text, reply_markup=achievements_keyboard().as_markup())
    else:
        text = build_progress_text(
            user_level=data["user"].level,
            streak=data["user"].streak,
            dialogues_today=data["user"].dialogues_today,
            total_dialogues=data["total_dialogues"],
            skill_tree=data["skill_tree"],
            rank_name=data["rank"],
            weekly_challenge=data["weekly_challenge"],
            achievement_count=data["achievement_count"],
            total_achievements=data["total_achievements"],
        )
        await message.answer(text, reply_markup=progress_keyboard().as_markup())


# ── Внутренняя навигация (gami_*) ───────────────────────────────────────


@router.callback_query(F.data.startswith("gami_"))
async def cb_gami_nav(callback: CallbackQuery):
    """Навигация по страницам геймификации."""
    user_id = callback.from_user.id
    action = callback.data.replace("gami_", "")

    data = await get_common_data(user_id)
    if data is None:
        await callback.message.edit_text("❓ Ошибка загрузки")
        await callback.answer()
        return

    if action == "refresh":
        text = build_progress_text(
            user_level=data["user"].level,
            streak=data["user"].streak,
            dialogues_today=data["user"].dialogues_today,
            total_dialogues=data["total_dialogues"],
            skill_tree=data["skill_tree"],
            rank_name=data["rank"],
            weekly_challenge=data["weekly_challenge"],
            achievement_count=data["achievement_count"],
            total_achievements=data["total_achievements"],
        )
        await callback.message.edit_text(text, reply_markup=progress_keyboard().as_markup())
        await callback.answer("🔄 Обновлено!")
        return

    if action == "achievements":
        text = build_achievements_text(data["achievements"], data["achievement_count"])
        await callback.message.edit_text(text, reply_markup=achievements_keyboard().as_markup())
        await callback.answer()
        return

    if action == "progress":
        text = build_progress_text(
            user_level=data["user"].level,
            streak=data["user"].streak,
            dialogues_today=data["user"].dialogues_today,
            total_dialogues=data["total_dialogues"],
            skill_tree=data["skill_tree"],
            rank_name=data["rank"],
            weekly_challenge=data["weekly_challenge"],
            achievement_count=data["achievement_count"],
            total_achievements=data["total_achievements"],
        )
        await callback.message.edit_text(text, reply_markup=progress_keyboard().as_markup())
        await callback.answer()
        return

    await callback.answer("❓ Неизвестная команда")