"""Хендлеры библиотеки текстов для чтения.

Команды:
  /texts — главное меню библиотеки
  /text <id> — открыть текст по ID
  /bookmarks — список закладок
"""

import logging
from typing import Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.db import UserRepository, get_conn, Text
from bot.services.text_library_service import (
    CATEGORIES,
    CATEGORY_LABELS,
    TextLibraryService,
    get_category_label,
    get_level_label,
    seed_texts,
)

router = Router()
logger = logging.getLogger(__name__)

# Хранилище позиций чтения: {user_id: {"text_id": ..., "paragraph": 0}}
_reading_positions: dict[int, dict] = {}

# Количество вопросов на текст
QUESTIONS_COUNT = 3


# ── Вспомогательные функции ──────────────────────────────────────────────


def _escape_md(text: str) -> str:
    """Экранирует спецсимволы MarkdownV2."""
    import re
    return re.sub(r"([_*[\]()~`>#+\-=|{}.!])", r"\\\1", text)


def _word_count_label(wc: int) -> str:
    """Форматирует количество слов."""
    return f"{wc} слов" if wc else ""


def _progress_icon(progress) -> str:
    """Иконка статуса прогресса."""
    if progress is None:
        return "📄"
    if progress.status == "completed":
        return "✅"
    return "📖"


def _build_text_summary(text: Text, progress=None) -> str:
    """Собирает однострочное описание текста."""
    icon = _progress_icon(progress)
    words = _word_count_label(text.word_count)
    level = get_level_label(text.level).split(" — ")[0]
    cat = get_category_label(text.category)
    return f"{icon} {text.title} ({level}, {cat}, {words})"


# ── Главное меню библиотеки ──────────────────────────────────────────────

@router.message(Command("texts"))
async def cmd_texts(message: Message):
    """Показывает главное меню библиотеки текстов."""
    await _show_library_menu(message)


async def _show_library_menu(message: Message, edit: bool = False):
    """Главное меню библиотеки: по уровню, по категории, прогресс."""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎯 По уровню", callback_data="tl_level"),
                InlineKeyboardButton(text="📂 По категории", callback_data="tl_category"),
            ],
            [
                InlineKeyboardButton(text="📊 Мой прогресс", callback_data="tl_progress"),
            ],
            [
                InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu_main"),
            ],
        ]
    )
    text = "📚 <b>Библиотека текстов</b>\n\nЧитай английские тексты, учи слова и проверяй понимание.\nВыбери способ поиска:"
    if edit:
        await message.edit_text(text, reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb)


# ── Выбор уровня ─────────────────────────────────────────────────────────

async def _show_level_menu(message: Message, service: TextLibraryService, edit: bool = False):
    """Показывает кнопки уровней с количеством текстов."""
    levels = await service.get_levels_with_counts()
    buttons = []
    for item in levels:
        label = f"{item['level']} ({item['count']})"
        buttons.append(
            [InlineKeyboardButton(text=label, callback_data=f"tl_lvl_{item['level']}")]
        )
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="tl_menu")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if edit:
        await message.edit_text("🎯 <b>Выбери уровень:</b>", reply_markup=kb)
    else:
        await message.answer("🎯 <b>Выбери уровень:</b>", reply_markup=kb)


# ── Выбор категории ──────────────────────────────────────────────────────

async def _show_category_menu(message: Message, service: TextLibraryService, edit: bool = False):
    """Показывает кнопки категорий."""
    categories = await service.get_categories_with_counts()
    buttons = []
    for item in categories:
        label = f"{item['label']} ({item['count']})"
        buttons.append(
            [InlineKeyboardButton(text=label, callback_data=f"tl_cat_{item['category']}")]
        )
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="tl_menu")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if edit:
        await message.edit_text("📂 <b>Выбери категорию:</b>", reply_markup=kb)
    else:
        await message.answer("📂 <b>Выбери категорию:</b>", reply_markup=kb)


# ── Список текстов ───────────────────────────────────────────────────────

async def _show_text_list(
    message: Message,
    service: TextLibraryService,
    user_id: int,
    level: str = "",
    category: str = "",
    edit: bool = False,
):
    """Показывает список текстов с прогрессом."""
    texts = await service.list_texts(level=level, category=category)
    progress_map = await service.get_progress_for_texts(user_id, texts)

    if not texts:
        await message.edit_text("😕 Нет текстов для этого выбора.", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="tl_menu")]]
        ))
        return

    lines = []
    if level:
        lines.append(f"🎯 <b>{get_level_label(level)}</b>\n")
    elif category:
        lines.append(f"📂 <b>{get_category_label(category)}</b>\n")

    buttons = []
    for text in texts:
        progress = progress_map.get(text.id)
        icon = _progress_icon(progress)
        words = _word_count_label(text.word_count)
        lines.append(f"{icon} <b>{text.title}</b> — {words}")
        buttons.append(
            [InlineKeyboardButton(text=f"{icon} {text.title}", callback_data=f"tl_read_{text.id}")]
        )

    lines.append("\n<i>Нажми на текст, чтобы начать чтение</i>")
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="tl_menu")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    if edit:
        await message.edit_text("\n".join(lines), reply_markup=kb)
    else:
        await message.answer("\n".join(lines), reply_markup=kb)


