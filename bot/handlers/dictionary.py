"""Хендлеры SRS-словаря: добавление, повторение, статистика, экспорт."""

import csv
import io
import json
import logging
from dataclasses import asdict
from typing import Any

from aiogram import Router, F
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.db import get_conn, DictionaryRepository
from bot.services.progress_service import SkillProgressRepository

router = Router()
logger = logging.getLogger(__name__)


@router.message(Command("dict"))
async def cmd_dict(message: Message):
    """Показывает слова для повторения и статистику."""
    user_id = message.from_user.id
    conn = await get_conn()
    repo = DictionaryRepository(conn)

    total = await repo.count(user_id)
    due = await repo.count_due(user_id)
    words = await repo.get_due_words(user_id)

    if not words:
        await message.answer(
            f"📖 <b>Твой словарь</b>\n\n"
            f"Всего слов: {total}\n"
            f"На повторении сегодня: 0 🎉\n\n"
            f"Новые слова добавляются автоматически из диалогов с AI!\n"
            f"Или добавь вручную: /add <слово> = <перевод>"
        )
        return

    builder = InlineKeyboardBuilder()
    for w in words[:5]:  # Показываем до 5 слов за раз
        builder.button(
            text=f"{w.word} — {w.translation}",
            callback_data=f"dict_review:{w.word_id}",
        )
    builder.adjust(1)

    await message.answer(
        f"📖 <b>Слова на повторение</b>\n\n"
        f"Сегодня: {due} слов • Всего: {total}\n\n"
        f"Нажми на слово, чтобы начать повторение 👇",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.startswith("dict_review:"))
async def cb_review_word(callback: CallbackQuery):
    """Показывает слово для повторения с кнопками."""
    word_id = int(callback.data.split(":")[1])
    conn = await get_conn()
    repo = DictionaryRepository(conn)
    word = await repo.get_word_by_id(word_id)

    if not word:
        await callback.answer("Слово не найдено", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Знаю", callback_data=f"dict_known:{word_id}")
    builder.button(text="🔁 Повторить", callback_data=f"dict_hard:{word_id}")
    builder.button(text="❌ Забыл", callback_data=f"dict_forgot:{word_id}")
    builder.button(text="🗑 Удалить", callback_data=f"dict_delete:{word_id}")
    builder.adjust(2)

    context_line = f"\n📝 <i>{word.context}</i>" if word.context else ""

    await callback.message.edit_text(
        f"📖 <b>{word.word}</b>\n"
        f"🔤 {word.translation}{context_line}\n\n"
        f"Уровень: {word.level} • Повторений: {word.repetitions}\n"
        f"Интервал: {word.interval_days} дн.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dict_known:"))
async def cb_known(callback: CallbackQuery):
    word_id = int(callback.data.split(":")[1])
    conn = await get_conn()
    repo = DictionaryRepository(conn)
    await repo.mark_reviewed(word_id, quality=3)
    # +2 XP за успешное повторение
    await SkillProgressRepository(conn).award_points(callback.from_user.id, "vocabulary", 2)
    await callback.answer("✅ Отлично! Слово запомнено. (+2 XP)")
    await _show_next_or_done(callback, conn, repo)


@router.callback_query(F.data.startswith("dict_hard:"))
async def cb_hard(callback: CallbackQuery):
    word_id = int(callback.data.split(":")[1])
    conn = await get_conn()
    repo = DictionaryRepository(conn)
    await repo.mark_reviewed(word_id, quality=1)
    # +1 XP за старание
    await SkillProgressRepository(conn).award_points(callback.from_user.id, "vocabulary", 1)
    await callback.answer("🔁 Повторим позже! (+1 XP)")
    await _show_next_or_done(callback, conn, repo)


@router.callback_query(F.data.startswith("dict_forgot:"))
async def cb_forgot(callback: CallbackQuery):
    word_id = int(callback.data.split(":")[1])
    conn = await get_conn()
    repo = DictionaryRepository(conn)
    await repo.mark_reviewed(word_id, quality=0)
    await callback.answer("❌ Ничего страшного! Вернёмся к слову завтра.")
    await _show_next_or_done(callback, conn, repo)


@router.callback_query(F.data.startswith("dict_delete:"))
async def cb_delete(callback: CallbackQuery):
    word_id = int(callback.data.split(":")[1])
    conn = await get_conn()
    repo = DictionaryRepository(conn)
    await repo.remove_word(word_id)
    await callback.answer("🗑 Слово удалено.")
    await _show_next_or_done(callback, conn, repo)


