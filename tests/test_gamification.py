"""Тесты для E202: дерево навыков, ранги и weekly challenge."""

import tempfile
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_skill_tree_starts_with_five_branches_at_level_zero():
    from bot.db import get_conn, init_db
    from bot.services.progress_service import SkillProgressRepository, get_skill_tree

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    repo = SkillProgressRepository(conn)
    tree = await get_skill_tree(12345, repo=repo)

    assert [branch["id"] for branch in tree] == [
        "vocabulary",
        "grammar",
        "speaking",
        "listening",
        "writing",
    ]
    assert all(branch["level"] == 0 for branch in tree)
    assert all(branch["points"] == 0 for branch in tree)


@pytest.mark.asyncio
async def test_award_skill_points_levels_up_branch_and_calculates_rank():
    from bot.db import get_conn, init_db
    from bot.services.progress_service import (
        SkillProgressRepository,
        calculate_rank,
        get_skill_tree,
    )

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    repo = SkillProgressRepository(conn)
    updated = await repo.award_points(12345, "vocabulary", 250)
    await repo.award_points(12345, "grammar", 50)
    tree = await get_skill_tree(12345, repo=repo)

    assert updated["branch_id"] == "vocabulary"
    assert updated["points"] == 250
    assert updated["level"] == 2
    assert calculate_rank(tree) == "Silver"


@pytest.mark.asyncio
async def test_weekly_challenge_has_progress_and_reward_when_completed():
    from bot.db import get_conn, init_db
    from bot.services.progress_service import WeeklyChallengeRepository

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()

    repo = WeeklyChallengeRepository(conn)
    challenge = await repo.get_or_create_current(12345)
    assert challenge["goal"] == 7
    assert challenge["progress"] == 0
    assert challenge["completed"] is False

    progress = None
    for _ in range(7):
        progress = await repo.increment_progress(12345)

    assert progress["progress"] == 7
    assert progress["completed"] is True
    assert progress["reward_achievement_id"] == "weekly_challenge"


@pytest.mark.asyncio
async def test_post_process_dialogue_awards_branch_points_and_weekly_challenge():
    from bot.db import UserRepository, get_conn, init_db
    from bot.handlers.common import post_process_dialogue
    from bot.services.progress_service import (
        AchievementRepository,
        SkillProgressRepository,
        WeeklyChallengeRepository,
    )

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()
    await UserRepository(conn).create(12345, "A2", "testuser")

    message = AsyncMock()
    message.reply = AsyncMock()
    message.reply_voice = AsyncMock()

    result = {
        "reply": "Good answer!",
        "rating": 4,
        "corrections": [
            {"original": "I go", "corrected": "I went", "category": "tense"}
        ],
        "skill_branch": "grammar",
    }

    await post_process_dialogue(message, 12345, "I go yesterday", result, conn)

    skill = await SkillProgressRepository(conn).get_branch(12345, "grammar")
    challenge = await WeeklyChallengeRepository(conn).get_or_create_current(12345)

    assert skill["points"] == 15  # 10 (диалог) + 5 (1 коррекция в result)
    assert skill["level"] == 0
    assert challenge["progress"] == 1
    assert await AchievementRepository(conn).has(12345, "first_lesson") is True


@pytest.mark.asyncio
async def test_post_process_dialogue_awards_correction_xp():
    """XP за коррекции: +5 за каждое исправление (ветка grammar)."""
    from bot.db import UserRepository, get_conn, init_db
    from bot.handlers.common import post_process_dialogue
    from bot.services.progress_service import SkillProgressRepository

    import tempfile

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()
    await UserRepository(conn).create(12346, "A2", "testuser")

    message = AsyncMock()
    message.reply = AsyncMock()
    message.reply_voice = AsyncMock()

    result = {
        "reply": "Good answer!",
        "rating": 4,
        "corrections": [
            {"original": "I go", "corrected": "I went", "category": "tense"},
            {"original": "He go", "corrected": "He goes", "category": "verb"},
        ],
        "skill_branch": "grammar",
    }

    await post_process_dialogue(message, 12346, "I go yesterday", result, conn)

    grammar = await SkillProgressRepository(conn).get_branch(12346, "grammar")
    # 10 (диалог) + 2*5 (2 коррекции) = 20
    assert grammar["points"] == 20


@pytest.mark.asyncio
async def test_post_process_dialogue_awards_word_xp():
    """XP за новые слова: +3 за каждое (ветка vocabulary)."""
    from bot.db import UserRepository, get_conn, init_db
    from bot.handlers.common import post_process_dialogue
    from bot.services.progress_service import SkillProgressRepository

    import tempfile

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()
    await UserRepository(conn).create(12347, "A2", "testuser")

    message = AsyncMock()
    message.reply = AsyncMock()
    message.reply_voice = AsyncMock()

    result = {
        "reply": "Well done!",
        "rating": 5,
        "corrections": [],
        "skill_branch": "vocabulary",
        "new_words": [
            {"word": "beautiful", "translation": "красивый", "context": "Beautiful day"},
            {"word": "wonderful", "translation": "чудесный", "context": ""},
        ],
    }

    await post_process_dialogue(message, 12347, "Very nice day", result, conn)

    vocab = await SkillProgressRepository(conn).get_branch(12347, "vocabulary")
    # 10 (диалог) + 2*3 (2 слова) = 16
    assert vocab["points"] == 16


@pytest.mark.asyncio
async def test_skills_rank_and_challenge_commands_render_registered_user_dashboard():
    from bot.db import UserRepository, get_conn, init_db
    from bot.handlers.dialogue import cmd_challenge
    from bot.handlers.gamification import cmd_progress
    from bot.services.progress_service import SkillProgressRepository

    db_path = tempfile.mktemp(suffix=".db")
    await init_db(db_path)
    conn = await get_conn()
    await UserRepository(conn).create(12345, "A2", "testuser")
    await SkillProgressRepository(conn).award_points(12345, "speaking", 120)

    message = AsyncMock()
    message.from_user.id = 12345
    message.answer = AsyncMock()

    # cmd_progress handles /progress, /achievements, /rank
    message.text = "/rank"
    await cmd_progress(message)
    await cmd_challenge(message)

    responses = [call.args[0] for call in message.answer.call_args_list]
    assert "📊 <b>Дерево навыков</b>" in responses[0]
    assert "Speaking" in responses[0]
    assert "🏅 <b>Ранг:</b>" in responses[0]
    assert "Bronze" in responses[0]
    assert "🎯 <b>Weekly Challenge</b>" in responses[1]
    assert "0/7" in responses[1]