# ── Чтение текста (с пагинацией по абзацам) ──────────────────────────────

async def _show_text_paragraph(
    message: Message,
    service: TextLibraryService,
    text: Text,
    user_id: int,
    paragraph: int = 0,
    edit: bool = False,
):
    """Показывает один абзац текста с кнопками навигации."""
    paragraphs = service.split_paragraphs(text.content)
    total = len(paragraphs)

    if paragraph >= total:
        paragraph = total - 1
    if paragraph < 0:
        paragraph = 0

    current = paragraphs[paragraph]
    progress = f"📄 {paragraph + 1}/{total}"

    lines = [
        f"📖 <b>{text.title}</b>",
        f"<i>{progress}  •  {get_level_label(text.level).split(' — ')[0]}  •  {_word_count_label(text.word_count)}</i>",
        "",
        current,
    ]

    # Кнопки навигации
    nav_buttons = []
    if paragraph > 0:
        nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data=f"tl_par_{paragraph - 1}_{text.id}"))
    if paragraph < total - 1:
        nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data=f"tl_par_{paragraph + 1}_{text.id}"))

    action_buttons = [
        [
            InlineKeyboardButton(text="➕ Слово в словарь", callback_data=f"tl_word_{text.id}_{paragraph}"),
            InlineKeyboardButton(text="🔖 Закладка", callback_data=f"tl_bm_{text.id}_{paragraph}"),
        ],
        [
            InlineKeyboardButton(text="📝 Вопросы", callback_data=f"tl_quiz_{text.id}"),
            InlineKeyboardButton(text="✅ Прочитано", callback_data=f"tl_done_{text.id}"),
        ],
    ]

    row1 = [nav_buttons] if nav_buttons else []
    kb_rows = row1 + action_buttons + [
        [InlineKeyboardButton(text="◀️ К списку", callback_data=f"tl_back_{text.id}")],
        [InlineKeyboardButton(text="🏠 Библиотека", callback_data="tl_menu")],
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

    # Отмечаем начало чтения
    await service.start_reading(user_id, text.id)
    # Сохраняем позицию
    _reading_positions[user_id] = {"text_id": text.id, "paragraph": paragraph}

    if edit:
        await message.edit_text("\n".join(lines), reply_markup=kb)
    else:
        await message.answer("\n".join(lines), reply_markup=kb)


# ── Вопросы на понимание ─────────────────────────────────────────────────

async def _show_quiz(
    message: Message,
    service: TextLibraryService,
    text: Text,
    user_id: int,
    edit: bool = False,
):
    """Генерирует и показывает вопросы по тексту."""
    await message.edit_text("🤔 Генерирую вопросы по тексту...")
    questions = await service.generate_questions(
        text.title, text.content, text.level, QUESTIONS_COUNT
    )

    if not questions:
        await message.edit_text(
            "😕 Не удалось сгенерировать вопросы. Попробуй позже.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ К тексту", callback_data=f"tl_par_0_{text.id}")]
                ]
            ),
        )
        return

    # Сохраняем вопросы в состоянии
    _reading_positions[user_id] = {
        "text_id": text.id,
        "questions": questions,
        "q_index": 0,
        "correct": 0,
    }
    await _show_question(message, user_id, edit=True)


async def _show_question(message: Message, user_id: int, edit: bool = False):
    """Показывает один вопрос викторины."""
    state = _reading_positions.get(user_id, {})
    questions = state.get("questions", [])
    q_idx = state.get("q_index", 0)

    if q_idx >= len(questions):
        # Викторина завершена
        total = len(questions)
        correct = state.get("correct", 0)
        text_id = state.get("text_id")
        lines = [
            "🎉 <b>Викторина завершена!</b>",
            f"Правильных ответов: {correct}/{total}",
        ]
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="◀️ К тексту", callback_data=f"tl_par_0_{text_id}")],
                [InlineKeyboardButton(text="🏠 Библиотека", callback_data="tl_menu")],
            ]
        )
        await message.edit_text("\n".join(lines), reply_markup=kb)
        return

    question = questions[q_idx]
    lines = [
        f"❓ <b>Вопрос {q_idx + 1}/{len(questions)}</b>",
        "",
        question["question"],
    ]

    options = question.get("options", [])
    buttons = []
    for i, opt in enumerate(options):
        buttons.append([
            InlineKeyboardButton(
                text=opt,
                callback_data=f"tl_ans_{q_idx}_{i}_{text_id}_{question['answer']}",
            )
        ])
    buttons.append([InlineKeyboardButton(text="🏠 Библиотека", callback_data="tl_menu")])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text_id = state.get("text_id", 0)

    # Удаляем старый callback_data с text_id для правильного формирования нажатия на вопрос
    if edit:
        await message.edit_text("\n".join(lines), reply_markup=kb)
    else:
        await message.answer("\n".join(lines), reply_markup=kb)


