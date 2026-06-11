import asyncio
import signal
from unittest.mock import AsyncMock

import pytest

from bot import main as main_mod


@pytest.mark.asyncio
async def test_register_shutdown_signal_handlers_stops_polling(monkeypatch):
    loop = asyncio.get_running_loop()
    handlers = {}

    def fake_add_signal_handler(signum, callback):
        handlers[signum] = callback

    monkeypatch.setattr(loop, "add_signal_handler", fake_add_signal_handler)

    class FakeDispatcher:
        def __init__(self):
            self.stop_polling = AsyncMock()

    dp = FakeDispatcher()
    shutdown_requested = main_mod.register_shutdown_signal_handlers(dp)

    assert signal.SIGINT in handlers
    assert signal.SIGTERM in handlers
    assert not shutdown_requested.is_set()

    handlers[signal.SIGTERM]()
    await asyncio.sleep(0)

    assert shutdown_requested.is_set()
    dp.stop_polling.assert_awaited_once()


@pytest.mark.asyncio
async def test_wait_for_inflight_updates_waits_until_tasks_finish():
    completed = False

    async def work():
        nonlocal completed
        await asyncio.sleep(0.01)
        completed = True

    task = asyncio.create_task(work())

    class FakeDispatcher:
        _handle_update_tasks = {task}

    await main_mod.wait_for_inflight_updates(FakeDispatcher(), timeout=1.0)

    assert completed
    assert task.done()


@pytest.mark.asyncio
async def test_main_registers_shutdown_handlers_before_start_polling(
    monkeypatch, tmp_path
):
    events = []
    shutdown_callbacks = []

    monkeypatch.setenv(
        "TELEGRAM_BOT_TOKEN", "1234567890:abcdefghijklmnopqrstuvwxyzABCDE"
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "tutor.db"))

    class FakeBot:
        def __init__(self, *args, **kwargs):
            events.append("bot")

    class FakeShutdown:
        def register(self, callback):
            shutdown_callbacks.append(callback)

    class FakeDispatcher:
        def __init__(self):
            self.shutdown = FakeShutdown()
            self._handle_update_tasks = set()
            events.append("dispatcher")

        def include_router(self, router):
            pass

        async def start_polling(self, bot, *, handle_signals=True):
            assert "register_signals" in events
            assert handle_signals is False
            events.append("start_polling")
            for callback in shutdown_callbacks:
                await callback()

    class FakeReminderService:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            events.append("reminder_start")

        async def stop(self):
            events.append("reminder_stop")

    async def fake_init_db(db_path):
        events.append("init_db")

    async def fake_get_conn():
        events.append("get_conn")
        return object()

    async def fake_close_all_connections():
        events.append("close_all")

    async def fake_checker():
        await asyncio.Event().wait()

    def fake_start_subscription_checker(*args, **kwargs):
        events.append("checker_start")
        return asyncio.create_task(fake_checker())

    def fake_register_shutdown_signal_handlers(dp):
        events.append("register_signals")
        return asyncio.Event()

    monkeypatch.setattr(main_mod, "Bot", FakeBot)
    monkeypatch.setattr(main_mod, "Dispatcher", FakeDispatcher)
    monkeypatch.setattr(main_mod, "ReminderService", FakeReminderService)
    monkeypatch.setattr(main_mod, "init_db", fake_init_db)
    monkeypatch.setattr(main_mod, "get_conn", fake_get_conn)
    monkeypatch.setattr(main_mod, "close_all_connections", fake_close_all_connections)
    monkeypatch.setattr(
        main_mod, "start_subscription_checker", fake_start_subscription_checker
    )
    monkeypatch.setattr(
        main_mod,
        "register_shutdown_signal_handlers",
        fake_register_shutdown_signal_handlers,
    )

    await main_mod.main()

    assert events.index("register_signals") < events.index("start_polling")
    assert "close_all" in events
