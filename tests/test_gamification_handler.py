"""Тесты для handler геймификации (/progress, /achievements, /rank, gami_*)."""

from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from bot.handlers.gamification import (
    build_achievements_text,
    build_progress_text,
    _progress_bar,
)


class TestProgressBar:
    def test_full_bar(self):
        assert "████████████ 100/100" == _progress_bar(100, 100, 12)

    def test_half_bar(self):
        result = _progress_bar(50, 100, 12)
        assert "██████" in result
        assert "░░░░░░" in result
        assert "50/100" in result

    def test_empty_bar(self):
        assert "░░░░░░░░░░░░ 0/100" == _progress_bar(0, 100, 12)

    def test_custom_total(self):
        result = _progress_bar(3, 7, 14)
        assert "3/7" in result

    def test_capped_at_total(self):
        assert "████████████ 100/100" == _progress_bar(200, 100, 12)


class TestBuildProgressText:
    SAMPLE_TREE = [
        {"icon": "📚", "name": "Vocabulary", "points": 120},
        {"icon": "🧩", "name": "Grammar", "points": 45},
        {"icon": "🗣", "name": "Speaking", "points": 0},
        {"icon": "🎧", "name": "Listening", "points": 10},
        {"icon": "✍️", "name": "Writing", "points": 0},
    ]
    SAMPLE_CHALLENGE = {"goal": 7, "progress": 5, "completed": False}

    def test_basic_structure(self):
        text = build_progress_text(
            user_level="B1",
            streak=5,
            dialogues_today=2,
            total_dialogues=47,
            skill_tree=self.SAMPLE_TREE,
            rank_name="Bronze",
            weekly_challenge=self.SAMPLE_CHALLENGE,
            achievement_count=3,
            total_achievements=12,
        )
        assert "B1" in text
        assert "Bronze" in text
        assert "5 дней" in text
        assert "47" in text
        assert "2" in text
        assert "3 из 12" in text
        assert "5/7" in text  # weekly challenge progress
        assert "Vocabulary" in text
        assert "Grammar" in text

    def test_completed_challenge(self):
        challenge = {"goal": 7, "progress": 7, "completed": True}
        text = build_progress_text(
            user_level="C1",
            streak=14,
            dialogues_today=0,
            total_dialogues=200,
            skill_tree=self.SAMPLE_TREE,
            rank_name="Gold",
            weekly_challenge=challenge,
            achievement_count=6,
            total_achievements=12,
        )
        assert "C1" in text
        assert "Gold" in text
        assert "Выполнен!" in text
        assert "14 дней" in text

    def test_long_streak_emoji(self):
        text = build_progress_text(
            user_level="A2",
            streak=30,
            dialogues_today=1,
            total_dialogues=500,
            skill_tree=self.SAMPLE_TREE,
            rank_name="Platinum",
            weekly_challenge=self.SAMPLE_CHALLENGE,
            achievement_count=10,
            total_achievements=12,
        )
        assert "🔥" in text
        assert "Platinum" in text

    def test_medium_streak_emoji(self):
        text = build_progress_text(
            user_level="A2",
            streak=3,
            dialogues_today=1,
            total_dialogues=10,
            skill_tree=self.SAMPLE_TREE,
            rank_name="Silver",
            weekly_challenge=self.SAMPLE_CHALLENGE,
            achievement_count=1,
            total_achievements=12,
        )
        assert "⭐" in text

    def test_no_achievements(self):
        challenge = {"goal": 7, "progress": 0, "completed": False}
        text = build_progress_text(
            user_level="A1",
            streak=0,
            dialogues_today=0,
            total_dialogues=0,
            skill_tree=self.SAMPLE_TREE,
            rank_name="Bronze",
            weekly_challenge=challenge,
            achievement_count=0,
            total_achievements=12,
        )
        assert "0 из 12" in text
        assert "0/7" in text


class TestBuildAchievementsText:
    SAMPLE_ACHIEVEMENTS = [
        {
            "achievement_id": "first_lesson",
            "name": "🎓 Первый урок",
            "desc": "Заверши первый диалог с репетитором",
            "earned_at": "2026-01-15",
        },
        {
            "achievement_id": "streak_7",
            "name": "🔥 Неделя практики",
            "desc": "Занимайся 7 дней подряд",
            "earned_at": "2026-01-22",
        },
    ]

    def test_shows_earned_achievements(self):
        text = build_achievements_text(self.SAMPLE_ACHIEVEMENTS, 2)
        assert "2 из 11" in text
        assert "✅ 🎓 Первый урок" in text
        assert "✅ 🔥 Неделя практики" in text

    def test_shows_locked_achievements(self):
        text = build_achievements_text(self.SAMPLE_ACHIEVEMENTS, 2)
        assert "🔒 ⚡ Две недели" in text
        assert "🔒 💪 Месяц практики" in text
        assert "🔒 💬 50 диалогов" in text

    def test_empty_achievements(self):
        text = build_achievements_text([], 0)
        assert "0 из 11" in text
        assert "🔒" in text
        assert "✅" not in text

    def test_all_achievements(self):
        """Все 11 ачивок получены."""
        all_achs = [
            {"achievement_id": ach_id, "name": "", "desc": "", "earned_at": "2026-01-01"}
            for ach_id in [
                "first_lesson", "streak_7", "streak_14", "streak_30",
                "dialogues_50", "dialogues_100", "dialogues_500",
                "first_correction", "all_corrections_accepted",
                "weekly_challenge", "skill_tree_started",
            ]
        ]
        text = build_achievements_text(all_achs, 11)
        assert "11 из 11" in text
        assert text.count("✅") == 11
        assert "🔒" not in text


