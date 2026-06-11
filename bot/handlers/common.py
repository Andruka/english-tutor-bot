"""
Общие функции для хендлеров диалога.
"""

import logging
import uuid
from typing import Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.db import UserRepository, DialogueRepository, DictionaryRepository
from bot.services.progress_service import AchievementChecker, ACHIEVEMENT_DEFINITIONS
from bot.services.voice_service import VoiceService

logger = logging.getLogger(__name__)

# Глобальный экземпляр VoiceService (ленивая инициализация)
_voice_service: Optional[VoiceService] = None
SKIP_TTS_CALLBACK_PREFIX = "skip_tts"


def build_skip_tts_reply_markup(response_id: str) -> InlineKeyboardMarkup:
    """Builds the per-response Skip TTS inline button for the chat UI."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏭ Skip TTS",
                    callback_data=f"{SKIP_TTS_CALLBACK_PREFIX}:{response_id}",
                )
            ]
        ]
    )


def get_voice_service() -> VoiceService:
    global _voice_service
    if _voice_service is None:
        _voice_service = VoiceService()
    return _voice_service


async def send_tts_voice(message: Message, text: str) -> None:
    """Генерирует и отправляет голосовое сообщение с текстом."""
    try:
        voice_svc = get_voice_service()
        audio_path = await voice_svc.text_to_speech(text[:500])  # edge-tts лимит
        logger.info(f"TTS generated: {audio_path} ({len(text)} chars)")
        from aiogram.types import FSInputFile

        await message.reply_voice(voice=FSInputFile(audio_path))
        logger.info("TTS sent successfully")
    except Exception as e:
        logger.warning(f"TTS send failed: {e}")


async def build_dialogue_reply(result: dict) -> str:
    """Собирает текст ответа из результата AI."""
    reply = f"{result['reply']}\n\n"

    if result.get("corrections"):
        reply += "📝 <b>Исправления:</b>\n"
        for c in result["corrections"]:
            reply += f"• <s>{c['original']}</s> → <b>{c['corrected']}</b> ({c.get('category', '')})\n"

    if result.get("rating"):
        stars = "⭐" * result["rating"]
        reply += f"\n<b>Оценка:</b> {stars} ({result['rating']}/5)"

    if result.get("vocabulary_tip"):
        reply += f"\n💡 <b>Совет:</b> {result['vocabulary_tip']}"

    if result.get("explanation"):
        reply += f"\n\n📖 <b>Разбор ошибки:</b>\n{result['explanation']}"

    return reply


async def post_process_dialogue(
    message: Message,
    user_id: int,
    text: str,
    result: dict,
    conn,
    topic: str = "introduction",
) -> None:
    """Пост-обработка диалога: сохранение, streak, ачивки, TTS."""
    repo = UserRepository(conn)
    dial_repo = DialogueRepository(conn)

    await repo.increment_dialogues(user_id)
    await dial_repo.save(user_id, text, result["reply"], topic=topic)
    await repo.update_streak(user_id)

    # Авто-сохранение новых слов в словарь
    new_words = result.get("new_words", [])
    if new_words:
        dict_repo = DictionaryRepository(conn)
        for w in new_words:
            await dict_repo.add_word(
                user_id,
                w.get("word", ""),
                w.get("translation", ""),
                w.get("context", ""),
            )
            logger.info(f"Saved new word: {w.get('word')} for user {user_id}")

    # Сборка текстового ответа
    reply_text = await build_dialogue_reply(result)

    # Проверка достижений
    checker = AchievementChecker(conn)
    total_dialogues = await dial_repo.count(user_id)
    user_updated = await repo.get(user_id)
    new_achievements = await checker.check_after_dialogue(
        user_id,
        dialogue_count=total_dialogues,
        streak=user_updated.streak,
        corrections=result.get("corrections", []),
    )
    if new_achievements:
        achievement_lines = []
        for ach_id in new_achievements:
            ach = ACHIEVEMENT_DEFINITIONS.get(ach_id, {})
            achievement_lines.append(
                f"  {ach.get('name', ach_id)} — {ach.get('desc', '')}"
            )
        reply_text += "\n\n🏆 <b>Новое достижение!</b>\n" + "\n".join(achievement_lines)

    response_id = uuid.uuid4().hex
    await message.reply(
        reply_text, reply_markup=build_skip_tts_reply_markup(response_id)
    )

    # TTS-озвучка ответа
    await send_tts_voice(message, result["reply"])
