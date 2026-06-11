"""Точка входа — запуск Telegram-бота."""

import asyncio
import contextlib
import logging
import os
import signal
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.handlers import (
    start,
    dialogue,
    subscription,
    dictionary,
    reminder,
    broadcast,
    exercise,
    digest,
)
from bot.db import (
    close_all_connections,
    init_db,
    get_conn,
    ReminderSettingsRepository,
    UserRepository,
)
from bot.admin_api import create_admin_stats_server_from_env
from bot.services.subscription_service import set_provider_token
from bot.services.subscription_cron import start_subscription_checker
from bot.services.reminder_service import ReminderService
from bot.services.daily_digest_service import DailyDigestSender

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _stop_polling(
    dp: Dispatcher,
    signum: signal.Signals,
    shutdown_requested: asyncio.Event,
) -> None:
    """Останавливает polling по системному сигналу без ненулевого exit code."""
    logger.info("Получен %s — запускаем graceful shutdown", signum.name)
    shutdown_requested.set()
    try:
        await dp.stop_polling()
    except RuntimeError:
        # Сигнал мог прийти до фактического старта polling. В этом случае
        # start_polling увидит shutdown через штатный путь или main завершится.
        logger.info("Polling ещё не запущен; shutdown продолжится без stop_polling()")


def register_shutdown_signal_handlers(dp: Dispatcher) -> asyncio.Event:
    """Регистрирует SIGINT/SIGTERM до входа в основной polling loop."""
    loop = asyncio.get_running_loop()
    shutdown_requested = asyncio.Event()

    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # pragma: no cover - Windows
            loop.add_signal_handler(
                signum,
                lambda signum=signum: asyncio.create_task(
                    _stop_polling(dp, signum, shutdown_requested)
                ),
            )

    return shutdown_requested


async def wait_for_inflight_updates(dp: Dispatcher, timeout: float = 10.0) -> None:
    """Дожидается уже принятых обработчиков перед закрытием общих ресурсов."""
    tasks = [
        task for task in getattr(dp, "_handle_update_tasks", set()) if not task.done()
    ]
    if not tasks:
        return

    logger.info("Ожидаем завершения %d in-flight update tasks", len(tasks))
    done, pending = await asyncio.wait(tasks, timeout=timeout)
    if pending:
        logger.warning(
            "Shutdown timeout: %d/%d update tasks не завершились вовремя",
            len(pending),
            len(tasks),
        )
    else:
        logger.info("Все %d in-flight update tasks завершены", len(done))


async def main():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    openrouter_key = os.getenv("OPENROUTER_API_KEY")

    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN не задан")
        return
    if not openrouter_key:
        logger.error("OPENROUTER_API_KEY не задан — завершение работы")
        return
    openrouter_key = openrouter_key.strip()
    if (
        openrouter_key == "***"
        or openrouter_key == "your-key-here"
        or len(openrouter_key) < 20
    ):
        logger.error(
            "OPENROUTER_API_KEY является placeholder'ом или слишком короток — завершение работы"
        )
        return
    if not openrouter_key.startswith("sk-or-v1-"):
        logger.error("OPENROUTER_API_KEY имеет неожиданный формат — завершение работы")
        return

    # Инициализируем БД
    db_path = os.getenv("DB_PATH", "data/tutor.db")
    os.makedirs(
        os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True
    )
    await init_db(db_path)

    admin_stats_server = create_admin_stats_server_from_env(db_path)
    if admin_stats_server:
        admin_stats_server.start()

    # Инициализируем provider_token для ЮKassa
    yookassa_token = os.getenv("YOOKASSA_PROVIDER_TOKEN", "")
    if yookassa_token:
        set_provider_token(yookassa_token)
        logger.info("ЮKassa провайдер инициализирован")
    else:
        logger.warning("YOOKASSA_PROVIDER_TOKEN не задан — тестовый режим оплаты")

    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    shutdown_requested = register_shutdown_signal_handlers(dp)

    # Регистрируем роутеры (exercise до dialogue — перехват translation-ответов)
    dp.include_router(start.router)
    dp.include_router(subscription.router)
    dp.include_router(reminder.router)
    dp.include_router(digest.router)
    dp.include_router(broadcast.router)
    dp.include_router(dictionary.router)
    dp.include_router(exercise.router)  # до dialogue — для HasActiveTranslationExercise
    dp.include_router(dialogue.router)

    # Запускаем фоновую проверку истекающих подписок
    checker_task = start_subscription_checker(bot=bot, interval=3600, notify=True)

    # Запускаем фоновую рассылку напоминаний
    conn = await get_conn()
    reminder_svc = ReminderService(
        bot=bot,
        reminder_repo=ReminderSettingsRepository(conn),
        user_repo=UserRepository(conn),
    )
    reminder_svc.start()

    # Запускаем фоновую рассылку ежедневных дайджестов
    digest_svc = DailyDigestSender(
        bot=bot,
        reminder_repo=ReminderSettingsRepository(conn),
        user_repo=UserRepository(conn),
    )
    digest_svc.start()

    # Shutdown handler — перестаём принимать работу, ждём текущие операции и
    # контролируемо закрываем фоновые сервисы + подключения к БД.
    async def on_shutdown():
        logger.info("Начинаем graceful shutdown")
        await wait_for_inflight_updates(dp)
        checker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(checker_task, timeout=5)
        await reminder_svc.stop()
        await digest_svc.stop()
        if admin_stats_server:
            admin_stats_server.stop()
        await close_all_connections()
        logger.info("Graceful shutdown завершён")

    dp.shutdown.register(on_shutdown)

    if shutdown_requested.is_set():
        await on_shutdown()
        return

    logger.info("Бот запущен. Нажми Ctrl+C для остановки.")
    await dp.start_polling(bot, handle_signals=False)


if __name__ == "__main__":
    asyncio.run(main())
