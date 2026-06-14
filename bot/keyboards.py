"""Все клавиатуры English Tutor Bot — централизованное определение кнопок."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton


# ──────────────────────────── Главное меню ────────────────────────────

def main_menu_kb(
    subscription_active: bool = False,
    trial_available: bool = False,
    tier: str = "basic",
) -> InlineKeyboardMarkup:
    """Главное меню — контекстно-зависимые кнопки."""
    buttons = [
        [
            InlineKeyboardButton(text="💬 Новый диалог", callback_data="menu_dialogue"),
            InlineKeyboardButton(text="🎤 Голосовое", callback_data="menu_voice"),
        ],
        [
            InlineKeyboardButton(text="📖 Микро-урок", callback_data="menu_lesson"),
            InlineKeyboardButton(text="📚 Словарь", callback_data="menu_dictionary"),
        ],
        [
            InlineKeyboardButton(text="🗺️ Learning Path", callback_data="menu_learnpath"),
            InlineKeyboardButton(text="🔄 Новая сессия", callback_data="menu_new"),
        ],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="menu_stats"),
            InlineKeyboardButton(text="🏆 Достижения", callback_data="menu_achievements"),
        ],
        [
            InlineKeyboardButton(text="🌳 Навыки", callback_data="menu_skills"),
            InlineKeyboardButton(text="🏅 Ранг", callback_data="menu_rank"),
        ],
        [
            InlineKeyboardButton(text="🎯 Weekly Challenge", callback_data="menu_challenge"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="menu_settings"),
        ],
    ]

    # Строка подписки
    sub_row = []
    if subscription_active:
        tier_icon = "💎" if tier == "pro" else "⭐"
        sub_row.append(
            InlineKeyboardButton(
                text=f"{tier_icon} {tier.capitalize()} ✅",
                callback_data="menu_subscribe",
            )
        )
    else:
        sub_row.append(
            InlineKeyboardButton(text="💎 Подписка", callback_data="menu_subscribe")
        )
        if trial_available:
            sub_row.append(
                InlineKeyboardButton(text="🆓 Триал 3 дня", callback_data="menu_trial")
            )

    if sub_row:
        buttons.append(sub_row)

    buttons.append(
        [InlineKeyboardButton(text="❓ Помощь", callback_data="menu_help")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ──────────────────────────── Подписка ────────────────────────────

def subscription_kb(
    has_trial: bool = False,
    in_trial: bool = False,
    subscription_active: bool = False,
) -> InlineKeyboardMarkup:
    """Клавиатура тарифов подписки."""
    buttons = [
        [
            InlineKeyboardButton(
                text="⭐ Premium 199₽/мес", callback_data="sub_monthly"
            ),
            InlineKeyboardButton(
                text="⭐ Premium 1490₽/год", callback_data="sub_yearly"
            ),
        ],
        [
            InlineKeyboardButton(
                text="💎 Pro 499₽/мес", callback_data="sub_pro_monthly"
            ),
            InlineKeyboardButton(
                text="💎 Pro 3990₽/год", callback_data="sub_pro_yearly"
            ),
        ],
    ]

    if has_trial and not in_trial and not subscription_active:
        buttons.append(
            [InlineKeyboardButton(text="🆓 Триал Premium 3 дня", callback_data="sub_trial")]
        )

    buttons.append(
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu_main")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def subscription_status_kb() -> InlineKeyboardMarkup:
    """Кнопки после просмотра статуса подписки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💎 Управление подпиской", callback_data="menu_subscribe"
                )
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu_main")],
        ]
    )


# ──────────────────────────── После диалога ────────────────────────────

def after_dialogue_kb() -> InlineKeyboardMarkup:
    """Кнопки после ответа AI (диалог/голос)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Продолжить", callback_data="menu_dialogue"
                ),
                InlineKeyboardButton(text="🆕 Новая тема", callback_data="menu_topic"),
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Сменить режим", callback_data="menu_mode"
                ),
                InlineKeyboardButton(
                    text="📖 Микро-урок", callback_data="menu_lesson"
                ),
            ],
            [InlineKeyboardButton(text="🏠 Меню", callback_data="menu_main")],
        ]
    )


# ──────────────────────────── Помощь ────────────────────────────

def help_kb() -> InlineKeyboardMarkup:
    """Клавиатура справки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Как начать диалог", callback_data="help_dialogue"
                ),
                InlineKeyboardButton(
                    text="🎤 Голосовые", callback_data="help_voice"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎓 Режимы обучения", callback_data="help_modes"
                ),
                InlineKeyboardButton(
                    text="📖 Упражнения", callback_data="help_exercises"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💎 Тарифы и лимиты", callback_data="menu_subscribe"
                ),
                InlineKeyboardButton(
                    text="⚙️ Настройки", callback_data="menu_settings"
                ),
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu_main")],
        ]
    )


