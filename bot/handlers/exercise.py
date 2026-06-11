"""Хендлеры для генерации и проверки упражнений по уровню."""

import logging
import random
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, BaseFilter
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db import get_conn, UserRepository
from bot.exercise_generators import (
    GapFillRequest,
    ChoiceRequest,
    TranslationRequest,
    generate_gap_fill_exercise,
    generate_choice_exercise,
    generate_translation_exercise,
)

router = Router()
logger = logging.getLogger(__name__)

# Хранилище активных упражнений: user_id -> exercise dict
_active_exercises: dict[int, dict] = {}

EXERCISE_TYPES = {
    "gap_fill": "📝 Вставь пропущенное слово",
    "choice": "✅ Выбери правильный вариант",
    "translation": "🌍 Переведи на английский",
}


@router.message(Command("exercise"))
async def cmd_exercise(message: Message):
    """Показывает список типов упражнений."""
    builder = InlineKeyboardBuilder()
    for ex_type, label in EXERCISE_TYPES.items():
        builder.button(text=label, callback_data=f"ex_type:{ex_type}")
    builder.adjust(1)

    await message.answer(
        "🎯 <b>Упражнения</b>\n\n"
        "Выбери тип упражнения. Сложность подстроится под твой уровень.\n\n"
        "Доступные типы:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("ex_type:"))
async def cb_select_type(callback: CallbackQuery):
    """Генерирует упражнение выбранного типа."""
    ex_type = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    conn = await get_conn()
    repo = UserRepository(conn)
    user = await repo.get(user_id)

    if user is None:
        await callback.message.edit_text(
            "Пожалуйста, начни с команды /start, чтобы я мог подобрать упражнение под твой уровень."
        )
        await callback.answer()
        return

    level = user.level
    topic = random.choice(
        [
            "introduction",
            "family",
            "daily_routine",
            "hobbies",
            "travel",
            "food",
            "work",
            "weather",
        ]
    )
    seed = f"tg-{user_id}-{ex_type}-{callback.message.message_id}"

    try:
        if ex_type == "gap_fill":
            exercise = generate_gap_fill_exercise(
                GapFillRequest(user_id=user_id, level=level, topic=topic, seed=seed)
            )
        elif ex_type == "choice":
            exercise = generate_choice_exercise(
                ChoiceRequest(user_id=user_id, level=level, topic=topic, seed=seed)
            )
        elif ex_type == "translation":
            exercise = generate_translation_exercise(
                TranslationRequest(user_id=user_id, level=level, topic=topic, seed=seed)
            )
        else:
            await callback.answer("Неизвестный тип упражнения", show_alert=True)
            return
    except Exception as e:
        logger.error(f"Exercise generation error for user {user_id}: {e}")
        await callback.message.edit_text(
            "😕 Не удалось сгенерировать упражнение. Попробуй ещё раз."
        )
        await callback.answer()
        return

    # Сохраняем активное упражнение для проверки ответа
    _active_exercises[user_id] = exercise

    if ex_type == "gap_fill":
        await _send_gap_fill(callback, exercise, level, topic)
    elif ex_type == "choice":
        await _send_choice(callback, exercise, level, topic)
    elif ex_type == "translation":
        await _send_translation(callback, exercise, level, topic)

    await callback.answer()


async def _send_gap_fill(
    callback: CallbackQuery, exercise: dict, level: str, topic: str
):
    """Отправляет gap-fill упражнение с кнопками вариантов."""
    sentence = exercise["payload"]["sentence"]
    possible = exercise["payload"]["possible_answers"]
    exercise_id = exercise["exercise_id"]

    # Перемешиваем ответы для UX
    shuffled = list(possible)
    random.shuffle(shuffled)

    builder = InlineKeyboardBuilder()
    for answer in shuffled:
        builder.button(text=answer, callback_data=f"ex_answer:{exercise_id}:{answer}")
    builder.adjust(2)

    # Кнопка «следующее» и «другое упражнение»
    builder.button(text="🔄 Другое", callback_data="ex_type:gap_fill")
    builder.button(text="🎯 Меню", callback_data="ex_back_to_menu")

    await callback.message.edit_text(
        f"📝 <b>Вставь пропущенное слово</b>\n\n"
        f"{sentence}\n\n"
        f"Уровень: {level} • Тема: {topic}",
        reply_markup=builder.as_markup(),
    )


async def _send_choice(callback: CallbackQuery, exercise: dict, level: str, topic: str):
    """Отправляет multiple-choice упражнение с кнопками."""
    sentence = exercise["payload"]["sentence"]
    choices = list(exercise["payload"]["choices"])
    exercise_id = exercise["exercise_id"]

    random.shuffle(choices)

    builder = InlineKeyboardBuilder()
    for choice in choices:
        builder.button(text=choice, callback_data=f"ex_answer:{exercise_id}:{choice}")
    builder.adjust(2)
    builder.button(text="🔄 Другое", callback_data="ex_type:choice")
    builder.button(text="🎯 Меню", callback_data="ex_back_to_menu")

    await callback.message.edit_text(
        f"✅ <b>Выбери правильный вариант</b>\n\n"
        f"{sentence}\n\n"
        f"Уровень: {level} • Тема: {topic}",
        reply_markup=builder.as_markup(),
    )


async def _send_translation(
    callback: CallbackQuery, exercise: dict, level: str, topic: str
):
    """Отправляет переводное упражнение."""
    source_text = exercise["payload"]["source_text"]
    hints = exercise["payload"]["hints"]
    exercise_id = exercise["exercise_id"]

    hints_text = ""
    if hints:
        hints_text = "\n💡 Подсказки: " + ", ".join(hints)

    builder = InlineKeyboardBuilder()
    builder.button(
        text="👀 Показать ответ", callback_data=f"ex_show_answer:{exercise_id}"
    )
    builder.button(text="🔄 Другое", callback_data="ex_type:translation")
    builder.button(text="🎯 Меню", callback_data="ex_back_to_menu")

    await callback.message.edit_text(
        f"🌍 <b>Переведи на английский</b>\n\n"
        f"{source_text}{hints_text}\n\n"
        f"Просто напиши перевод текстом 👇\n\n"
        f"Уровень: {level} • Тема: {topic}",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("ex_answer:"))
async def cb_check_answer(callback: CallbackQuery):
    """Проверяет ответ на упражнение."""
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer("Ошибка: неверный формат ответа", show_alert=True)
        return

    exercise_id = parts[1]
    user_answer = parts[2]
    user_id = callback.from_user.id

    exercise = _active_exercises.get(user_id)
    if not exercise or exercise.get("exercise_id") != exercise_id:
        await callback.answer(
            "⏰ Это упражнение уже неактивно. Создай новое!", show_alert=True
        )
        return

    correct = exercise["correct_answer"]["value"]
    case_sensitive = exercise["correct_answer"]["case_sensitive"]

    is_correct = (
        (user_answer == correct)
        if case_sensitive
        else (user_answer.strip().casefold() == correct.strip().casefold())
    )

    if is_correct:
        await callback.answer("✅ Правильно! Молодец! 🎉")
        # Показываем следующее упражнение того же типа
        ex_type = exercise["type"]
        await callback.message.edit_text(
            f"✅ <b>Верно!</b> 🎉\n\nПравильный ответ: {correct}\n\nХочешь ещё одно?",
            reply_markup=_next_exercise_keyboard(ex_type),
        )
    else:
        await callback.answer(
            "❌ Неверно. Попробуй ещё раз или посмотри ответ.", show_alert=True
        )
        builder = InlineKeyboardBuilder()

        # Добавляем кнопку просмотра ответа
        builder.button(
            text="👀 Показать ответ", callback_data=f"ex_show_answer:{exercise_id}"
        )
        # Возвращаем исходные кнопки
        ex_type = exercise["type"]
        if ex_type == "gap_fill":
            possible = exercise["payload"]["possible_answers"]
            shuffled = list(possible)
            random.shuffle(shuffled)
            for answer in shuffled:
                builder.button(
                    text=answer, callback_data=f"ex_answer:{exercise_id}:{answer}"
                )
            builder.adjust(2)
        elif ex_type == "choice":
            choices = list(exercise["payload"]["choices"])
            random.shuffle(choices)
            for choice in choices:
                builder.button(
                    text=choice, callback_data=f"ex_answer:{exercise_id}:{choice}"
                )
            builder.adjust(2)

        builder.button(text="🔄 Другое", callback_data=f"ex_type:{ex_type}")
        builder.button(text="🎯 Меню", callback_data="ex_back_to_menu")

        await callback.message.edit_reply_markup(reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("ex_show_answer:"))
async def cb_show_answer(callback: CallbackQuery):
    """Показывает правильный ответ."""
    exercise_id = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    exercise = _active_exercises.get(user_id)
    if not exercise or exercise.get("exercise_id") != exercise_id:
        await callback.answer("⏰ Упражнение уже неактивно", show_alert=True)
        return

    correct = exercise["correct_answer"]["value"]
    ex_type = exercise["type"]

    await callback.message.edit_text(
        f"📖 <b>Правильный ответ</b>\n\n"
        f"Ответ: <b>{correct}</b>\n\n"
        "Попробуй запомнить! 👇",
        reply_markup=_next_exercise_keyboard(ex_type),
    )
    await callback.answer()


class HasActiveTranslationExercise(BaseFilter):
    """Фильтр: у пользователя активно translation-упражнение."""

    async def __call__(self, message: Message) -> bool:
        exercise = _active_exercises.get(message.from_user.id)
        return exercise is not None and exercise.get("type") == "translation"


@router.message(F.text, ~F.text.startswith("/"), HasActiveTranslationExercise())
async def handle_translation_answer(message: Message):
    """Проверяет текстовый ответ на переводное упражнение.

    Срабатывает только когда у пользователя активно translation-упражнение.
    В остальных случаях сообщение обрабатывает dialogue.handle_text_dialogue.
    """
    user_id = message.from_user.id
    user_answer = message.text.strip()

    exercise = _active_exercises.get(user_id)

    correct = exercise["correct_answer"]["value"]
    case_sensitive = exercise["correct_answer"]["case_sensitive"]

    is_correct = (
        (user_answer == correct)
        if case_sensitive
        else (user_answer.strip().casefold() == correct.strip().casefold())
    )

    _active_exercises.pop(user_id, None)

    if is_correct:
        await message.answer(
            f"✅ <b>Верно!</b> 🎉\n\n"
            f"Твой перевод: {user_answer}\n"
            f"Правильный ответ: {correct}\n\n"
            "Отлично!",
            reply_markup=_next_exercise_keyboard("translation"),
        )
    else:
        await message.answer(
            f"❌ Не совсем так.\n\n"
            f"Твой вариант: {user_answer}\n"
            f"Правильный ответ: <b>{correct}</b>\n\n"
            "Не расстраивайся, практика — ключ к успеху! 💪",
            reply_markup=_next_exercise_keyboard("translation"),
        )


def _next_exercise_keyboard(ex_type: str) -> InlineKeyboardBuilder:
    """Клавиатура для действий после упражнения."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Ещё", callback_data=f"ex_type:{ex_type}")
    builder.button(text="🎯 Меню", callback_data="ex_back_to_menu")
    return builder.as_markup()


@router.callback_query(F.data == "ex_back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery):
    """Возвращает в меню упражнений."""
    user_id = callback.from_user.id
    _active_exercises.pop(user_id, None)

    builder = InlineKeyboardBuilder()
    for ex_type, label in EXERCISE_TYPES.items():
        builder.button(text=label, callback_data=f"ex_type:{ex_type}")
    builder.adjust(1)

    await callback.message.edit_text(
        "🎯 <b>Упражнения</b>\n\nВыбери тип упражнения:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


def _format_exercise_types() -> str:
    """Форматирует список типов упражнений."""
    return "\n".join(
        f"  • {label} — /exercise {ex_type}"
        for ex_type, label in EXERCISE_TYPES.items()
    )
