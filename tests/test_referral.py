"""Тесты реферальной системы — service, db, handlers."""

import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import Message, User, Chat


def make_message(
    text: str,
    user_id: int = 1,
    username: str = "TestUser",
) -> Message:
    return Message(
        message_id=42,
        date=0,
        text=text,
        from_user=User(id=user_id, is_bot=False, first_name="Test", username=username),
        chat=Chat(id=user_id, type="private"),
        sender_chat=None,
    )


# ── Service tests ──────────────────────────────────────────────


class TestReferralService:
    """Тесты referral_service — parse и award."""

    def test_parse_referral_valid(self):
        from bot.services.referral_service import parse_referral

        assert parse_referral("ref_12345") == 12345
        assert parse_referral("ref_0") == 0

    def test_parse_referral_invalid(self):
        from bot.services.referral_service import parse_referral

        assert parse_referral("") is None
        assert parse_referral("foobar") is None
        assert parse_referral("ref_abc") is None
        assert parse_referral("ref_") is None

    def test_parse_referral_none(self):
        from bot.services.referral_service import parse_referral

        assert parse_referral(None) is None

    @pytest.mark.asyncio
    async def test_generate_referral_link(self):
        from bot.services.referral_service import generate_referral_link

        link = generate_referral_link(42)
        assert isinstance(link, str)
        assert "ref_42" in link
        assert "ai_your_english_tutor_bot" in link

    @pytest.mark.asyncio
    async def test_award_referral_bonus(self):
        from bot.services.referral_service import award_referral_bonus
        from bot.db import UserRepository, ReferralRewardRepository, init_db, get_conn

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        import bot.db as bdb

        old_db_path = bdb._db_path
        bdb._db_path = db_path
        await init_db(db_path)

        try:
            conn = await get_conn()
            repo = UserRepository(conn)
            reward_repo = ReferralRewardRepository(conn)

            await repo.create(user_id=100, level="A2", username="referrer")
            await repo.create(user_id=101, level="B1", username="referred")

            # Сначала привязываем реферера (как делает start.py)
            await repo.set_referrer(101, 100)
            bonus = await award_referral_bonus(repo, reward_repo, 101, 100)

            assert bonus["referrer_id"] == 100
            assert bonus["referred_id"] == 101
            assert bonus["referrer_days"] == 7
            assert bonus["referred_days"] == 3

            # Проверяем, что рефереру начислен Premium
            referrer = await repo.get(100)
            assert referrer is not None
            assert referrer.subscription is True
            assert referrer.subscription_tier == "premium"
            assert referrer.referral_count == 1  # set_referrer увеличил счётчик

            # Проверяем, что рефералу начислен Premium
            referred = await repo.get(101)
            assert referred is not None
            assert referred.subscription is True
            assert referred.subscription_tier == "premium"
            assert referred.referrer_id == 100

            # Проверяем запись в referral_rewards
            rows = await reward_repo.get_by_user(100)
            assert len(rows) == 1
            assert rows[0].referred_user_id == 101
            await conn.close()
        finally:
            bdb._db_path = old_db_path
            os.unlink(db_path)


# ── DB tests ───────────────────────────────────────────────────


class TestReferralDB:
    """Тесты UserRepository.set_referrer и ReferralRewardRepository."""

    @pytest.mark.asyncio
    async def test_set_referrer(self):
        from bot.db import UserRepository, ReferralRewardRepository, init_db, get_conn

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        import bot.db as bdb

        old_db_path = bdb._db_path
        bdb._db_path = db_path
        await init_db(db_path)

        try:
            conn = await get_conn()
            repo = UserRepository(conn)

            await repo.create(user_id=200, level="A2", username="user")
            await repo.create(user_id=201, level="B1", username="ref")

            await repo.set_referrer(200, 201)
            user = await repo.get(200)
            assert user is not None
            assert user.referrer_id == 201

            await conn.close()
        finally:
            bdb._db_path = old_db_path
            os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_set_referrer_self_reference(self):
        """Попытка установить себя реферером — игнорируется или не меняет referrer_id."""
        from bot.db import UserRepository, init_db, get_conn

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        import bot.db as bdb

        old_db_path = bdb._db_path
        bdb._db_path = db_path
        await init_db(db_path)

        try:
            conn = await get_conn()
            repo = UserRepository(conn)
            await repo.create(user_id=300, level="A2", username="self")

            with pytest.raises(ValueError, match="cannot refer self"):
                await repo.set_referrer(300, 300)

            await conn.close()
        finally:
            bdb._db_path = old_db_path
            os.unlink(db_path)

    @pytest.mark.asyncio
    async def test_referral_reward_crud(self):
        from bot.db import ReferralRewardRepository, init_db, get_conn

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        import bot.db as bdb

        old_db_path = bdb._db_path
        bdb._db_path = db_path
        await init_db(db_path)

        try:
            conn = await get_conn()
            repo = ReferralRewardRepository(conn)

            await repo.add_reward(user_id=202, referred_user_id=101, reward_value=7)

            rows = await repo.get_by_user(202)
            assert len(rows) == 1
            assert rows[0].referred_user_id == 101
            assert rows[0].reward_value == 7
            # referral_rewards stores reward_value, not referred_days
            assert rows[0].reward_value == 7
            assert rows[0].reward_type == "premium_days"  # schema DEFAULT

            rows_all = await repo.get_by_user(202)
            assert len(rows_all) == 1

            await conn.close()
        finally:
            bdb._db_path = old_db_path
            os.unlink(db_path)


# ── Handler tests ──────────────────────────────────────────────


class TestReferralHandlers:
    """Тесты хендлера /referral."""

    @patch.object(Message, "answer", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_cmd_referral(self, mock_answer):
        from bot.handlers.referral import cmd_referral
        from bot.db import UserRepository, init_db, get_conn

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        import bot.db as bdb

        old_db_path = bdb._db_path
        bdb._db_path = db_path
        await init_db(db_path)

        try:
            conn = await get_conn()
            repo = UserRepository(conn)
            await repo.create(user_id=500, level="A2", username="referrer")

            msg = make_message("/referral", user_id=500)

            with patch(
                "bot.handlers.referral.UserRepository", return_value=repo
            ):
                await cmd_referral(msg, command=SimpleNamespace(args=""))

            mock_answer.assert_called_once()
            text = mock_answer.call_args[0][0]
            assert "ref_500" in text
            assert "t.me/ai_your_english_tutor_bot" in text
            await conn.close()
        finally:
            bdb._db_path = old_db_path
            os.unlink(db_path)

    @patch.object(Message, "answer", new_callable=AsyncMock)
    @pytest.mark.asyncio
    async def test_cmd_referral_new_user(self, mock_answer):
        """Пользователь без записи в БД получает предложение зарегистрироваться."""
        from bot.handlers.referral import cmd_referral
        from bot.db import init_db, get_conn

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        import bot.db as bdb

        old_db_path = bdb._db_path
        bdb._db_path = db_path
        await init_db(db_path)

        try:
            msg = make_message("/referral", user_id=999)
            await cmd_referral(msg, command=SimpleNamespace(args=None))

            mock_answer.assert_called_once()
            text = mock_answer.call_args[0][0]
            assert "зарегистрироваться" in text.lower() or "/start" in text
        finally:
            bdb._db_path = old_db_path
            os.unlink(db_path)