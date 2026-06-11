"""Тесты для прогресса и геймификации — streak, achievements, дашборд."""

import pytest
import tempfile
import os
from unittest.mock import AsyncMock, patch


# ====== Achievement Repository Tests ======


@pytest.mark.asyncio
async def test_add_achievement():
    """Добавление достижения в БД."""
    from bot.db import init_db, get_conn
    from bot.services.progress_service import AchievementRepository

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    repo = AchievementRepository(conn)
    await repo.add(12345, "first_lesson")

    result = await repo.get_all(12345)
    assert len(result) == 1
    assert result[0]["achievement_id"] == "first_lesson"


@pytest.mark.asyncio
async def test_add_achievement_duplicate():
    """Повторное добавление того же достижения — без ошибки."""
    from bot.db import init_db, get_conn
    from bot.services.progress_service import AchievementRepository

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    repo = AchievementRepository(conn)
    await repo.add(12345, "first_lesson")
    await repo.add(12345, "first_lesson")  # должно проигнорировать

    result = await repo.get_all(12345)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_get_all_achievements():
    """Получение всех достижений пользователя."""
    from bot.db import init_db, get_conn
    from bot.services.progress_service import AchievementRepository

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    repo = AchievementRepository(conn)
    await repo.add(12345, "first_lesson")
    await repo.add(12345, "streak_7")
    await repo.add(12345, "dialogues_50")

    result = await repo.get_all(12345)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_has_achievement():
    """Проверка наличия конкретного достижения."""
    from bot.db import init_db, get_conn
    from bot.services.progress_service import AchievementRepository

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    repo = AchievementRepository(conn)
    await repo.add(12345, "first_lesson")

    assert await repo.has(12345, "first_lesson") is True
    assert await repo.has(12345, "streak_7") is False


@pytest.mark.asyncio
async def test_achievement_has_timestamp():
    """Достижение содержит дату получения."""
    from bot.db import init_db, get_conn
    from bot.services.progress_service import AchievementRepository

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    repo = AchievementRepository(conn)
    await repo.add(12345, "first_lesson")

    result = await repo.get_all(12345)
    assert result[0]["earned_at"] is not None


# ====== Achievement Checker Tests ======


@pytest.mark.asyncio
async def test_check_first_lesson_achievement():
    """Первый диалог даёт достижение first_lesson."""
    from bot.db import init_db, get_conn
    from bot.services.progress_service import AchievementChecker

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    checker = AchievementChecker(conn)
    earned = await checker.check_after_dialogue(
        12345, dialogue_count=1, streak=1, corrections=[]
    )

    assert "first_lesson" in earned


@pytest.mark.asyncio
async def test_check_streak_7_achievement():
    """Streak 7 дней даёт достижение streak_7."""
    from bot.db import init_db, get_conn
    from bot.services.progress_service import AchievementChecker

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    checker = AchievementChecker(conn)
    earned = await checker.check_after_dialogue(
        12345, dialogue_count=50, streak=7, corrections=[]
    )

    assert "streak_7" in earned


@pytest.mark.asyncio
async def test_check_streak_30_achievement():
    """Streak 30 дней даёт достижение streak_30."""
    from bot.db import init_db, get_conn
    from bot.services.progress_service import AchievementChecker

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    checker = AchievementChecker(conn)
    earned = await checker.check_after_dialogue(
        12345, dialogue_count=100, streak=30, corrections=[]
    )

    assert "streak_30" in earned


@pytest.mark.asyncio
async def test_check_dialogues_50_achievement():
    """50 диалогов даёт достижение dialogues_50."""
    from bot.db import init_db, get_conn
    from bot.services.progress_service import AchievementChecker

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    checker = AchievementChecker(conn)
    earned = await checker.check_after_dialogue(
        12345, dialogue_count=50, streak=0, corrections=[]
    )

    assert "dialogues_50" in earned


@pytest.mark.asyncio
async def test_check_dialogues_100_achievement():
    """100 диалогов даёт достижение dialogues_100."""
    from bot.db import init_db, get_conn
    from bot.services.progress_service import AchievementChecker

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    checker = AchievementChecker(conn)
    earned = await checker.check_after_dialogue(
        12345, dialogue_count=100, streak=0, corrections=[]
    )

    assert "dialogues_100" in earned


@pytest.mark.asyncio
async def test_check_first_correction():
    """Первое исправление даёт достижение first_correction."""
    from bot.db import init_db, get_conn
    from bot.services.progress_service import AchievementChecker

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    checker = AchievementChecker(conn)
    earned = await checker.check_after_dialogue(
        12345,
        dialogue_count=5,
        streak=3,
        corrections=[{"original": "I go", "corrected": "I went", "category": "tense"}],
    )

    assert "first_correction" in earned


@pytest.mark.asyncio
async def test_check_no_duplicate_achievements():
    """Повторная проверка не выдаёт те же достижения."""
    from bot.db import init_db, get_conn
    from bot.services.progress_service import AchievementChecker, AchievementRepository

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    # Сначала выдаём достижение
    ach_repo = AchievementRepository(conn)
    await ach_repo.add(12345, "first_lesson")

    checker = AchievementChecker(conn)
    earned = await checker.check_after_dialogue(
        12345, dialogue_count=1, streak=1, corrections=[]
    )

    assert "first_lesson" not in earned  # уже есть


# ====== Streak Tests ======


@pytest.mark.asyncio
async def test_streak_called_after_text_dialogue():
    """После текстового диалога вызывается update_streak."""
    from bot.handlers.dialogue import handle_text_dialogue
    from bot.db import init_db, get_conn, UserRepository

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()
    repo = UserRepository(conn)
    await repo.create(12345, "A2", "testuser")

    mock_message = AsyncMock()
    mock_message.from_user.id = 12345
    mock_message.text = "hello"
    mock_message.bot = AsyncMock()
    mock_message.bot.send_chat_action = AsyncMock()

    with (
        patch("bot.db.UserRepository.update_streak") as mock_streak,
        patch(
            "bot.services.ai_service.AITutor.chat", new_callable=AsyncMock
        ) as mock_chat,
        patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-v1-xxx-test"}),
    ):
        mock_chat.return_value = {
            "reply": "Great job!",
            "rating": 4,
            "correction": None,
        }
        await handle_text_dialogue(mock_message)
        mock_streak.assert_called_once_with(12345)


# ====== Progress Dashboard Tests ======


@pytest.mark.asyncio
async def test_get_progress_dashboard():
    """Дашборд прогресса содержит все ключевые метрики."""
    from bot.db import init_db, get_conn, UserRepository, DialogueRepository
    from bot.services.progress_service import (
        AchievementRepository,
        get_progress_dashboard,
    )

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    # Создаём пользователя с данными
    user_repo = UserRepository(conn)
    await user_repo.create(12345, "B1", "testuser")
    await user_repo.update_streak(12345)  # streak = 1

    dial_repo = DialogueRepository(conn)
    await dial_repo.save(12345, "hello", "Hi there!", "introduction", 4, [])
    await dial_repo.save(12345, "how are you", "I'm fine!", "introduction", 4, [])

    ach_repo = AchievementRepository(conn)
    await ach_repo.add(12345, "first_lesson")

    dashboard = await get_progress_dashboard(12345)

    assert "level" in dashboard
    assert "streak" in dashboard
    assert "total_dialogues" in dashboard
    assert dashboard["total_dialogues"] == 2
    assert "achievements" in dashboard
    assert len(dashboard["achievements"]) == 1