@pytest.mark.asyncio
@patch("bot.handlers.gamification.get_conn")
class TestGamificationCommands:
    """Тестирует команды /progress, /achievements, /rank."""

    @pytest.fixture
    def mock_user_data(self):
        """Возвращает моковые данные пользователя."""
        user = MagicMock()
        user.level = "B1"
        user.streak = 5
        user.dialogues_today = 2
        user.subscription = True
        return user

    @pytest.fixture
    def mock_conn(self):
        conn = AsyncMock()
        cursor = AsyncMock()
        cursor.fetchone = AsyncMock(return_value=None)
        cursor.fetchall = AsyncMock(return_value=[])
        conn.execute = AsyncMock(return_value=cursor)
        conn.__aenter__ = AsyncMock(return_value=conn)
        conn.__aexit__ = AsyncMock(return_value=None)
        return conn

    async def test_progress_command_sends_message(self, mock_get_conn, mock_user_data, mock_conn):
        """Проверяет, что /progress отправляет сообщение с данными."""
        from aiogram.types import Message, User as TgUser

        mock_get_conn.return_value = mock_conn

        with patch("bot.handlers.gamification.UserRepository") as mock_user_repo, \
             patch("bot.handlers.gamification.AchievementRepository") as mock_ach_repo, \
             patch("bot.handlers.gamification.SkillProgressRepository") as mock_skill_repo, \
             patch("bot.handlers.gamification.WeeklyChallengeRepository") as mock_chal_repo, \
             patch("bot.handlers.gamification.DialogueRepository") as mock_dial_repo:

            repo_instance = AsyncMock()
            repo_instance.get = AsyncMock(return_value=mock_user_data)
            mock_user_repo.return_value = repo_instance

            ach_instance = AsyncMock()
            ach_instance.get_all = AsyncMock(return_value=[])
            mock_ach_repo.return_value = ach_instance

            skill_instance = AsyncMock()
            skill_instance.get_tree = AsyncMock(return_value=[
                {"icon": "📚", "name": "Vocabulary", "points": 50},
                {"icon": "🧩", "name": "Grammar", "points": 20},
                {"icon": "🗣", "name": "Speaking", "points": 0},
                {"icon": "🎧", "name": "Listening", "points": 0},
                {"icon": "✍️", "name": "Writing", "points": 0},
            ])
            mock_skill_repo.return_value = skill_instance

            chal_instance = AsyncMock()
            chal_instance.get_or_create_current = AsyncMock(
                return_value={"goal": 7, "progress": 3, "completed": False}
            )
            mock_chal_repo.return_value = chal_instance

            dial_instance = AsyncMock()
            dial_instance.count = AsyncMock(return_value=42)
            mock_dial_repo.return_value = dial_instance

            from bot.handlers.gamification import cmd_progress

            message = AsyncMock(spec=Message)
            message.from_user = MagicMock(spec=TgUser)
            message.from_user.id = 12345
            message.text = "/progress"
            message.answer = AsyncMock()

            await cmd_progress(message)

            message.answer.assert_awaited_once()
            args, kwargs = message.answer.await_args
            text = args[0]
            assert "B1" in text
            assert "Bronze" in text
            assert "42" in text
            assert "3/7" in text
            assert "0 из 11" in text

    async def test_achievements_command_shows_achievements(self, mock_get_conn, mock_user_data, mock_conn):
        """Проверяет, что /achievements показывает достижения."""
        from aiogram.types import Message, User as TgUser

        mock_get_conn.return_value = mock_conn

        with patch("bot.handlers.gamification.UserRepository") as mock_user_repo, \
             patch("bot.handlers.gamification.AchievementRepository") as mock_ach_repo, \
             patch("bot.handlers.gamification.SkillProgressRepository") as mock_skill_repo, \
             patch("bot.handlers.gamification.WeeklyChallengeRepository") as mock_chal_repo, \
             patch("bot.handlers.gamification.DialogueRepository") as mock_dial_repo:

            repo_instance = AsyncMock()
            repo_instance.get = AsyncMock(return_value=mock_user_data)
            mock_user_repo.return_value = repo_instance

            ach_instance = AsyncMock()
            ach_instance.get_all = AsyncMock(
                return_value=[
                    {"achievement_id": "first_lesson", "name": "🎓 Первый урок",
                     "desc": "Заверши первый диалог", "earned_at": "2026-01-15"},
                ]
            )
            mock_ach_repo.return_value = ach_instance

            skill_instance = AsyncMock()
            skill_instance.get_tree = AsyncMock(return_value=[])
            mock_skill_repo.return_value = skill_instance

            chal_instance = AsyncMock()
            chal_instance.get_or_create_current = AsyncMock(
                return_value={"goal": 7, "progress": 0, "completed": False}
            )
            mock_chal_repo.return_value = chal_instance

            dial_instance = AsyncMock()
            dial_instance.count = AsyncMock(return_value=0)
            mock_dial_repo.return_value = dial_instance

            from bot.handlers.gamification import cmd_progress

            message = AsyncMock(spec=Message)
            message.from_user = MagicMock(spec=TgUser)
            message.from_user.id = 12345
            message.text = "/achievements"
            message.answer = AsyncMock()

            await cmd_progress(message)

            message.answer.assert_awaited_once()
            args, kwargs = message.answer.await_args
            text = args[0]
            assert "1 из 11" in text
            assert "✅" in text
            assert "🔒" in text