"""Хендлеры диалога с AI-репетитором."""

import logging
import os
from aiogram import Router, F
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)
from aiogram.filters import Command

from bot.services.ai_service import AITutor
from bot.services.voice_service import VoiceService
from bot.db import UserRepository, get_conn
from bot.handlers.start import TOPIC_ALIASES
from bot.admin_api import mark_text_response_tts_skipped
from bot.handlers.common import SKIP_TTS_CALLBACK_PREFIX, post_process_dialogue

router = Router()
logger = logging.getLogger(__name__)

_tutor_sessions: dict[int, AITutor] = {}
_user_topics: dict[int, str] = {}

FREE_DAILY_LIMIT = 5


def _skip_tts_status_markup(text: str) -> InlineKeyboardMarkup:
    """Returns a non-actionable status button to disable repeated Skip TTS clicks."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data="skip_tts_noop")]
        ]
    )


def get_or_create_tutor(user_id: int, level: str, topic: str) -> AITutor:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY не задан — AI-функции недоступны")
    existing = _tutor_sessions.get(user_id)
    if existing is None:
        _tutor_sessions[user_id] = AITutor(
            level=level,
            api_key=api_key,
            topic=topic or "introduction",
        )
    elif existing.level != level or existing.topic != topic:
        _tutor_sessions[user_id] = AITutor(
            level=level,
            api_key=api_key,
            topic=topic or "introduction",
        )
    return _tutor_sessions[user_id]


async def _check_limit(message: Message, user) -> bool:
    """Проверяет дневной лимит. Возвращает True, если лимит не превышен."""
    if not user.subscription and user.dialogues_today >= FREE_DAILY_LIMIT:
        await message.answer(
            f"📊 Дневной лимит ({FREE_DAILY_LIMIT} диалогов) исчерпан.\n\n"
            "Оформи подписку для неограниченного доступа:\n"
            "— 5$/мес: безлимитные диалоги\n"
            "— Исправления ошибок + словарные подсказки\n"
            "— Статистика прогресса\n\n"
            "Напиши /subscribe для оформления."
        )
        return False
    return True


async def _resolve_topic(text: str, user_id: int) -> str | None:
    """Проверяет, не выбрал ли пользователь тему текстом. Возвращает тему или None."""
    text_lower = text.lower()
    for topic_name, aliases in TOPIC_ALIASES.items():
        if text_lower in aliases:
            _user_topics[user_id] = topic_name
            return topic_name
    return None


@router.callback_query(F.data.startswith(f"{SKIP_TTS_CALLBACK_PREFIX}:"))
async def handle_skip_tts_callback(callback):
    """Handles the Skip TTS inline button and confirms the skipped state."""
    response_id = callback.data.split(":", 1)[1].strip()
    if not response_id:
        await callback.answer("Cannot skip TTS: missing response id.", show_alert=True)
        return

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=_skip_tts_status_markup("⏳ Skipping TTS...")
        )

    session_id = str(callback.from_user.id)
    text = callback.message.text if callback.message and callback.message.text else ""
    mark_text_response_tts_skipped(session_id, response_id, text)

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=_skip_tts_status_markup("✅ TTS skipped")
        )
    await callback.answer("TTS skipped for this response.")


@router.callback_query(F.data == "skip_tts_noop")
async def handle_skip_tts_noop(callback):
    """Acknowledges disabled Skip TTS status buttons without changing state."""
    await callback.answer()


@router.message(F.text, ~F.text.startswith("/"))
async def handle_text_dialogue(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    logger.info(f"DIALOGUE ENTER: user={user_id}, text={text!r}")

    if not text:
        await message.answer("Напиши что-нибудь на английском! 🗣️")
        return

    conn = await get_conn()
    repo = UserRepository(conn)
    user = await repo.get(user_id)

    if user is None:
        await message.answer("Пожалуйста, начни с команды /start")
        return

    if not await _check_limit(message, user):
        return

    topic = _user_topics.get(user_id, "introduction")

    # Проверка выбора темы текстом
    selected_topic = await _resolve_topic(text, user_id)
    if selected_topic:
        await message.answer(
            f"Тема <b>{selected_topic.capitalize()}</b> выбрана!\n\n"
            f"Напиши что-нибудь на английском на эту тему. 👇",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    tutor = get_or_create_tutor(user_id, user.level, topic)

    await message.bot.send_chat_action(chat_id=user_id, action="typing")

    try:
        result = await tutor.chat(text)
        await post_process_dialogue(message, user_id, text, result, conn, topic=topic)
    except Exception as e:
        logger.error(f"AI error for user {user_id}: {e}")
        await message.reply(
            "Извини, произошла ошибка при обработке запроса. "
            "Пожалуйста, попробуй ещё раз через несколько секунд. 🙏"
        )


@router.message(F.voice)
async def handle_voice_dialogue(message: Message):
    user_id = message.from_user.id

    conn = await get_conn()
    repo = UserRepository(conn)
    user = await repo.get(user_id)

    if user is None:
        await message.answer("Пожалуйста, начни с команды /start")
        return

    if not await _check_limit(message, user):
        return

    # Мгновенный фидбек — пользователь сразу видит, что бот работает
    status_msg = await message.reply("🎤 <i>Обрабатываю голосовое сообщение...</i>")

    try:
        voice_svc = VoiceService()

        # Этап 1: скачивание
        await status_msg.edit_text("🎤 Скачиваю аудио... (1/4)")
        file_path = await voice_svc.download_voice(message.voice.file_id, message.bot)

        # Этап 2: транскрипция (через OpenRouter Whisper API — ~1-2 сек)
        await status_msg.edit_text("🎤 Распознаю речь... (2/4)")
        await message.bot.send_chat_action(chat_id=user_id, action="typing")
        text = await voice_svc.get_transcription(
            file_path,
            duration_seconds=message.voice.duration,
        )

        if not text:
            await status_msg.edit_text(
                "😕 Не удалось распознать речь. Попробуй ещё раз или используй текст."
            )
            return

        # Показываем распознанный текст
        await status_msg.edit_text(
            f"🎤 <i>Распознано:</i> '{text}'\n\n⏳ Отвечаю... (3/4)"
        )

        # Этап 3: AI ответ
        await message.bot.send_chat_action(chat_id=user_id, action="typing")
        topic = _user_topics.get(user_id, "introduction")
        tutor = get_or_create_tutor(user_id, user.level, topic)
        result = await tutor.chat(text)

        # Добавляем распознанный текст префиксом к ответу
        result["reply"] = f"🎤 <i>Распознано:</i> {text}\n\n{result['reply']}"

        # Этап 4: пост-обработка (сохранение + ачивки + TTS)
        await status_msg.edit_text(
            f"🎤 <i>Распознано:</i> '{text}'\n\n⏳ Готовлю ответ... (4/4)"
        )
        await post_process_dialogue(message, user_id, text, result, conn, topic=topic)

        # Удаляем статусное сообщение после отправки полного ответа
        await status_msg.delete()
    except ValueError as e:
        # Лимиты (длительность / дневной бюджет)
        await status_msg.edit_text(str(e))
    except Exception as e:
        logger.error(f"Voice error for user {user_id}: {e}")
        await status_msg.edit_text(
            "😕 Ошибка при обработке голоса. Попробуй текст или повтори позже. 🙏"
        )


@router.message(Command("new"))
async def cmd_new(message: Message):
    user_id = message.from_user.id
    if user_id in _tutor_sessions:
        del _tutor_sessions[user_id]
    await message.answer("🔄 Новая сессия начата! Напиши что-нибудь на английском.")


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    user_id = message.from_user.id
    conn = await get_conn()
    repo = UserRepository(conn)
    user = await repo.get(user_id)

    if user is None:
        await message.answer("Пожалуйста, начни с команды /start")
        return

    # Import inside function to avoid circular imports
    from bot.db import DialogueRepository as DR

    dial_repo = DR(conn)
    total = await dial_repo.count(user_id)

    await message.answer(
        f"📊 <b>Твоя статистика</b>\n\n"
        f"Уровень: {user.level}\n"
        f"Streak: {user.streak} дней\n"
        f"Диалогов сегодня: {user.dialogues_today}/{FREE_DAILY_LIMIT}\n"
        f"Всего диалогов: {total}\n"
        f"Подписка: {'✅ Активна' if user.subscription else '❌ Нет'}\n\n"
        f"Напиши /achievements чтобы увидеть список достижений!\n"
        f"Чтобы продолжить, просто напиши что-нибудь!"
    )


@router.message(Command("achievements"))
async def cmd_achievements(message: Message):
    user_id = message.from_user.id
    conn = await get_conn()
    repo = UserRepository(conn)
    user = await repo.get(user_id)

    if user is None:
        await message.answer("Пожалуйста, начни с команды /start")
        return

    from bot.services.progress_service import (
        AchievementRepository,
        ACHIEVEMENT_DEFINITIONS,
    )

    ach_repo = AchievementRepository(conn)
    all_achievements = []
    for ach_id, defn in ACHIEVEMENT_DEFINITIONS.items():
        earned = await ach_repo.has(user_id, ach_id)
        icon = "✅" if earned else "⬜"
        all_achievements.append(f"{icon} <b>{defn['name']}</b> — {defn['desc']}")

    await message.answer("🏆 <b>Твои достижения</b>\n\n" + "\n".join(all_achievements))
