"""Handler for CEFR placement test — /test command."""

from __future__ import annotations

import json
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, WebAppInfo
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db import get_conn, UserRepository
from bot.services.placement_test_service import (
    PlacementTestResult,
    run_placement_test,
    finalize_test,
)

router = Router()
logger = logging.getLogger(__name__)

# Active test sessions: user_id -> PlacementTestResult
_active_tests: dict[int, PlacementTestResult] = {}

# ── CEFR level descriptions (in Russian) ────────────────────────────────

CEFR_DESCRIPTIONS: dict[str, str] = {
    "A1": (
        "Начальный уровень (Beginner)\n"
        "• Понимаешь простые фразы и выражения\n"
        "• Можешь представиться и ответить на базовые вопросы\n"
        "• Читаешь короткие простые тексты"
    ),
    "A2": (
        "Элементарный уровень (Elementary)\n"
        "• Понимаешь простые предложения и частые выражения\n"
        "• Можешь рассказать о себе, семье, покупках\n"
        "• Общаешься в простых бытовых ситуациях"
    ),
    "B1": (
        "Средний уровень (Intermediate)\n"
        "• Понимаешь основные идеи на знакомые темы\n"
        "• Можешь объясниться в путешествиях\n"
        "• Рассказываешь о событиях, мечтах, планах"
    ),
    "B2": (
        "Выше среднего (Upper-Intermediate)\n"
        "• Понимаешь сложные тексты на разные темы\n"
        "• Общаешься свободно с носителями языка\n"
        "• Можешь аргументировать свою точку зрения"
    ),
    "C1": (
        "Продвинутый уровень (Advanced)\n"
        "• Понимаешь объёмные сложные тексты\n"
        "• Выражаешься бегло без подготовки\n"
        "• Используешь язык гибко в разных целях"
    ),
    "C2": (
        "В совершенстве (Proficiency)\n"
        "• Понимаешь практически всё услышанное/прочитанное\n"
        "• Выражаешься спонтанно, точно и тонко\n"
        "• Различаешь тонкие смысловые оттенки"
    ),
}


# ── Commands ─────────────────────────────────────────────────────────────


MINIAPP_URL = "https://search-pee-accounting-cordless.trycloudflare.com"


