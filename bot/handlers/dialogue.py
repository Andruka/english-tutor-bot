"""Хендлеры диалога с AI-репетитором."""

import logging
import os
import html
from datetime import date
from aiogram import Router, F
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)
from aiogram.filters import Command

from bot.services.ai_service import (
    AITutor,
    MODES,
    MODE_LABELS,
    MODE_ICONS,
    MODE_FREE_TALK,
    MODE_ROLE_PLAY,
    MODE_GRAMMAR_FOCUS,
    pick_random_scenario,
    pick_random_grammar_topic,
)
from bot.services.voice_service import VoiceService
from bot.services.learning_path_service import build_learning_path, format_learning_path
from bot.db import UserRepository, get_conn
from bot.handlers.start import TOPIC_ALIASES
from bot.admin_api import mark_text_response_tts_skipped
from bot.handlers.common import SKIP_TTS_CALLBACK_PREFIX, post_process_dialogue

router = Router()
logger = logging.getLogger(__name__)

_tutor_sessions: dict[int, AITutor] = {}
_user_topics: dict[int, str] = {}
_user_modes: dict[int, str] = {}
_user_role_scenarios: dict[int, str] = {}
_user_grammar_foci: dict[int, str] = {}

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

    mode = _user_modes.get(user_id, MODE_FREE_TALK)
    scenario = _user_role_scenarios.get(user_id)
    grammar_focus = _user_grammar_foci.get(user_id)

    if existing is None:
        _tutor_sessions[user_id] = AITutor(
            level=level,
            api_key=api_key,
            topic=topic or "introduction",
            mode=mode,
            scenario=scenario,
            grammar_focus=grammar_focus,
        )
    elif existing.level != level or existing.topic != topic or existing.mode != mode:
        _tutor_sessions[user_id] = AITutor(
            level=level,
            api_key=api_key,
            topic=topic or "introduction",
            mode=mode,
            scenario=scenario,
            grammar_focus=grammar_focus,
        )
    return _tutor_sessions[user_id]


async def _check_limit(message: Message, user, conn=None) -> bool:
    """Проверяет дневной лимит. Возвращает True, если лимит не превышен."""
    today = date.today()
    # Если день сменился — сбрасываем счётчик, чтобы не блокировать
    if user.last_dialogue_date != today:
        user.dialogues_today = 0
        if conn:
            from bot.db import UserRepository
            await UserRepository(conn).reset_user_dialogues(user.user_id)
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

    if not await _check_limit(message, user, conn=conn):
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
        mode = _user_modes.get(user_id)
        await post_process_dialogue(
            message, user_id, text, result, conn, topic=topic, mode=mode
        )
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

    if not await _check_limit(message, user, conn=conn):
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

        escaped_text = html.escape(text)
        pronunciation_block = ""
        try:
            from bot.db import PronunciationFeedback, PronunciationFeedbackRepository
            from bot.services.pronunciation_service import (
                PronunciationService,
                format_pronunciation_feedback,
            )

            assessment = await PronunciationService().score_transcript(text, user.level)
            if assessment is not None:
                await PronunciationFeedbackRepository(conn).create(
                    PronunciationFeedback(
                        user_id=user_id,
                        transcript=text,
                        score=assessment.score,
                        problem_sounds=assessment.problem_sounds,
                        tips=assessment.tips,
                    )
                )
                pronunciation_block = format_pronunciation_feedback(assessment)
        except Exception as e:
            logger.warning(f"Pronunciation feedback skipped for user {user_id}: {e}")

        # Показываем распознанный текст
        await status_msg.edit_text(
            f"🎤 <i>Распознано:</i> '{escaped_text}'\n\n⏳ Отвечаю... (3/4)"
        )

        # Этап 3: AI ответ
        await message.bot.send_chat_action(chat_id=user_id, action="typing")
        topic = _user_topics.get(user_id, "introduction")
        tutor = get_or_create_tutor(user_id, user.level, topic)
        result = await tutor.chat(text)

        # Добавляем распознанный текст и pronunciation feedback префиксом к ответу
        prefix = f"🎤 <i>Распознано:</i> {escaped_text}"
        if pronunciation_block:
            prefix += f"\n\n{pronunciation_block}"
        result["reply"] = f"{prefix}\n\n{result['reply']}"

        # Этап 4: пост-обработка (сохранение + ачивки + TTS)
        await status_msg.edit_text(
            f"🎤 <i>Распознано:</i> '{escaped_text}'\n\n⏳ Готовлю ответ... (4/4)"
        )
        await post_process_dialogue(
            message,
            user_id,
            text,
            result,
            conn,
            topic=topic,
            mode=_user_modes.get(user_id),
        )

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


