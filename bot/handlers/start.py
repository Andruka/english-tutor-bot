"""Хендлеры для /start и регистрации пользователя."""

import logging
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, Command

from bot.db import UserRepository, get_conn

router = Router()
logger = logging.getLogger(__name__)

LEVELS = ["A1", "A2", "B1", "B2", "C1"]
TOPICS = [
    "introduction",
    "family",
    "daily_routine",
    "hobbies",
    "travel",
    "food",
    "work",
    "weather",
]


def level_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура выбора уровня."""
    buttons = [[KeyboardButton(text=level)] for level in LEVELS]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def topic_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура выбора темы."""
    buttons = [
        [KeyboardButton(text=topic.replace("_", " ").capitalize())] for topic in TOPICS
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=True,
    )


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик /start — приветствие и регистрация."""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "User"

    conn = await get_conn()
    repo = UserRepository(conn)

    existing = await repo.get(user_id)
    if existing:
        await message.answer(
            f"👋 С возвращением, {username}!\n"
            f"Твой уровень: {existing.level}\n"
            f"Streak: {existing.streak} дней\n\n"
            f"Напиши что-нибудь на английском, и я помогу тебе улучшить язык! ✨"
        )
        return

    await repo.create(user_id=user_id, level="A2", username=username)
    await message.answer(
        f"👋 Привет, {username}! Я AI-репетитор английского.\n\n"
        f"Я помогу тебе:\n"
        f"🎯 Практиковать разговорный английский\n"
        f"✏️ Исправлять ошибки\n"
        f"📈 Отслеживать прогресс\n\n"
        f"Выбери свой уровень:",
        reply_markup=level_keyboard(),
    )


@router.message(F.text.in_(LEVELS))
async def select_level(message: Message):
    """Обработчик выбора уровня."""
    level = message.text.strip().upper()
    user_id = message.from_user.id

    conn = await get_conn()
    repo = UserRepository(conn)
    await repo.set_level(user_id, level)

    await message.answer(
        f"Отлично! Уровень <b>{level}</b> сохранён.\n\n"
        f"Теперь выбери тему для первого урока:",
        reply_markup=topic_keyboard(),
    )


@router.message(Command("level"))
async def cmd_level(message: Message):
    """Смена уровня."""
    await message.answer(
        "Выбери свой уровень:",
        reply_markup=level_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Справка."""
    await message.answer(
        "🤖 <b>AI-репетитор английского</b>\n\n"
        "Команды:\n"
        "/start — начать / вернуться\n"
        "/level — сменить уровень\n"
        "/topic — сменить тему урока\n"
        "/help — эта справка\n\n"
        "Просто напиши что-нибудь на английском или отправь голосовое сообщение!"
    )


@router.message(Command("topic"))
async def cmd_topic(message: Message):
    """Смена темы урока."""
    await message.answer(
        "Выбери тему:",
        reply_markup=topic_keyboard(),
    )


TOPIC_ALIASES = {
    "introduction": ["introduction", "знакомство"],
    "family": ["family", "семья"],
    "daily routine": ["daily_routine", "daily routine", "рутина", "ежедневные"],
    "hobbies": ["hobbies", "хобби", "увлечения"],
    "travel": ["travel", "путешествия"],
    "food": ["food", "еда"],
    "work": ["work", "работа"],
    "weather": ["weather", "погода"],
}