# ──────────────────────────── Настройки ────────────────────────────

def settings_kb() -> InlineKeyboardMarkup:
    """Клавиатура настроек."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎯 Уровень", callback_data="set_level"),
                InlineKeyboardButton(text="📂 Тема", callback_data="set_topic"),
            ],
            [
                InlineKeyboardButton(text="🎭 Режим", callback_data="set_mode"),
                InlineKeyboardButton(text="🔔 Напоминания", callback_data="set_remind"),
            ],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu_main")],
        ]
    )


# ──────────────────────────── Режимы диалога ────────────────────────────

def mode_kb(active_mode: str | None = None) -> InlineKeyboardMarkup:
    """Выбор режима диалога с индикацией активного."""
    modes = [
        ("free_talk", "🗣️", "Свободный разговор"),
        ("role_play", "🎭", "Ролевая игра"),
        ("grammar_focus", "📝", "Грамматика"),
    ]
    buttons = []
    for mode_id, icon, label in modes:
        is_active = mode_id == active_mode
        text = f"{icon} {label} ✅" if is_active else f"{icon} {label}"
        buttons.append(
            [InlineKeyboardButton(text=text, callback_data=f"mode_{mode_id}")]
        )
    buttons.append([InlineKeyboardButton(text="🏠 Меню", callback_data="menu_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ──────────────────────────── Уровни (Reply) ────────────────────────────

LEVELS = ["A1", "A2", "B1", "B2", "C1"]


def level_kb() -> ReplyKeyboardMarkup:
    """Клавиатура выбора уровня (reply, одноразовая)."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=lvl)] for lvl in LEVELS],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


TOPIC_BUTTONS = [
    "Знакомство",
    "Семья",
    "Рутина",
    "Хобби",
    "Путешествия",
    "Еда",
    "Работа",
    "Погода",
]


