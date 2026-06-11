"""Тесты контролируемой админской рассылки."""

import os
import tempfile
from datetime import date
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest
import pytest_asyncio
from aiogram.types import Chat, Message, User

from bot.db import UserRepository, init_db


@pytest_asyncio.fixture
async def db():
    """Временная файловая БД: aiosqlite открывает отдельные подключения."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()

    import bot.db as bdb

    old_path = bdb._db_path
    bdb._db_path = f.name
    await init_db(f.name)
    conn = await aiosqlite.connect(f.name)
    conn.row_factory = aiosqlite.Row
    try:
        yield conn
    finally:
        await conn.close()
        os.unlink(f.name)
        bdb._db_path = old_path


def _fake_message(text: str, user_id: int = 42) -> Message:
    return Message(
        message_id=1,
        date=date.today(),
        chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, is_bot=False, first_name="Admin"),
        text=text,
    )


class FakeBot:
    def __init__(self, failing_user_ids=None):
        self.sent = []
        self.failing_user_ids = set(failing_user_ids or [])

    async def send_message(self, chat_id: int, text: str, **kwargs):
        if chat_id in self.failing_user_ids:
            raise RuntimeError("telegram unavailable")
        self.sent.append((chat_id, text, kwargs))


@pytest.mark.asyncio
async def test_broadcast_service_sends_to_all_users_with_throttling(db):
    """Рассылка доставляет сообщение всем пользователям и делает паузу между отправками."""
    from bot.services.broadcast_service import BroadcastService, BroadcastTarget

    users = UserRepository(db)
    await users.create(100, "A1", "alice")
    await users.create(200, "B1", "bob")
    await users.create(300, "A1", "charlie")
    sleeps = []
    bot = FakeBot()
    service = BroadcastService(bot=bot, conn=db, sleep=sleeps.append)

    result = await service.send(
        BroadcastTarget(kind="all"),
        "System maintenance tonight",
        messages_per_second=2,
    )

    assert result.total == 3
    assert result.sent == 3
    assert result.failed == 0
    assert [chat_id for chat_id, _, _ in bot.sent] == [100, 200, 300]
    assert all(text == "System maintenance tonight" for _, text, _ in bot.sent)
    assert sleeps == [0.5, 0.5]


@pytest.mark.asyncio
async def test_broadcast_service_can_target_user_subset_by_level(db):
    """Subset-рассылка выбирает только пользователей нужного уровня."""
    from bot.services.broadcast_service import BroadcastService, BroadcastTarget

    users = UserRepository(db)
    await users.create(100, "A1", "alice")
    await users.create(200, "B1", "bob")
    await users.create(300, "A1", "charlie")
    bot = FakeBot()

    result = await BroadcastService(bot=bot, conn=db, sleep=AsyncMock()).send(
        BroadcastTarget(kind="level", value="A1"),
        "A1 lesson starts now",
        messages_per_second=10,
    )

    assert result.total == 2
    assert result.sent == 2
    assert [chat_id for chat_id, _, _ in bot.sent] == [100, 300]


@pytest.mark.asyncio
async def test_broadcast_service_continues_after_single_user_failure(db):
    """Ошибка доставки одному пользователю не останавливает всю рассылку."""
    from bot.services.broadcast_service import BroadcastService, BroadcastTarget

    users = UserRepository(db)
    await users.create(100, "A1", "alice")
    await users.create(200, "A1", "bob")
    bot = FakeBot(failing_user_ids={100})

    result = await BroadcastService(bot=bot, conn=db, sleep=AsyncMock()).send(
        BroadcastTarget(kind="all"),
        "Hello",
        messages_per_second=10,
    )

    assert result.total == 2
    assert result.sent == 1
    assert result.failed == 1
    assert result.failures == [(100, "telegram unavailable")]
    assert [chat_id for chat_id, _, _ in bot.sent] == [200]


@patch.object(Message, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_broadcast_command_requires_admin_confirmation(
    mock_answer, db, monkeypatch
):
    """Первый /broadcast показывает preview и не отправляет реальные сообщения."""
    from bot.handlers.broadcast import cmd_broadcast

    users = UserRepository(db)
    await users.create(100, "A1", "alice")
    bot = FakeBot()
    monkeypatch.setenv("ADMIN_USER_IDS", "42")

    with patch("bot.handlers.broadcast.get_conn", return_value=db):
        await cmd_broadcast(_fake_message("/broadcast all Hello students"), bot=bot)

    assert bot.sent == []
    mock_answer.assert_awaited_once()
    args, _ = mock_answer.await_args
    assert "Подтверждение" in args[0]
    assert "/broadcast --confirm all Hello students" in args[0]


@patch.object(Message, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_broadcast_command_executes_after_confirmation(
    mock_answer, db, monkeypatch
):
    """Команда с --confirm отправляет сообщение выбранным пользователям и отдаёт отчёт."""
    from bot.handlers.broadcast import cmd_broadcast

    users = UserRepository(db)
    await users.create(100, "A1", "alice")
    await users.create(200, "B1", "bob")
    bot = FakeBot()
    monkeypatch.setenv("ADMIN_USER_IDS", "42")

    with patch("bot.handlers.broadcast.get_conn", return_value=db):
        await cmd_broadcast(
            _fake_message("/broadcast --confirm level:A1 Hello A1"), bot=bot
        )

    assert bot.sent == [(100, "Hello A1", {})]
    args, _ = mock_answer.await_args
    assert "Готово" in args[0]
    assert "1/1" in args[0]


@patch.object(Message, "answer", new_callable=AsyncMock)
@pytest.mark.asyncio
async def test_broadcast_command_rejects_non_admin(mock_answer, db, monkeypatch):
    """Неадмин не может запускать рассылку даже с --confirm."""
    from bot.handlers.broadcast import cmd_broadcast

    bot = FakeBot()
    monkeypatch.setenv("ADMIN_USER_IDS", "42")

    with patch("bot.handlers.broadcast.get_conn", return_value=db):
        await cmd_broadcast(
            _fake_message("/broadcast --confirm all Hello", user_id=7), bot=bot
        )

    assert bot.sent == []
    args, _ = mock_answer.await_args
    assert "нет доступа" in args[0].lower()