# ── Обработчик callback-запросов ─────────────────────────────────────────

def _get_text_id_from_data(data: str) -> int:
    """Извлекает text_id из callback_data."""
    parts = data.split("_")
    for i, p in enumerate(parts):
        if p.isdigit():
            return int(p)
    return 0


@router.callback_query(lambda c: c.data.startswith("tl_"))
async def text_library_callback(callback: CallbackQuery):
    """Обработчик всех callback-запросов библиотеки текстов."""
    data = callback.data
    user_id = callback.from_user.id
    await callback.answer()

    service = await TextLibraryService.create()
    try:
        # ── Навигация ──────────────────────────────────────────────
        if data == "tl_menu":
            await _show_library_menu(callback.message, edit=True)

        elif data == "tl_level":
            await _show_level_menu(callback.message, service, edit=True)

        elif data == "tl_category":
            await _show_category_menu(callback.message, service, edit=True)

        elif data == "tl_progress":
            await _show_user_progress(callback, service, user_id)

        # ── Выбор уровня ──────────────────────────────────────────
        elif data.startswith("tl_lvl_"):
            level = data.replace("tl_lvl_", "")
            await _show_text_list(callback.message, service, user_id, level=level, edit=True)

        # ── Выбор категории ───────────────────────────────────────
        elif data.startswith("tl_cat_"):
            category = data.replace("tl_cat_", "")
            await _show_text_list(callback.message, service, user_id, category=category, edit=True)

        # ── Чтение текста ─────────────────────────────────────────
        elif data.startswith("tl_read_"):
            text_id = int(data.replace("tl_read_", ""))
            text = await service.get_text(text_id)
            if not text:
                await callback.message.edit_text("😕 Текст не найден.")
                return
            await _show_text_paragraph(callback.message, service, text, user_id, edit=True)

        # ── Навигация по абзацам ──────────────────────────────────
        elif data.startswith("tl_par_"):
            parts = data.split("_")
            paragraph = int(parts[2])
            text_id = int(parts[3])
            text = await service.get_text(text_id)
            if not text:
                await callback.message.edit_text("😕 Текст не найден.")
                return
            await _show_text_paragraph(callback.message, service, text, user_id, paragraph=paragraph, edit=True)

        # ── Назад к списку ─────────────────────────────────────────
        elif data.startswith("tl_back_"):
            text_id = int(data.replace("tl_back_", ""))
            text = await service.get_text(text_id)
            if text:
                await _show_text_list(callback.message, service, user_id, level=text.level, edit=True)

        # ── Добавить слово в словарь ──────────────────────────────
        elif data.startswith("tl_word_"):
            parts = data.split("_")
            text_id = int(parts[2])
            await service.add_word(user_id, text_id)
            await callback.message.edit_text(
                "✅ Слово добавлено к прогрессу! Используй /dict для просмотра словаря.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="◀️ К тексту", callback_data=f"tl_par_0_{text_id}")],
                    ]
                ),
            )

        # ── Закладка ──────────────────────────────────────────────
        elif data.startswith("tl_bm_"):
            parts = data.split("_")
            text_id = int(parts[2])
            paragraph = int(parts[3])
            await service.add_bookmark(user_id, text_id, paragraph)
            await callback.message.edit_text(
                "🔖 <b>Закладка сохранена!</b>",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="◀️ К тексту", callback_data=f"tl_par_{paragraph}_{text_id}")],
                        [InlineKeyboardButton(text="📋 Мои закладки", callback_data="tl_bookmarks")],
                    ]
                ),
            )

        # ── Викторина ─────────────────────────────────────────────
        elif data.startswith("tl_quiz_"):
            text_id = int(data.replace("tl_quiz_", ""))
            text = await service.get_text(text_id)
            if not text:
                await callback.message.edit_text("😕 Текст не найден.")
                return
            await _show_quiz(callback.message, service, text, user_id, edit=True)

        # ── Ответ на вопрос ───────────────────────────────────────
        elif data.startswith("tl_ans_"):
            parts = data.split("_")
            q_idx = int(parts[2])
            chosen = int(parts[3])
            text_id = int(parts[4])
            correct = int(parts[5])

            state = _reading_positions.get(user_id, {})
            if chosen == correct:
                state["correct"] = state.get("correct", 0) + 1
                feedback = "✅ <b>Верно!</b>"
            else:
                options = state.get("questions", [])[q_idx].get("options", [])
                correct_text = options[correct] if correct < len(options) else "?"
                feedback = f"❌ Неверно. Правильный ответ: <b>{correct_text}</b>"

            state["q_index"] = state.get("q_index", 0) + 1
            _reading_positions[user_id] = state

            await callback.message.edit_text(
                feedback,
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="▶️ Далее", callback_data="tl_next_q")]
                    ]
                ),
            )

        # ── Следующий вопрос ──────────────────────────────────────
        elif data == "tl_next_q":
            await _show_question(callback.message, user_id, edit=True)

        # ── Завершить текст ───────────────────────────────────────
        elif data.startswith("tl_done_"):
            text_id = int(data.replace("tl_done_", ""))
            await service.complete_reading(user_id, text_id)
            await callback.message.edit_text(
                "✅ <b>Текст завершён!</b> Молодец! 🎉",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="📊 Мой прогресс", callback_data="tl_progress")],
                        [InlineKeyboardButton(text="🏠 Библиотека", callback_data="tl_menu")],
                    ]
                ),
            )

        # ── Закладки ──────────────────────────────────────────────
        elif data == "tl_bookmarks":
            bookmarks = await service.list_bookmarks(user_id)
            if not bookmarks:
                await callback.message.edit_text(
                    "🔖 У тебя пока нет закладок.\n\nЧитай тексты и ставь 🔖 Закладку, чтобы вернуться позже!",
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [InlineKeyboardButton(text="🏠 Библиотека", callback_data="tl_menu")],
                        ]
                    ),
                )
                return

            lines = ["🔖 <b>Мои закладки</b>\n"]
            buttons = []
            for bm in bookmarks:
                text_obj = await service.get_text(bm.text_id)
                title = text_obj.title if text_obj else f"#{bm.text_id}"
                lines.append(f"• <b>{title}</b> — абзац {bm.paragraph_index + 1}")
                buttons.append([
                    InlineKeyboardButton(
                        text=f"📖 {title} (абз.{bm.paragraph_index + 1})",
                        callback_data=f"tl_par_{bm.paragraph_index}_{bm.text_id}",
                    )
                ])
            buttons.append([InlineKeyboardButton(text="🏠 Библиотека", callback_data="tl_menu")])

            await callback.message.edit_text(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            )

        else:
            await callback.message.edit_text("😕 Неизвестная команда.")

    finally:
        await service.close()


