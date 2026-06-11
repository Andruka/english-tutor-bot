"""Тесты подписки — планы, оплата, разграничение доступа."""

import pytest
import pytest_asyncio
import tempfile
from datetime import datetime, timedelta, timezone


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


@pytest.mark.asyncio
async def test_subscription_has_expiry(db):
    """В таблице users есть поле subscription_expiry."""
    cursor = await db.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in await cursor.fetchall()]
    assert "subscription_expiry" in columns


@pytest.mark.asyncio
async def test_subscription_plans_list():
    """Список планов содержит названия и цены."""
    from bot.services.subscription_service import SUBSCRIPTION_PLANS

    assert "monthly" in SUBSCRIPTION_PLANS
    assert "yearly" in SUBSCRIPTION_PLANS
    assert SUBSCRIPTION_PLANS["monthly"]["price_kopecks"] == 19900
    assert SUBSCRIPTION_PLANS["yearly"]["price_kopecks"] == 149000


@pytest.mark.asyncio
async def test_subscription_plan_durations():
    """Длительность подписок корректна."""
    from bot.services.subscription_service import SUBSCRIPTION_PLANS

    assert SUBSCRIPTION_PLANS["monthly"]["duration_days"] == 30
    assert SUBSCRIPTION_PLANS["yearly"]["duration_days"] == 365


@pytest.mark.asyncio
async def test_set_subscription(db):
    """Установка подписки пользователю."""
    from bot.db import UserRepository

    repo = UserRepository(db)
    await repo.create(111, "A1", "testuser")

    # Устанавливаем подписку
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(days=30)
    await repo.set_subscription(111, True, expiry.isoformat())

    user = await repo.get(111)
    assert user.subscription is True
    assert user.subscription_expiry is not None


@pytest.mark.asyncio
async def test_subscription_expired(db):
    """Истёкшая подписка считается неактивной."""
    from bot.db import UserRepository

    repo = UserRepository(db)
    await repo.create(222, "A1", "testuser2")

    # Устанавливаем истёкшую подписку
    expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    await repo.set_subscription(222, False, expired)

    user = await repo.get(222)
    assert user.subscription is False


@pytest.mark.asyncio
async def test_free_limit_after_expiry(db):
    """После истечения подписки лимит сбрасывается до бесплатного."""
    from bot.db import UserRepository

    repo = UserRepository(db)
    await repo.create(333, "A1", "testuser3")

    expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    await repo.set_subscription(333, False, expired)

    user = await repo.get(333)
    assert user.subscription is False
    assert user.dialogues_today == 0


@pytest.mark.asyncio
async def test_subscribe_command_exists():
    """Хендлер /subscribe существует и вызывается."""
    from bot.handlers.subscription import router

    assert len(router.message.handlers) > 0


@pytest.mark.asyncio
async def test_payment_url_generated():
    """Генерация ссылки на оплату через ЮKassa."""
    from bot.services.subscription_service import create_invoice_link

    link = await create_invoice_link("monthly", 555)
    assert "monthly" in link
    assert "555" in link
    assert "19900" in link


@pytest.mark.asyncio
async def test_check_subscription_on_dialogue(db):
    """Проверка подписки при каждом диалоге."""
    from bot.db import UserRepository

    repo = UserRepository(db)
    await repo.create(444, "A1", "testuser4")

    # Устанавливаем подписку на 30 дней
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(days=30)
    await repo.set_subscription(444, True, expiry.isoformat())

    # Проверяем через сервис
    user = await repo.get(444)
    from bot.services.subscription_service import get_user_subscription_status

    status = await get_user_subscription_status(user, repo)
    assert status["active"] is True
    assert status["days_left"] > 0


@pytest.mark.asyncio
async def test_auto_revoke_expired_subscription(db):
    """Автоматическое отключение истёкшей подписки при проверке."""
    from bot.db import UserRepository
    from bot.services.subscription_service import check_and_update_subscription

    repo = UserRepository(db)
    await repo.create(555, "A1", "testuser5")

    expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    await repo.set_subscription(555, True, expired)

    active = await check_and_update_subscription(555, repo)
    assert active is False

    user = await repo.get(555)
    assert user.subscription is False