@router.message(Command("lesson"))
async def cmd_lesson(message: Message):
    """Creates a micro-lesson or checks the current lesson answer."""
    from bot.db import MicroLessonRepository
    from bot.services.micro_lesson_service import (
        check_lesson_attempt,
        format_attempt_result,
        format_micro_lesson,
        generate_micro_lesson,
    )

    user_id = message.from_user.id
    conn = await get_conn()
    user = await UserRepository(conn).get(user_id)
    if user is None:
        await message.answer("Пожалуйста, начни с команды /start")
        return

    text = message.text or ""
    answer = text.partition(" ")[2].strip()
    lesson_repo = MicroLessonRepository(conn)

    if answer:
        active_lesson = await lesson_repo.get_latest_active(user_id)
        if active_lesson is None:
            active_lesson = await generate_micro_lesson(user_id, user.level, conn)
            await message.answer(format_micro_lesson(active_lesson))
            return
        attempt = await check_lesson_attempt(
            user_id, active_lesson.lesson_id, answer, conn
        )
        await message.answer(format_attempt_result(attempt))
        return

    lesson = await generate_micro_lesson(user_id, user.level, conn)
    await message.answer(format_micro_lesson(lesson))


@router.message(Command("learnpath"))
async def cmd_learnpath(message: Message):
    """Показывает персональную рекомендацию следующего урока."""
    user_id = message.from_user.id
    conn = await get_conn()
    repo = UserRepository(conn)
    user = await repo.get(user_id)

    if user is None:
        await message.answer("Пожалуйста, начни с команды /start")
        return

    recommendation = await build_learning_path(user_id, conn)
    await message.answer(format_learning_path(recommendation))


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Прогресс-панель: уровень, streak, навыки, достижения, слова."""
    user_id = message.from_user.id
    conn = await get_conn()
    repo = UserRepository(conn)
    user = await repo.get(user_id)

    if user is None:
        await message.answer("Пожалуйста, начни с команды /start")
        return

    from bot.services.progress_service import (
        get_progress_dashboard,
        RANK_THRESHOLDS,
    )
    from bot.db import DictionaryRepository

    dashboard = await get_progress_dashboard(user_id)
    dict_repo = DictionaryRepository(conn)
    word_count = await dict_repo.count(user_id)

    # Средняя оценка и динамика за 7 дней
    from bot.db import DialogueRepository

    dialogue_repo = DialogueRepository(conn)
    weekly = await dialogue_repo.get_weekly_stats(user_id)
    total_dialogue_count = dashboard["total_dialogues"]
    avg_rating_line = ""
    weekly_line = ""
    if total_dialogue_count > 0:
        # Средняя оценка за всё время
        from datetime import date, datetime, timedelta

        cursor = await conn.execute(
            "SELECT AVG(rating) FROM dialogues WHERE user_id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        avg_all = round(row[0], 1) if row and row[0] else 0.0
        avg_rating_line = f"⭐ <b>Средняя оценка</b>: {avg_all}/5  |  "
    if weekly["count"] > 0:
        weekly_line = (
            f"📈 <b>За 7 дней</b>: {weekly['count']} диалогов"
            f"{f', ср. оценка {weekly['avg_rating']}/5' if weekly['avg_rating'] else ''}"
        )

    total_xp = sum(b["points"] for b in dashboard["skill_tree"])
    rank = dashboard["rank"]

    # Прогресс-бар до следующего ранга
    next_rank_name = None
    next_rank_threshold = None
    for threshold, rname in reversed(RANK_THRESHOLDS):
        if total_xp < threshold:
            next_rank_name = rname
            next_rank_threshold = threshold
            break

    # Визуальный прогресс-бар
    bar_full = 20
    if next_rank_threshold:
        prev_threshold = 0
        for t, _ in reversed(RANK_THRESHOLDS):
            if t < next_rank_threshold:
                prev_threshold = t
                break
        range_xp = next_rank_threshold - prev_threshold
        current_in_range = total_xp - prev_threshold
        filled = min(bar_full, int(current_in_range / range_xp * bar_full))
        bar = "█" * filled + "░" * (bar_full - filled)
        xp_line = f"  {bar}  {total_xp} / {next_rank_threshold} XP → {next_rank_name}"
    else:
        xp_line = f"  ✨ Максимальный ранг ({rank}) — {total_xp} XP"

    # Ветки навыков (кратко)
    skill_lines = []
    for b in dashboard["skill_tree"]:
        lvl = b["level"]
        pt = b["points"]
        skill_lines.append(f"  {b['icon']}<b>{b['name']}</b>  ур.{lvl} ({pt} XP)")

    # Weekly challenge
    wc = dashboard["weekly_challenge"]
    if wc and not wc.get("completed"):
        wc_bar = "█" * wc.get("progress", 0) + "░" * (
            wc.get("goal", 7) - wc.get("progress", 0)
        )
        wc_line = f"  🎯 Weekly: {wc_bar}  {wc.get('progress', 0)}/{wc.get('goal', 7)}"
    elif wc and wc.get("completed"):
        wc_line = "  🎯 Weekly: ✅ выполнен! 🎉"
    else:
        wc_line = ""

    text = (
        f"📊 <b>Прогресс-панель</b>\n\n"
        f"🏅 <b>{rank}</b>\n"
        f"{xp_line}\n\n"
        f"🔥 <b>Streak</b>: {user.streak} дн.  |  💬 <b>Диалогов</b>: {total_dialogue_count}  |  "
        f"📚 <b>Слов</b>: {word_count}  |  {avg_rating_line}\n"
    )
    if weekly_line:
        text += f"{weekly_line}\n\n"
    else:
        text += "\n"
    text += (
        f"🌳 <b>Навыки</b>\n" + "\n".join(skill_lines) + "\n\n"
        f"🏆 <b>Достижения</b>: {dashboard['achievement_count']} / 11\n"
    )
    if wc_line:
        text += wc_line + "\n"
    text += (
        f"\nПодписка: {'✅' if dashboard['subscription'] else '❌'}\n\n"
        f"<i>Подробнее: /skills · /achievements · /challenge</i>"
    )
    await message.answer(text)


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


@router.message(Command("skills"))
async def cmd_skills(message: Message):
    """Показывает дерево навыков: 5 веток, очки и уровни."""
    user_id = message.from_user.id
    conn = await get_conn()
    user = await UserRepository(conn).get(user_id)
    if user is None:
        await message.answer("Пожалуйста, начни с команды /start")
        return

    from bot.services.progress_service import get_progress_dashboard

    dashboard = await get_progress_dashboard(user_id)
    lines = ["🌳 <b>Дерево навыков</b>", ""]
    for branch in dashboard["skill_tree"]:
        lines.append(
            f"{branch['icon']} <b>{branch['name']}</b> — "
            f"ур. {branch['level']} · {branch['points']} XP "
            f"(до след.: {branch['points_to_next_level']})"
        )
        lines.append(f"  <i>{branch['desc']}</i>")
    lines.append("")
    lines.append(f"🏅 Ранг: <b>{dashboard['rank']}</b>")
    await message.answer("\n".join(lines))


@router.message(Command("rank"))
async def cmd_rank(message: Message):
    """Показывает текущий ранг пользователя."""
    user_id = message.from_user.id
    conn = await get_conn()
    user = await UserRepository(conn).get(user_id)
    if user is None:
        await message.answer("Пожалуйста, начни с команды /start")
        return

    from bot.services.progress_service import RANK_THRESHOLDS, get_progress_dashboard

    dashboard = await get_progress_dashboard(user_id)
    total_points = sum(branch["points"] for branch in dashboard["skill_tree"])
    next_rank = None
    for threshold, rank in reversed(RANK_THRESHOLDS):
        if total_points < threshold:
            next_rank = (rank, threshold)
            break

    text = (
        f"🏅 <b>Твой ранг</b>\n\n"
        f"Сейчас: <b>{dashboard['rank']}</b>\n"
        f"Всего XP: <b>{total_points}</b>\n"
    )
    if next_rank:
        rank_name, threshold = next_rank
        text += f"До {rank_name}: <b>{threshold - total_points}</b> XP"
    else:
        text += "Максимальный ранг достигнут — Platinum! ✨"
    await message.answer(text)


@router.message(Command("challenge"))
async def cmd_challenge(message: Message):
    """Показывает прогресс weekly challenge."""
    user_id = message.from_user.id
    conn = await get_conn()
    user = await UserRepository(conn).get(user_id)
    if user is None:
        await message.answer("Пожалуйста, начни с команды /start")
        return

    from bot.services.progress_service import (
        ACHIEVEMENT_DEFINITIONS,
        get_progress_dashboard,
    )

    dashboard = await get_progress_dashboard(user_id)
    challenge = dashboard["weekly_challenge"]
    reward = ACHIEVEMENT_DEFINITIONS.get(challenge["reward_achievement_id"], {})
    status = "✅ выполнен" if challenge["completed"] else "в процессе"
    await message.answer(
        f"🎯 <b>Weekly Challenge</b>\n\n"
        f"Неделя: <b>{challenge['week_id']}</b>\n"
        f"Прогресс: <b>{challenge['progress']}/{challenge['goal']}</b> практик\n"
        f"Статус: <b>{status}</b>\n"
        f"Награда: <b>{reward.get('name', challenge['reward_achievement_id'])}</b>"
    )


def _mode_keyboard(current_mode: str) -> InlineKeyboardMarkup:
    """Клавиатура выбора режима диалога."""
    buttons = []
    for m in MODES:
        icon = MODE_ICONS[m]
        label = MODE_LABELS[m]
        checked = " ✅" if m == current_mode else ""
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{icon}{label}{checked}", callback_data=f"mode_set:{m}"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("mode"))
async def cmd_mode(message: Message):
    user_id = message.from_user.id
    current_mode = _user_modes.get(user_id, MODE_FREE_TALK)
    mode_label = MODE_LABELS[current_mode]
    await message.answer(
        f"🎯 <b>Режим диалога</b>\n\n"
        f"Текущий: {MODE_ICONS[current_mode]} <b>{mode_label}</b>\n\n"
        f"Выбери режим:",
        reply_markup=_mode_keyboard(current_mode),
    )


@router.callback_query(F.data.startswith("mode_set:"))
async def handle_mode_callback(callback):
    user_id = callback.from_user.id
    mode = callback.data.split(":", 1)[1]

    if mode not in MODES:
        await callback.answer("Неизвестный режим.", show_alert=True)
        return

    _user_modes[user_id] = mode

    # Для role play — выбираем случайный сценарий
    scenario_key = None
    if mode == MODE_ROLE_PLAY:
        scenario_key, scenario_desc = pick_random_scenario()
        _user_role_scenarios[user_id] = scenario_desc
    elif mode == MODE_GRAMMAR_FOCUS:
        gf = pick_random_grammar_topic()
        _user_grammar_foci[user_id] = gf

    # Переключаем режим в существующем тюторе, если есть
    tutor = _tutor_sessions.get(user_id)
    if tutor is not None:
        scenario = _user_role_scenarios.get(user_id)
        grammar_focus = _user_grammar_foci.get(user_id)
        tutor.set_mode(mode=mode, scenario=scenario, grammar_focus=grammar_focus)

    descriptions = {
        MODE_FREE_TALK: (
            "🗣 Свободная беседа — разговаривай на любые темы, "
            "AI поддерживает диалог и мягко исправляет ошибки. "
            "Фокус на беглость речи."
        ),
        MODE_ROLE_PLAY: (
            "🎭 Ролевая игра — ты и AI разыгрываете сценку "
            "(ресторан, магазин, собеседование). Учись через реальные ситуации!"
        ),
        MODE_GRAMMAR_FOCUS: (
            "📚 Грамматика — AI тренирует конкретную грамматическую тему. "
            "Подробный разбор каждой ошибки."
        ),
    }

    extra = ""
    if mode == MODE_ROLE_PLAY and scenario_key:
        extra = f"\n🎬 Сценарий: <b>{scenario_key}</b>"
    elif mode == MODE_GRAMMAR_FOCUS:
        gf = _user_grammar_foci.get(user_id, "")
        extra = f"\n📖 Тема: <b>{gf}</b>"

    mode_icon = MODE_ICONS[mode]
    await callback.message.edit_text(
        f"{mode_icon} <b>Режим переключён!</b>\n\n"
        f"{descriptions[mode]}"
        f"{extra}\n\n"
        f"Давай начнём диалог — напиши что-нибудь 👇"
    )
    await callback.answer()