# ── Прогресс пользователя ──────────────────────────────────────────────

async def _show_user_progress(callback: CallbackQuery, service: TextLibraryService, user_id: int):
    """Показывает статистику чтения."""
    stats = await service.get_progress_stats(user_id)
    text = (
        "📊 <b>Мой прогресс чтения</b>\n\n"
        f"📚 Начато текстов: <b>{stats['total_started']}</b>\n"
        f"✅ Завершено: <b>{stats['completed']}</b>\n"
        f"📝 Слов добавлено: <b>{stats['words_learned']}</b>\n\n"
        f"Продолжай читать — каждая минута практики улучшает твой английский! 💪"
    )
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Библиотека", callback_data="tl_menu")],
            ]
        ),
    )


# ── Команда /bookmarks ──────────────────────────────────────────────────

@router.message(Command("bookmarks"))
async def cmd_bookmarks(message: Message):
    """Показывает закладки пользователя."""
    service = await TextLibraryService.create()
    try:
        bookmarks = await service.list_bookmarks(message.from_user.id)
        if not bookmarks:
            await message.answer(
                "🔖 У тебя пока нет закладок.\n\n"
                "Читай тексты через /texts и ставь 🔖 Закладку, чтобы вернуться позже!"
            )
            return

        lines = ["🔖 <b>Мои закладки</b>\n"]
        buttons = []
        for bm in bookmarks:
            text_obj = await service.get_text(bm.text_id)
            title = text_obj.title if text_obj else f"Текст #{bm.text_id}"
            lines.append(f"• <b>{title}</b> — абзац {bm.paragraph_index + 1}")
            buttons.append([
                InlineKeyboardButton(
                    text=f"📖 {title} (абз.{bm.paragraph_index + 1})",
                    callback_data=f"tl_par_{bm.paragraph_index}_{bm.text_id}",
                )
            ])
        buttons.append([InlineKeyboardButton(text="🏠 Библиотека", callback_data="tl_menu")])

        await message.answer(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    finally:
        await service.close()