def topic_kb() -> ReplyKeyboardMarkup:
    """Клавиатура выбора темы (reply, одноразовая)."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t)] for t in TOPIC_BUTTONS],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


TOPIC_ALIASES_V2 = {
    "introduction": ["знакомство", "introduction"],
    "family": ["семья", "family"],
    "daily_routine": ["рутина", "daily routine"],
    "hobbies": ["хобби", "hobbies"],
    "travel": ["путешествия", "travel"],
    "food": ["еда", "food"],
    "work": ["работа", "work"],
    "weather": ["погода", "weather"],
}


# ──────────────────────────── Callback handlers (роутер) ────────────────────────────

# Импортируется в main.py
from aiogram import Router
from aiogram.types import CallbackQuery, Message as AiogramMessage
from aiogram.filters import Command

menu_router = Router()


@menu_router.message(Command("menu"))
async def cmd_menu(message: AiogramMessage):
    """Показывает главное меню с inline-кнопками."""
    from bot.db import UserRepository, get_conn

    conn = await get_conn()
    repo = UserRepository(conn)
    user = await repo.get(message.from_user.id)
    has_trial = user and not user.trial_taken and not user.subscription
    sub_active = user and user.subscription
    tier = user.subscription_tier if user else "basic"
    await message.answer(
        "🎯 <b>Главное меню</b>\n\nВыбери, что хочешь делать:",
        reply_markup=main_menu_kb(
            subscription_active=sub_active,
            trial_available=has_trial,
            tier=tier,
        ),
    )


@menu_router.callback_query(lambda c: c.data.startswith("menu_") or c.data.startswith("sub_") or c.data.startswith("set_") or c.data.startswith("mode_") or c.data.startswith("help_"))
async def menu_callback_handler(callback: CallbackQuery):
    """Общий обработчик навигационных кнопок — делегирует по callback_data."""
    data = callback.data
    await callback.answer()

    # Меню
    if data == "menu_main":
        from bot.db import UserRepository, get_conn
        conn = await get_conn()
        repo = UserRepository(conn)
        user = await repo.get(callback.from_user.id)
        has_trial = user is None or (user is not None and not user.trial_taken and not user.subscription)
        sub_active = user is not None and user.subscription
        tier = user.subscription_tier if user else "basic"
        await callback.message.edit_text(
            "🎯 <b>Главное меню</b>\n\nВыбери, что хочешь делать:",
            reply_markup=main_menu_kb(
                subscription_active=sub_active,
                trial_available=has_trial,
                tier=tier,
            ),
        )
    elif data == "menu_dialogue":
        await callback.message.edit_text(
            "💬 Напиши что-нибудь на английском, и я помогу! ✨"
        )
    elif data == "menu_voice":
        await callback.message.edit_text(
            "🎤 Отправь голосовое сообщение — я распознаю речь и отвечу!"
        )
    elif data == "menu_lesson":
        await callback.message.edit_text("📖 Напиши /lesson для нового микро-урока!")
    elif data == "menu_dictionary":
        await callback.message.edit_text("📚 Напиши /dict — твой словарь!")
    elif data == "menu_learnpath":
        await callback.message.edit_text("🗺️ Напиши /learnpath для персонализированного маршрута!")
    elif data == "menu_new":
        await callback.message.edit_text("🔄 Напиши /new для новой сессии!")
    elif data == "menu_stats":
        await callback.message.edit_text("📊 Напиши /stats для статистики!")
    elif data == "menu_achievements":
        await callback.message.edit_text("🏆 Напиши /achievements!")
    elif data == "menu_skills":
        await callback.message.edit_text("🌳 Напиши /skills для дерева навыков!")
    elif data == "menu_rank":
        await callback.message.edit_text("🏅 Напиши /rank!")
    elif data == "menu_challenge":
        await callback.message.edit_text("🎯 Напиши /challenge!")
    elif data == "menu_help":
        await callback.message.edit_text(
            "❓ <b>Помощь</b>\n\n"
            "🤖 <b>AI-репетитор английского</b>\n\n"
            "<b>Как пользоваться:</b>\n"
            "• Просто напиши что-нибудь на <b>английском</b>\n"
            "• Или отправь <b>голосовое сообщение</b>\n"
            "• Я исправлю ошибки, оценю и дам советы\n\n"
            "<b>Что ещё умею:</b>\n"
            "📖 Микро-уроки по твоим ошибкам — /lesson\n"
            "📚 Персональный словарь с SRS — /dict\n"
            "🗺️ Персональный Learning Path — /learnpath\n"
            "🎭 3 режима диалога (свободный, ролевой, грамматика)\n"
            "🏆 Достижения и ранги за практику\n"
            "🔄 Weekly Challenge каждую неделю\n"
            "🔔 Ежедневные напоминания — /remind\n\n"
            "<b>Лимиты:</b>\n"
            "• Бесплатно: 5 диалогов/день\n"
            "• Premium 199₽/мес: без лимитов\n"
            "• Pro 499₽/мес: Premium + приоритетная AI-модель",
            reply_markup=help_kb(),
        )
    elif data == "menu_subscribe":
        from bot.db import UserRepository, get_conn
        from bot.services.subscription_service import (
            SUBSCRIPTION_PLANS,
            TRIAL_DURATION_DAYS,
        )
        conn = await get_conn()
        repo = UserRepository(conn)
        user = await repo.get(callback.from_user.id)
        has_trial = user is not None and not user.trial_taken
        in_trial = user is not None and user.trial_taken and user.subscription
        sub_active = user is not None and user.subscription

        lines = [
            "<b>💎 Тарифы</b>\n\n",
            "<b>⭐ Premium</b>\n",
            "• Безлимитные диалоги с AI\n",
            "• Исправление ошибок и разбор грамматики\n",
            "• Персональный словарь\n",
            "• Все режимы обучения\n",
            "• Голосовые ответы (TTS)\n",
            "• Микро-уроки и статистика\n",
        ]
        premium_monthly = SUBSCRIPTION_PLANS["monthly"]
        premium_yearly = SUBSCRIPTION_PLANS["yearly"]
        lines.append(f"• {premium_monthly['price_rub']}₽/мес или {premium_yearly['price_rub']}₽/год\n\n")

        lines.append("<b>💎 Pro (всё из Premium +)</b>\n")
        lines.append("• Приоритетная AI-модель (более качественные ответы)\n")
        lines.append("• Детальный анализ произношения\n")
        lines.append("• Расширенная статистика прогресса\n")
        pro_monthly = SUBSCRIPTION_PLANS["pro_monthly"]
        pro_yearly = SUBSCRIPTION_PLANS["pro_yearly"]
        lines.append(f"• {pro_monthly['price_rub']}₽/мес или {pro_yearly['price_rub']}₽/год\n")

        if has_trial and not in_trial and not sub_active:
            lines.append(f"\n🆓 Есть {TRIAL_DURATION_DAYS}-дневный триал Premium!")

        await callback.message.edit_text(
            "".join(lines),
            reply_markup=subscription_kb(
                has_trial=has_trial,
                in_trial=in_trial,
                subscription_active=sub_active,
            ),
        )
    elif data == "menu_trial":
        await callback.message.edit_text(
            "🆓 Напиши /trial для активации 3-дневного триала Premium!"
        )
    elif data == "menu_settings":
        await callback.message.edit_text(
            "⚙️ <b>Настройки</b>\n\nЧто хочешь изменить?",
            reply_markup=settings_kb(),
        )
    elif data == "menu_mode":
        await callback.message.edit_text(
            "🎭 <b>Режим диалога</b>\n\nВыбери режим:",
            reply_markup=mode_kb(),
        )
    elif data == "menu_topic":
        await callback.message.edit_text("📂 Напиши /topic, чтобы выбрать тему!")
    elif data == "menu_stats":
        await callback.message.edit_text("📊 Напиши /stats для статистики!")

    # Подписка
    elif data.startswith("sub_"):
        plan_map = {
            "sub_monthly": "monthly",
            "sub_yearly": "yearly",
            "sub_pro_monthly": "pro_monthly",
            "sub_pro_yearly": "pro_yearly",
            "sub_trial": "trial",
        }
        plan_id = plan_map.get(data)
        if plan_id == "trial":
            await callback.message.edit_text("🆓 Напиши /trial для активации!")
        elif plan_id:
            cmd = f"/pay_{plan_id}"
            from bot.handlers.subscription import _create_invoice
            await _create_invoice(callback.message, plan_id)

    # Настройки
    elif data == "set_level":
        await callback.message.edit_text(
            "🎯 Выбери уровень:",
            reply_markup=level_kb(),
        )
    elif data == "set_topic":
        await callback.message.edit_text(
            "📂 Выбери тему:",
            reply_markup=topic_kb(),
        )
    elif data == "set_mode":
        await callback.message.edit_text(
            "🎭 Выбери режим диалога:",
            reply_markup=mode_kb(),
        )
    elif data == "set_remind":
        await callback.message.edit_text("🔔 Напиши /remind для настройки напоминаний!")

    # Режимы
    elif data.startswith("mode_"):
        from bot.handlers.dialogue import _user_modes
        mode_id = data.replace("mode_", "")
        _user_modes[callback.from_user.id] = mode_id
        from bot.services.ai_service import MODE_LABELS
        label = MODE_LABELS.get(mode_id, mode_id)
        await callback.message.edit_text(
            f"🎭 Режим <b>{label}</b> выбран!\n\nТеперь напиши что-нибудь на английском.",
        )

    # Помощь
    elif data == "help_dialogue":
        await callback.message.edit_text(
            "💬 <b>Как начать диалог</b>\n\n"
            "Просто напиши сообщение на английском!\n"
            "Я отвечу с:\n"
            "• Исправлением ошибок\n"
            "• Оценкой (1-5 ⭐)\n"
            "• Словарными подсказками\n"
            "• Разбором ошибок\n\n"
            "Или используй голосовое сообщение 🎤",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_help")]
                ]
            ),
        )
    elif data == "help_voice":
        await callback.message.edit_text(
            "🎤 <b>Голосовые сообщения</b>\n\n"
            "Отправь голосовое — я:\n"
            "1️⃣ Распознаю речь (Whisper AI)\n"
            "2️⃣ Оценю произношение\n"
            "3️⃣ Отвечу текстом + голосом\n\n"
            "Совет: говори чётко, но не бойся ошибок!",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_help")]
                ]
            ),
        )
    elif data == "help_modes":
        from bot.services.ai_service import MODE_LABELS, MODE_DESCRIPTIONS
        lines = ["🎭 <b>Режимы обучения</b>\n\n"]
        for mode_id, label in MODE_LABELS.items():
            desc = MODE_DESCRIPTIONS.get(mode_id, "")
            lines.append(f"<b>{label}</b>\n{desc}\n")
        await callback.message.edit_text(
            "".join(lines),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_help")]
                ]
            ),
        )
    elif data == "help_exercises":
        await callback.message.edit_text(
            "📖 <b>Упражнения</b>\n\n"
            "📖 <b>/lesson</b> — микро-урок по твоим ошибкам\n"
            "📚 <b>/dict</b> — персональный SRS-словарь\n"
            "    /add слово перевод — добавить слово\n"
            "    /review — повторить слова\n"
            "🗺️ <b>/learnpath</b> — персональный план обучения\n"
            "📖 <b>/exercises</b> — практика перевода\n\n"
            "После диалога я сам добавляю новые слова в словарь!",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="⬅ Назад", callback_data="menu_help")]
                ]
            ),
        )