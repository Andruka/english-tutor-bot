"""Helper-процесс для интеграционного теста graceful shutdown.

Запускает реальные обработчики сигналов, открывает подключение к БД,
создаёт очередь in-flight задач, регистрирует shutdown-колбэк (как в main.py),
и ждёт SIGTERM. При получении сигнала — корректно завершается с кодом 0.
"""

import asyncio
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("shutdown_helper")

# Добавляем корень проекта в sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram import Dispatcher  # noqa: E402
from bot.main import (  # noqa: E402
    register_shutdown_signal_handlers,
    wait_for_inflight_updates,
)
from bot.db import init_db, get_conn, close_all_connections  # noqa: E402


async def main():
    db_path = os.environ.get("TEST_DB_PATH", "/tmp/test_graceful_shutdown.db")

    # ── 1. Создаём Dispatcher и регистрируем реальные обработчики сигналов ──
    dp = Dispatcher()
    shutdown_requested = register_shutdown_signal_handlers(dp)

    # ── 2. Инициализируем БД и открываем долгоживущее подключение ──
    await init_db(db_path)
    conn = await get_conn()
    logger.info("DB connection opened (tracked: %s)", conn)

    # ── 3. Создаём 2 in-flight задачи (имитируем активные обработчики) ──
    async def long_op(name: str):
        logger.info("In-flight task '%s' started", name)
        try:
            await asyncio.sleep(300)  # достаточно долго, чтобы нас убили до завершения
        except asyncio.CancelledError:
            logger.info("In-flight task '%s' cancelled during shutdown", name)
            raise

    task_a = asyncio.create_task(long_op("task_a"))
    task_b = asyncio.create_task(long_op("task_b"))
    # Подмешиваем в Dispatcher (как это делает aiogram)
    dp._handle_update_tasks = {task_a, task_b}

    # ── 4. Регистрируем shutdown-колбэк (как в main.py) ──
    async def on_shutdown():
        logger.info("=== Graceful shutdown: начало ===")
        # Ждём in-flight задачи (с небольшим таймаутом — они долгие)
        await wait_for_inflight_updates(dp, timeout=0.5)
        # Закрываем все подключения к БД
        await close_all_connections()
        logger.info("=== Graceful shutdown: завершён ===")

    dp.shutdown.register(on_shutdown)

    # ── 5. Если сигнал пришёл ДО этой точки — выполняем shutdown сразу ──
    if shutdown_requested.is_set():
        logger.warning("Shutdown was already requested before blocking wait")
        await dp.emit_shutdown()
        logger.info("Helper exiting (early shutdown)")
        return

    # ── 6. Сигнализируем родительскому процессу, что мы готовы ──
    logger.info("Helper ready — waiting for SIGTERM/SIGINT")
    print("READY", flush=True)

    # ── 7. Ждём сигнал ──
    # После получения SIGTERM:
    #   - register_shutdown_signal_handlers вызывает _stop_polling()
    #   - _stop_polling ставит shutdown_requested и вызывает dp.stop_polling()
    #   - Мы выходим из ожидания и запускаем shutdown через emit_shutdown
    await shutdown_requested.wait()

    # ── 8. Запускаем shutdown-колбэк ──
    logger.info("Shutdown requested — running shutdown callbacks")
    await dp.emit_shutdown()
    logger.info("Helper exiting cleanly")


if __name__ == "__main__":
    asyncio.run(main())
