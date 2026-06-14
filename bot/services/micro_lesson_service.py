"""Micro-lessons generated from a learner's recurring mistakes."""

import re
from collections import Counter
from dataclasses import dataclass

import aiosqlite

from bot.db import (
    DialogueRepository,
    MicroLesson,
    MicroLessonAttempt,
    MicroLessonRepository,
)


@dataclass
class LessonDraft:
    topic: str
    explanation: str
    examples: list[str]
    exercise: str
    answer_key: str
    source_errors: list[dict]


def _normalise_answer(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _pick_representative_error(corrections: list[dict]) -> dict | None:
    if not corrections:
        return None
    key_counts = Counter(
        (
            c.get("category", "grammar"),
            c.get("original", "").strip().lower(),
            c.get("corrected", "").strip().lower(),
        )
        for c in corrections
    )
    category, original, corrected = key_counts.most_common(1)[0][0]
    for correction in corrections:
        if (
            correction.get("category", "grammar") == category
            and correction.get("original", "").strip().lower() == original
            and correction.get("corrected", "").strip().lower() == corrected
        ):
            return correction
    return corrections[0]


def _topic_for(correction: dict | None, level: str) -> str:
    if not correction:
        return f"{level}: базовый порядок слов в английском предложении"

    text = " ".join(
        [
            correction.get("original", ""),
            correction.get("corrected", ""),
            correction.get("explanation", ""),
            correction.get("category", ""),
        ]
    ).lower()
    if "past simple" in text or "yesterday" in text or "went" in text:
        return "Past Simple: когда говорить I went, а не I go"
    if "present perfect" in text:
        return "Present Perfect: have/has + V3"
    if "article" in text or " a " in text or " the " in text:
        return "Articles: a/an/the"
    if "preposition" in text:
        return "Prepositions: короткие предлоги места и времени"
    category = correction.get("category", "grammar").strip().capitalize()
    return f"{category}: исправляем частую ошибку"


def _draft_from_correction(correction: dict | None, level: str) -> LessonDraft:
    if not correction:
        topic = _topic_for(None, level)
        answer_key = "I usually study English in the evening."
        return LessonDraft(
            topic=topic,
            explanation=(
                "Мини-урок на 3 минуты: в простом английском предложении обычно идёт "
                "сначала кто/что, потом действие, потом детали. Почему это важно: такой "
                "порядок помогает собеседнику сразу понять мысль."
            ),
            examples=[
                "I study English every day.",
                "She reads books in the evening.",
            ],
            exercise="Составь правильное предложение: usually / I / English / study / in the evening",
            answer_key=answer_key,
            source_errors=[],
        )

    original = correction.get("original", "I go") or "I go"
    corrected = correction.get("corrected", "I went") or "I went"
    explanation = (
        correction.get("explanation")
        or "После слова yesterday обычно нужен Past Simple."
    )
    topic = _topic_for(correction, level)

    if "went" in corrected.lower() or "past simple" in topic.lower():
        examples = [
            "Yesterday I went to school.",
            "Last week she visited her friend.",
        ]
        exercise = "Исправь предложение: I go to school yesterday."
        answer_key = "I went to school yesterday."
    else:
        examples = [
            f"Wrong: {original}",
            f"Right: {corrected}",
        ]
        exercise = f"Исправь фразу: {original}"
        answer_key = corrected

    return LessonDraft(
        topic=topic,
        explanation=(
            f"Почему так: {explanation} Мини-урок на 3 минуты: запомни шаблон, "
            "посмотри на примеры и сразу закрепи правилом в одном упражнении."
        ),
        examples=examples,
        exercise=exercise,
        answer_key=answer_key,
        source_errors=[correction],
    )


async def generate_micro_lesson(
    user_id: int,
    level: str,
    conn: aiosqlite.Connection,
) -> MicroLesson:
    """Generate and persist a short lesson from the user's latest corrections."""
    history = await DialogueRepository(conn).get_history(user_id, limit=30)
    corrections: list[dict] = []
    for entry in history:
        corrections.extend(c for c in entry.corrections if isinstance(c, dict))

    draft = _draft_from_correction(_pick_representative_error(corrections), level)
    return await MicroLessonRepository(conn).create(
        user_id=user_id,
        topic=draft.topic,
        explanation=draft.explanation,
        examples=draft.examples,
        exercise=draft.exercise,
        answer_key=draft.answer_key,
        source_errors=draft.source_errors,
    )


async def check_lesson_attempt(
    user_id: int,
    lesson_id: int,
    answer: str,
    conn: aiosqlite.Connection,
) -> MicroLessonAttempt:
    """Check a user's exercise answer and persist the attempt."""
    repo = MicroLessonRepository(conn)
    lesson = await repo.get(lesson_id)
    if lesson is None or lesson.user_id != user_id:
        raise ValueError("Мини-урок не найден")

    normalized_answer = _normalise_answer(answer)
    normalized_key = _normalise_answer(lesson.answer_key)
    is_correct = (
        normalized_answer == normalized_key or normalized_key in normalized_answer
    )
    if is_correct:
        feedback = f"Верно! Ответ: {lesson.answer_key}. Отлично закрепил правило."
    else:
        feedback = (
            f"Почти, попробуй ещё раз. Правильный ответ: {lesson.answer_key}. "
            f"Подсказка: {lesson.explanation}"
        )
    return await repo.save_attempt(user_id, lesson_id, answer, is_correct, feedback)


def format_micro_lesson(lesson: MicroLesson) -> str:
    examples = "\n".join(f"• {example}" for example in lesson.examples)
    return (
        f"📝 <b>Мини-урок: {lesson.topic}</b>\n\n"
        f"{lesson.explanation}\n\n"
        f"<b>Примеры</b>\n{examples}\n\n"
        f"<b>Упражнение</b>\n{lesson.exercise}\n\n"
        "Ответь командой: <code>/lesson твой ответ</code>"
    )


def format_attempt_result(attempt: MicroLessonAttempt) -> str:
    status = "✅" if attempt.is_correct else "💡"
    return f"{status} <b>Ответ проверен</b>\n\n{attempt.feedback}"
