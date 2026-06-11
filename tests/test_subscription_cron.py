"""Тесты фоновой проверки истекающих подписок (K003)."""

import pytest
import pytest_asyncio
import asyncio
import tempfile
from unittest.mock import AsyncMock
from datetime import datetime, timedelta, timezone

from aiogram import Bot

from bot.services.subscription_cron import (
    find_expired_subscriptions,
    find_almost_expired_subscriptions,
    revoke_subscription,
    revoke_all_expired,
    notify_user_expired,
    notify_users_expired,
    check_once_and_notify,
    subscription_checker_loop,
    start_subscription_checker,
)


@pytest_asyncio.fixture
async def db():
    """Временная БД для тестов."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    from bot.db import init_db

    await init_db(f.name)

    import aiosqlite

    conn = await aiosqlite.connect(f.name)
    conn.row_factory = aiosqlite.Row
    yield conn
    await conn.close()

    import os

    os.unlink(f.name)


@pytest_asyncio.fixture
async def seeded_db(db):
    """БД с тремя пользователями: без подписки, с активной, с истёкшей."""
    from bot.db import UserRepository

    repo = UserRepository(db)
    await repo.create(1000, "A1", "no_sub_user")
    await repo.create(1001, "A1", "active_sub_user")
    await repo.create(1002, "A1", "expired_sub_user")
    await repo.create(1003, "A1", "almost_expired_user")

    now = datetime.now(timezone.utc)

    # user 1001 — активная подписка (ещё 10 дней)
    active_expiry = (now + timedelta(days=10)).isoformat()
    await repo.set_subscription(1001, True, active_expiry)

    # user 1002 — истёкшая (1 день назад)
    expired_expiry = (now - timedelta(days=1)).isoformat()
    await repo.set_subscription(1002, True, expired_expiry)

    # user 1003 — скоро истекает (через 6 часов)
    almost_expiry = (now + timedelta(hours=6)).isoformat()
    await repo.set_subscription(1003, True, almost_expiry)

    yield db


# ─── find_expired_subscriptions ───────────────────────────────────


@pytest.mark.asyncio
async def test_find_expired_skips_no_subscription(seeded_db):
    """Пользователь без подписки не попадает в список истёкших."""
    result = await find_expired_subscriptions()
    user_ids = {e["user_id"] for e in result}
    assert 1000 not in user_ids  # без подписки
    assert 1001 not in user_ids  # активная


@pytest.mark.asyncio
async def test_find_expired_detects_expired(seeded_db):
    """Пользователь с истёкшей подпиской находится."""
    result = await find_expired_subscriptions()
    user_ids = {e["user_id"] for e in result}
    assert 1002 in user_ids


@pytest.mark.asyncio
async def test_find_expired_returns_correct_fields(seeded_db):
    """Возвращаемые записи содержат user_id, username, subscription_expiry."""
    result = await find_expired_subscriptions()
    for entry in result:
        assert "user_id" in entry
        assert "username" in entry
        assert "subscription_expiry" in entry


@pytest.mark.asyncio
async def test_find_expired_empty_when_all_active(db):
    """Если никто не просрочен — пустой список."""
    from bot.db import UserRepository

    repo = UserRepository(db)
    await repo.create(2000, "A1", "fresh_user")
    now = datetime.now(timezone.utc)
    await repo.set_subscription(2000, True, (now + timedelta(days=30)).isoformat())

    result = await find_expired_subscriptions()
    assert result == []


# ─── find_almost_expired_subscriptions ─────────────────────────────


@pytest.mark.asyncio
async def test_find_almost_expired_default(seeded_db):
    """Пользователь с истечением < 24 часов находится."""
    result = await find_almost_expired_subscriptions(hours_left=24)
    user_ids = {e["user_id"] for e in result}
    assert 1003 in user_ids  # expires in 6 hours


@pytest.mark.asyncio
async def test_find_almost_expired_narrow_window(seeded_db):
    """Если окно меньше времени до истечения — не находит."""
    # user 1003 expires in 6 hours, окно в 2 часа — не должно попасть
    result = await find_almost_expired_subscriptions(hours_left=2)
    user_ids = {e["user_id"] for e in result}
    assert 1003 not in user_ids


# ─── revoke_subscription ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_active_subscription(seeded_db):
    """Отзыв активной подписки."""
    from bot.db import UserRepository

    repo = UserRepository(seeded_db)
    user = await repo.get(1001)
    assert user.subscription is True

    ok = await revoke_subscription(1001)
    assert ok is True

    user = await repo.get(1001)
    assert user.subscription is False


@pytest.mark.asyncio
async def test_revoke_already_revoked(seeded_db):
    """Повторный отзыв неактивной подписки — False."""
    ok = await revoke_subscription(1000)  # без подписки
    assert ok is False


@pytest.mark.asyncio
async def test_revoke_nonexistent_user():
    """Отзыв для несуществующего пользователя — False."""
    ok = await revoke_subscription(999999)
    assert ok is False


# ─── revoke_all_expired ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_all_removes_expired(seeded_db):
    """revoke_all_expired находит и отзывает истёкшие подписки."""
    from bot.db import UserRepository

    revoked = await revoke_all_expired()
    revoked_ids = {e["user_id"] for e in revoked}
    assert 1002 in revoked_ids  # expired
    assert 1001 not in revoked_ids  # still active

    # Проверяем, что в БД subscription=0 для user 1002
    repo = UserRepository(seeded_db)
    user = await repo.get(1002)
    assert user.subscription is False


@pytest.mark.asyncio
async def test_revoke_all_returns_usernames(seeded_db):
    """revoke_all_expired возвращает user_id и username для уведомлений."""
    revoked = await revoke_all_expired()
    for entry in revoked:
        assert "user_id" in entry
        assert "username" in entry


@pytest.mark.asyncio
async def test_revoke_all_empty_when_none_expired(db):
    """Если нет истёкших — возвращает []."""
    from bot.db import UserRepository

    repo = UserRepository(db)
    await repo.create(3000, "A1", "active_user")
    await repo.set_subscription(
        3000, True, (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    )

    revoked = await revoke_all_expired()
    assert revoked == []


# ─── notify_user_expired / notify_users_expired ─────────────────────


@pytest.mark.asyncio
async def test_notify_user_expired():
    """Уведомление одного пользователя."""
    bot = AsyncMock(spec=Bot)
    ok = await notify_user_expired(bot, 123, "test_user")
    assert ok is True
    assert bot.send_message.await_count == 1
    args, _ = bot.send_message.await_args
    assert args[0] == 123


@pytest.mark.asyncio
async def test_notify_user_expired_handles_exception():
    """Если send_message кидает исключение — возвращает False."""
    bot = AsyncMock(spec=Bot)
    bot.send_message.side_effect = Exception("Network error")
    ok = await notify_user_expired(bot, 999)
    assert ok is False


@pytest.mark.asyncio
async def test_notify_users_expired():
    """Массовое уведомление."""
    bot = AsyncMock(spec=Bot)
    user_list = [{"user_id": 1, "username": "a"}, {"user_id": 2, "username": "b"}]
    count = await notify_users_expired(bot, user_list)
    assert count == 2
    assert bot.send_message.await_count == 2


# ─── check_once_and_notify ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_once_revokes_and_notifies(seeded_db):
    """Одна итерация находит, отзывает и уведомляет."""
    bot = AsyncMock(spec=Bot)
    bot.send_message.return_value = None

    count = await check_once_and_notify(bot=bot, notify=True)
    assert count == 1  # только user 1002 истёк
    assert bot.send_message.await_count >= 1


@pytest.mark.asyncio
async def test_check_once_no_bot_skip_notify(seeded_db):
    """Без bot — отзыв есть, уведомлений нет."""
    count = await check_once_and_notify(bot=None, notify=True)
    assert count == 1


@pytest.mark.asyncio
async def test_check_once_notify_disabled(seeded_db):
    """notify=False — отзыв есть, уведомлений нет."""
    bot = AsyncMock(spec=Bot)
    count = await check_once_and_notify(bot=bot, notify=False)
    assert count == 1
    bot.send_message.assert_not_called()


# ─── subscription_checker_loop ──────────────────────────────────────


@pytest.mark.asyncio
async def test_checker_loop_runs_and_cancels(seeded_db):
    """Цикл запускается, делает итерацию, отзывается через cancel."""
    bot = AsyncMock(spec=Bot)

    task = asyncio.create_task(
        subscription_checker_loop(bot=bot, interval=10, notify=True)
    )
    # Даём время на запуск
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Цикл не упал, структура корректна
    assert True


# ─── start_subscription_checker ─────────────────────────────────────


@pytest.mark.asyncio
async def test_start_checker_returns_task():
    """start_subscription_checker возвращает asyncio.Task."""
    bot = AsyncMock(spec=Bot)
    task = start_subscription_checker(bot=bot, interval=3600, notify=True)
    assert isinstance(task, asyncio.Task)
    assert not task.done()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
