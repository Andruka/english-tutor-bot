"""E206: базовая оценка произношения по voice-транскрипту."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_pronunciation_mock_score_has_rubric_tips_and_problem_sounds():
    """PronunciationService возвращает score 1-5 и конкретные советы."""
    from bot.services.pronunciation_service import PronunciationService

    service = PronunciationService(api_key="test_key")
    feedback = await service.score_transcript("I sink it is tree", level="A2")

    assert 1 <= feedback.score <= 5
    assert len(feedback.tips) in (1, 2)
    assert any("/θ/" in sound for sound in feedback.problem_sounds)
    assert "1–5" not in feedback.tips[0]


@pytest.mark.asyncio
async def test_pronunciation_parses_openrouter_json_response():
    """AI scoring парсится из JSON без реальных сетевых вызовов."""
    from bot.services.pronunciation_service import PronunciationService

    mock_payload = {
        "choices": [
            {
                "message": {
                    "content": '{"score": 4, "problem_sounds": ["/w/"], "tips": ["Round your lips for /w/."]}'
                }
            }
        ]
    }

    with patch("bot.services.pronunciation_service.httpx.AsyncClient") as client_cls:
        client = AsyncMock()
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = mock_payload
        client.post = AsyncMock(return_value=response)
        client.__aenter__.return_value = client
        client_cls.return_value = client

        service = PronunciationService(api_key="sk-test")
        feedback = await service.score_transcript("we went walking", level="B1")

    assert feedback.score == 4
    assert feedback.problem_sounds == ["/w/"]
    assert feedback.tips == ["Round your lips for /w/."]


@pytest.mark.asyncio
async def test_pronunciation_disabled_returns_none_and_skips_network():
    """Оценку можно отключить, и voice dialogue не обязан ждать scoring."""
    from bot.services.pronunciation_service import PronunciationService

    with patch.dict(os.environ, {"PRONUNCIATION_FEEDBACK_ENABLED": "0"}):
        service = PronunciationService(api_key="sk-test")
        with patch(
            "bot.services.pronunciation_service.httpx.AsyncClient"
        ) as client_cls:
            feedback = await service.score_transcript("hello world", level="A2")

    assert feedback is None
    client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_pronunciation_failure_soft_fallback():
    """Сбой AI scoring деградирует в мягкий fallback вместо падения voice flow."""
    from bot.services.pronunciation_service import PronunciationService

    with patch("bot.services.pronunciation_service.httpx.AsyncClient") as client_cls:
        client = AsyncMock()
        client.post = AsyncMock(side_effect=TimeoutError("boom"))
        client.__aenter__.return_value = client
        client_cls.return_value = client

        service = PronunciationService(api_key="sk-test")
        feedback = await service.score_transcript("hello world", level="A2")

    assert feedback.score == 3
    assert feedback.is_fallback is True
    assert feedback.problem_sounds
    assert feedback.tips


@pytest.mark.asyncio
async def test_pronunciation_feedback_persisted_and_read_back(tmp_path):
    """Pronunciation feedback сохраняется в БД для истории/аналитики."""
    from bot.db import (
        PronunciationFeedback,
        PronunciationFeedbackRepository,
        get_conn,
        init_db,
    )

    await init_db(str(tmp_path / "pronunciation.db"))
    conn = await get_conn()
    repo = PronunciationFeedbackRepository(conn)

    saved = await repo.create(
        PronunciationFeedback(
            user_id=42,
            transcript="I sink it is tree",
            score=2,
            problem_sounds=["/θ/", "/iː/"],
            tips=["Put your tongue lightly between your teeth for /θ/."],
        )
    )
    latest = await repo.get_latest(42)

    assert saved.feedback_id > 0
    assert latest.score == 2
    assert latest.problem_sounds == ["/θ/", "/iː/"]
    assert latest.tips == ["Put your tongue lightly between your teeth for /θ/."]