@router.message(Command("miniapp"))
async def cmd_miniapp(message: Message):
    """Start placement test via Telegram Mini App."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🎯 Пройти тест",
        web_app=WebAppInfo(url=MINIAPP_URL),
    )
    await message.answer(
        "🎯 <b>Placement Test</b>\n\n"
        "Пройди тест в удобном формате — вопросы отображаются\n"
        "полностью, больше вариантов ответа.\n\n"
        "Нажми кнопку ниже, чтобы начать.",
        reply_markup=builder.as_markup(),
    )


@router.message(Command("test"))
async def cmd_test(message: Message):
    """Start the CEFR placement test."""
    user_id = message.from_user.id

    # Check if user already has a test in progress
    if user_id in _active_tests:
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Продолжить", callback_data="pt_continue")
        builder.button(text="🔄 Начать заново", callback_data="pt_restart")
        await message.answer(
            "📝 У тебя уже есть незавершённый тест.\n"
            "Хочешь продолжить или начать заново?",
            reply_markup=builder.as_markup(),
        )
        return

    await _start_new_test(user_id, message)


async def _start_new_test(user_id: int, message: Message):
    """Create a new test session and show the first question."""
    seed = f"tg-{user_id}-{message.message_id}"
    result = run_placement_test(user_id, seed)
    _active_tests[user_id] = result

    await _send_question(message, result, 0)


async def _send_question(
    target: Message | CallbackQuery,
    result: PlacementTestResult,
    index: int,
):
    """Send question at given index to user."""
    if index >= len(result.questions):
        # Test complete
        await _finish_test(target, result)
        return

    q = result.questions[index]
    total = len(result.questions)

    # Build keyboard with choices
    builder = InlineKeyboardBuilder()
    for i, choice in enumerate(q.choices):
        builder.button(
            text=choice,
            callback_data=f"pt_answer:{index}:{i}",
        )
    builder.adjust(2)

    text = (
        f"📝 <b>Тест на определение уровня</b>\n\n"
        f"<b>Прогресс: {index + 1}/{total}</b>\n\n"
        f"{q.sentence}\n\n"
        f"Уровень вопроса: {q.level}"
    )

    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await target.answer(text, reply_markup=builder.as_markup())


# ── Callbacks ────────────────────────────────────────────────────────────


@router.callback_query(F.data.startswith("pt_answer:"))
async def cb_answer(callback: CallbackQuery):
    """Handle an answer to a placement test question."""
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Ошибка формата", show_alert=True)
        return

    question_index = int(parts[1])
    choice_index = int(parts[2])

    user_id = callback.from_user.id
    result = _active_tests.get(user_id)
    if not result:
        await callback.answer(
            "⏰ Тест не найден. Начни заново — /test", show_alert=True
        )
        return

    if question_index >= len(result.questions):
        await callback.answer("⏰ Тест уже завершён", show_alert=True)
        return

    q = result.questions[question_index]
    if choice_index >= len(q.choices):
        await callback.answer("Ошибка варианта ответа", show_alert=True)
        return

    chosen = q.choices[choice_index]
    is_correct = chosen == q.correct_answer

    # Store answer
    result.answers[q.id] = is_correct

    # Show feedback
    if is_correct:
        feedback = "✅ Верно!"
    else:
        feedback = f"❌ Правильный ответ: <b>{q.correct_answer}</b>"

    await callback.answer()
    await callback.message.edit_text(
        f"{feedback}\n\n{q.explanation}",
        reply_markup=None,
    )

    # Show next question after a brief delay (via callback)
    next_index = question_index + 1
    if next_index < len(result.questions):
        builder = InlineKeyboardBuilder()
        builder.button(
            text="➡️ Далее",
            callback_data=f"pt_next:{next_index}",
        )
        await callback.message.edit_text(
            f"{feedback}\n\n{q.explanation}",
            reply_markup=builder.as_markup(),
        )
    else:
        # Last question — finish
        await _finish_test(callback, result)


@router.callback_query(F.data.startswith("pt_next:"))
async def cb_next(callback: CallbackQuery):
    """Show the next question."""
    parts = callback.data.split(":")
    next_index = int(parts[1])

    user_id = callback.from_user.id
    result = _active_tests.get(user_id)
    if not result:
        await callback.answer("⏰ Тест не найден", show_alert=True)
        return

    await _send_question(callback, result, next_index)
    await callback.answer()


@router.callback_query(F.data == "pt_continue")
async def cb_continue(callback: CallbackQuery):
    """Continue an existing test."""
    user_id = callback.from_user.id
    result = _active_tests.get(user_id)
    if not result:
        await callback.answer(
            "⏰ Тест не найден. Начни заново — /test", show_alert=True
        )
        return

    # Find the first unanswered question
    for i, q in enumerate(result.questions):
        if q.id not in result.answers:
            await _send_question(callback, result, i)
            await callback.answer()
            return

    # All answered — finish
    await _finish_test(callback, result)
    await callback.answer()


@router.callback_query(F.data == "pt_restart")
async def cb_restart(callback: CallbackQuery):
    """Restart the test from scratch."""
    user_id = callback.from_user.id
    _active_tests.pop(user_id, None)
    await _start_new_test(user_id, callback.message)
    await callback.answer()


# ── Test completion ──────────────────────────────────────────────────────


async def _finish_test(target: Message | CallbackQuery, result: PlacementTestResult):
    """Score the test, save results, and show final level."""
    result = finalize_test(result)
    user_id = result.user_id

    # Save to DB before showing the final message so failures are visible in tests
    # and the user level is durable when Telegram receives the completion screen.
    conn = await get_conn()
    try:
        repo = UserRepository(conn)

        # Save test result
        await conn.execute(
            """INSERT INTO placement_test_results
               (user_id, answers_json, total_questions, correct_answers, score, determined_level)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                json.dumps(result.answers, ensure_ascii=False),
                result.total_count,
                result.correct_count,
                result.score,
                result.determined_level,
            ),
        )

        # Update user level
        await repo.set_level(user_id, result.determined_level)
        await conn.commit()
    finally:
        await conn.close()

    # Build level description
    desc = CEFR_DESCRIPTIONS.get(result.determined_level, "")
    level_scores_str = ", ".join(
        f"{lvl}: {s:.0%}" for lvl, s in result.level_scores.items()
    )

    text = (
        f"🎉 <b>Тест завершён!</b>\n\n"
        f"Твой уровень: <b>{result.determined_level}</b>\n\n"
        f"{desc}\n\n"
        f"📊 Результаты по уровням:\n{level_scores_str}\n\n"
        f"Правильных ответов: {result.correct_count} из {result.total_count} "
        f"({result.score:.0%})"
    )

    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Упражнения", callback_data="ex_back_to_menu")
    builder.button(text="💬 Диалог", callback_data="start_dialogue")
    builder.button(text="🏠 Главное меню", callback_data="menu_main")

    if hasattr(target, "message") and hasattr(target.message, "edit_text"):
        await target.message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await target.answer(text, reply_markup=builder.as_markup())

    # Cleanup
    _active_tests.pop(user_id, None)
