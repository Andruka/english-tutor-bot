"""Тесты ежедневного digest-сервиса."""

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import pytest

from bot.db import (
    ReminderSettings,
    ReminderSettingsRepository,
    UserRepository,
    get_conn,
    init_db,
)
from bot.services.daily_digest_service import (
    DailyDigestSender,
    collect_daily_digest,
    format_daily_digest,
)


@pytest.fixture
async def conn(tmp_path):
    db_path = tmp_path / "digest.db"
    await init_db(str(db_path))
    connection = await get_conn()
    try:
        yield connection
    finally:
        await connection.close()


async def create_user(conn, user_id: int, *, streak: int = 0, username: str = "tester"):
    user = await UserRepository(conn).create(user_id, "A2", username)
    await conn.execute(
        "UPDATE users SET streak = ? WHERE user_id = ?", (streak, user_id)
    )
    await conn.commit()
    return user


@pytest.mark.asyncio
async def test_collect_and_format_digest_with_no_data(conn):
    await create_user(conn, 1001, streak=0)

    data = await collect_daily_digest(
        conn,
        user_id=1001,
        tz="Europe/Moscow",
        target_date=date(2026, 6, 11),
    )
    text = format_daily_digest(data)

    assert data.dialogues_today == 0
    assert data.words_due == 0
    assert data.achievements_today == []
    assert "<b>Твой прогресс за сегодня</b>" in text
    assert "Сегодня практики не было" in text
    assert "Тест прогресса" in text
    assert "Начать урок" in text


@pytest.mark.asyncio
async def test_collect_digest_counts_required_sections(conn):
    await create_user(conn, 1002, streak=3)
    await conn.execute(
        """
        INSERT INTO dialogues (user_id, topic, user_message, ai_reply, rating, corrections, timestamp)
        VALUES (?, 'travel', 'hi', 'hello', 8, ?, '2026-06-11 18:10:00')
        """,
        (1002, '[{"old":"a","new":"b"}, {"old":"c","new":"d"}]'),
    )
    await conn.execute(
        """
        INSERT INTO dictionary (user_id, word, translation, level, next_review, created_at)
        VALUES (?, 'journey', 'путешествие', 'new', '2020-01-01 00:00:00', '2026-06-11 19:00:00')
        """,
        (1002,),
    )
    await conn.execute(
        """
        INSERT INTO dictionary (user_id, word, translation, level, next_review, created_at)
        VALUES (?, 'fluent', 'беглый', 'mastered', '2099-01-01 00:00:00', '2026-06-10 19:00:00')
        """,
        (1002,),
    )
    await conn.execute(
        "INSERT INTO achievements (user_id, achievement_id, earned_at) VALUES (?, 'first_lesson', '2026-06-11')",
        (1002,),
    )
    await conn.commit()

    data = await collect_daily_digest(
        conn,
        user_id=1002,
        tz="Europe/Moscow",
        target_date=date(2026, 6, 11),
    )
    text = format_daily_digest(data)

    assert data.dialogues_today == 1
    assert data.avg_rating_today == 8
    assert data.corrections_today == 2
    assert data.words_added_today == 1
    assert data.words_due == 1
    assert data.words_mastered == 1
    assert data.achievements_today == ["🎓 Первый урок"]
    assert "Диалоги" in text
    assert "Слова" in text
    assert "Streak" in text
    assert "Повтори 1 слов" in text


@pytest.mark.asyncio
async def test_sender_respects_local_digest_time_and_timezone(conn):
    await create_user(conn, 2001, username="moscow")
    await create_user(conn, 2002, username="newyork")
    repo = ReminderSettingsRepository(conn)
    await repo.upsert(
        ReminderSettings(
            user_id=2001,
            timezone="Europe/Moscow",
            digest_enabled=True,
            digest_time="21:00",
        )
    )
    await repo.upsert(
        ReminderSettings(
            user_id=2002,
            timezone="America/New_York",
            digest_enabled=True,
            digest_time="21:00",
        )
    )

    bot = AsyncMock()
    sender = DailyDigestSender(
        bot=bot, reminder_repo=repo, user_repo=UserRepository(conn)
    )
    sent = await sender.check_and_send_digests(
        now=datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc)
    )

    assert sent == 1
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == 2001
    assert "Твой прогресс за сегодня" in bot.send_message.await_args.kwargs["text"]
    assert (await repo.get(2001)).last_digest_date == "2026-06-11"
    assert (await repo.get(2002)).last_digest_date is None


@pytest.mark.asyncio
async def test_sender_does_not_send_twice_for_same_local_day(conn):
    await create_user(conn, 3001)
    repo = ReminderSettingsRepository(conn)
    await repo.upsert(
        ReminderSettings(
            user_id=3001,
            timezone="Europe/Moscow",
            digest_enabled=True,
            digest_time="21:00",
            last_digest_date="2026-06-11",
        )
    )

    bot = AsyncMock()
    sender = DailyDigestSender(
        bot=bot, reminder_repo=repo, user_repo=UserRepository(conn)
    )
    sent = await sender.check_and_send_digests(
        now=datetime(2026, 6, 11, 19, 0, tzinfo=timezone.utc)
    )

    assert sent == 0
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_sender_falls_back_for_invalid_timezone(conn):
    await create_user(conn, 4001)
    repo = ReminderSettingsRepository(conn)
    await repo.upsert(
        ReminderSettings(
            user_id=4001,
            timezone="Invalid/Zone",
            digest_enabled=True,
            digest_time="21:00",
        )
    )

    bot = AsyncMock()
    sender = DailyDigestSender(
        bot=bot, reminder_repo=repo, user_repo=UserRepository(conn)
    )
    sent = await sender.check_and_send_digests(
        now=datetime(2026, 6, 11, 18, 0, tzinfo=timezone.utc)
    )

    assert sent == 1
    bot.send_message.assert_awaited_once()
    assert (await repo.get(4001)).last_digest_date == "2026-06-11"