async def _show_next_or_done(callback: CallbackQuery, conn, repo):
    """Показывает следующее слово или сообщение о завершении."""
    user_id = callback.from_user.id
    due = await repo.count_due(user_id)
    total = await repo.count(user_id)
    next_words = await repo.get_due_words(user_id, limit=1)

    if next_words:
        word = next_words[0]
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Знаю", callback_data=f"dict_known:{word.word_id}")
        builder.button(text="🔁 Повторить", callback_data=f"dict_hard:{word.word_id}")
        builder.button(text="❌ Забыл", callback_data=f"dict_forgot:{word.word_id}")
        builder.button(text="🗑 Удалить", callback_data=f"dict_delete:{word.word_id}")
        builder.adjust(2)

        context_line = f"\n📝 <i>{word.context}</i>" if word.context else ""

        await callback.message.edit_text(
            f"📖 <b>{word.word}</b>\n"
            f"🔤 {word.translation}{context_line}\n\n"
            f"Осталось: {due} слов • Всего: {total}",
            reply_markup=builder.as_markup(),
        )
    else:
        await callback.message.edit_text(
            f"🎉 <b>Все слова на сегодня повторены!</b>\n\n"
            f"Всего в словаре: {total} слов.\n"
            f"Новые слова появятся завтра.\n\n"
            f"Продолжай практиковаться с AI-репетитором!"
        )


@router.message(Command("add"))
async def cmd_add_word(message: Message):
    """Добавляет слово вручную: /add word = translation"""
    text = message.text.removeprefix("/add").strip()

    if "=" in text:
        parts = text.split("=", 1)
        word = parts[0].strip()
        translation = parts[1].strip()
    elif text:
        word = text
        translation = "📝 уточни позже"
    else:
        await message.answer(
            "📖 <b>Как добавить слово:</b>\n\n"
            "• <code>/add hello = привет</code>\n"
            "• Слова добавляются автоматически из диалогов с AI!\n"
            "• Для просмотра словаря: /dict"
        )
        return

    conn = await get_conn()
    repo = DictionaryRepository(conn)
    entry = await repo.add_word(message.from_user.id, word, translation)

    if entry:
        # +3 XP за новое слово (ветка vocabulary)
        await SkillProgressRepository(conn).award_points(message.from_user.id, "vocabulary", 3)
        await message.answer(f"✅ <b>{word}</b> — {translation} добавлено в словарь! (+3 XP 🎯)")
    else:
        await message.answer(f"ℹ️ Слово <b>{word}</b> уже есть в словаре.")


def _serialize_entry(entry) -> dict[str, Any]:
    """Преобразует WordEntry в плоский dict для экспорта."""
    data = asdict(entry)
    # next_review может быть None
    return data


@router.message(Command("export_csv"))
async def cmd_export_csv(message: Message):
    """Экспортирует словарь пользователя в CSV."""
    user_id = message.from_user.id
    conn = await get_conn()
    repo = DictionaryRepository(conn)
    entries = await repo.get_all(user_id)

    if not entries:
        await message.answer(
            "📭 В твоём словаре пока нет слов. Добавь их через /add или в диалогах с AI!"
        )
        return

    output = io.StringIO()
    # BOM для корректного отображения кириллицы в Excel
    output.write("\ufeff")
    writer = csv.writer(output, dialect="excel", lineterminator="\r\n")
    writer.writerow(
        [
            "word_id",
            "user_id",
            "word",
            "translation",
            "context",
            "level",
            "next_review",
            "interval_days",
            "repetitions",
            "created_at",
        ]
    )
    for e in entries:
        writer.writerow(
            [
                e.word_id,
                e.user_id,
                e.word,
                e.translation,
                e.context or "",
                e.level,
                e.next_review or "",
                e.interval_days,
                e.repetitions,
                e.created_at or "",
            ]
        )

    csv_bytes = output.getvalue().encode("utf-8")
    file = BufferedInputFile(csv_bytes, filename=f"dictionary_{user_id}.csv")
    await message.answer_document(
        file,
        caption=f"📖 <b>Экспорт словаря</b>\nФормат: CSV • Слов: {len(entries)}",
    )


@router.message(Command("export_json"))
async def cmd_export_json(message: Message):
    """Экспортирует словарь пользователя в JSON."""
    user_id = message.from_user.id
    conn = await get_conn()
    repo = DictionaryRepository(conn)
    entries = await repo.get_all(user_id)

    if not entries:
        await message.answer(
            "📭 В твоём словаре пока нет слов. Добавь их через /add или в диалогах с AI!"
        )
        return

    data = [_serialize_entry(e) for e in entries]
    json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    file = BufferedInputFile(json_bytes, filename=f"dictionary_{user_id}.json")
    await message.answer_document(
        file,
        caption=f"📖 <b>Экспорт словаря</b>\nФормат: JSON • Слов: {len(entries)}",
    )
