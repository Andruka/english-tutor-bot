"""
Общие функции для хендлеров диалога.
"""

import logging
import uuid
from typing import Optional
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.db import UserRepository, DialogueRepository, DictionaryRepository
from bot.services.progress_service import (
    AchievementChecker,
    AchievementRepository,
    ACHIEVEMENT_DEFINITIONS,
    SkillProgressRepository,
    WeeklyChallengeRepository,
)
from bot.services.voice_service import VoiceService
from bot.keyboards import after_dialogue_kb
from bot.services.ai_service import MODE_ICONS, MODE_FREE_TALK

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


def _infer_skill_branch(text: str, mode: str | None, result: dict) -> str:
    """Определяет ветку навыков для начисления очков за практику."""
    if mode == "grammar_focus" or result.get("corrections"):
        return "grammar"
    if result.get("new_words") or len(text.split()) <= 3:
        return "vocabulary"
    if text.strip().endswith("?"):
        return "speaking"
    return "writing" if len(text.split()) >= 12 else "speaking"


async def build_dialogue_reply(result: dict, mode: str | None = None) -> str:
    """Собирает текст ответа из результата AI."""
    mode_prefix = (
        f"{MODE_ICONS.get(mode, '')} " if mode and mode != MODE_FREE_TALK else ""
    )
    reply = f"{mode_prefix}{result['reply']}\n\n"

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
    mode: str | None = None,
) -> None:
    """Пост-обработка диалога: сохранение, streak, ачивки, TTS."""
    repo = UserRepository(conn)
    dial_repo = DialogueRepository(conn)

    await repo.increment_dialogues(user_id)
    await dial_repo.save(
        user_id,
        text,
        result["reply"],
        topic=topic,
        rating=result.get("rating", 0),
        corrections=result.get("corrections", []),
    )
    await repo.update_streak(user_id)

    # Прогресс геймификации: дерево навыков + weekly challenge.
    branch_id = result.get("skill_branch") or _infer_skill_branch(text, mode, result)
    skill_repo = SkillProgressRepository(conn)
    branch_progress = await skill_repo.award_points(user_id, branch_id, 10)
    weekly_challenge = await WeeklyChallengeRepository(conn).increment_progress(user_id)
    if branch_progress["points"] == 10:
        await AchievementRepository(conn).add(user_id, "skill_tree_started")

    # +XP за каждое исправление (ветка grammar)
    corrections = result.get("corrections", [])
    if corrections:
        await skill_repo.award_points(user_id, "grammar", 5 * len(corrections))

    # Авто-сохранение новых слов в словарь + XP за каждое
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
        # XP за новые слова (ветка vocabulary)
        await skill_repo.award_points(user_id, "vocabulary", 3 * len(new_words))

    # Сборка текстового ответа
    reply_text = await build_dialogue_reply(result, mode=mode)

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

    if weekly_challenge["completed"]:
        reply_text += "\n\n🎯 <b>Weekly Challenge выполнен!</b> Награда добавлена 🏆"
    else:
        reply_text += (
            "\n\n🎯 Weekly Challenge: "
            f"{weekly_challenge['progress']}/{weekly_challenge['goal']} практик"
        )

    response_id = uuid.uuid4().hex
    # Комбинированная клавиатура: Skip TTS + кнопки действий
    tts_markup = build_skip_tts_reply_markup(response_id)
    dialogue_markup = after_dialogue_kb()
    combined_kb = InlineKeyboardMarkup(
        inline_keyboard=tts_markup.inline_keyboard + dialogue_markup.inline_keyboard
    )
    await message.reply(
        reply_text, reply_markup=combined_kb
    )

    # TTS-озвучка ответа
    await send_tts_voice(message, result["reply"])
