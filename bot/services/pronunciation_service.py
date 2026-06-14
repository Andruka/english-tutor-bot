"""Pronunciation feedback: базовая AI-оценка произношения по voice transcript."""

import json
import os
from dataclasses import dataclass, field
from typing import Optional

import httpx

from bot.services.ai_service import OPENROUTER_URL, parse_ai_response

DEFAULT_PRONUNCIATION_MODEL = "openai/gpt-4o-mini"


@dataclass
class PronunciationAssessment:
    """Короткая оценка произношения для пользователя."""

    transcript: str
    score: int
    problem_sounds: list[str] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)
    is_fallback: bool = False


def is_pronunciation_enabled() -> bool:
    """Feature flag: PRONUNCIATION_FEEDBACK_ENABLED=0/false/off выключает scoring."""
    raw = os.getenv("PRONUNCIATION_FEEDBACK_ENABLED", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def build_pronunciation_prompt(transcript: str, level: str) -> str:
    """Промпт для MVP-scoring без фонемного аудиоанализа.

    Важно: у нас есть только STT transcript, поэтому это базовый эвристический
    feedback по вероятным проблемам произношения, а не точная фонемная разметка.
    """
    return f"""You are an English pronunciation coach. The learner level is {level}.
You only have the speech-to-text transcript, not the audio, so infer likely
pronunciation issues cautiously from words that beginners often confuse.

Transcript: {transcript!r}

Return ONLY valid JSON:
{{
  "score": 1-5,
  "problem_sounds": ["/θ/", "/w/"],
  "tips": ["one actionable tip", "second actionable tip"]
}}

Rules:
- score is an integer from 1 to 5;
- include 1-2 short actionable tips;
- include 1-3 likely problem sounds in IPA-like notation;
- do not mention grammar, vocabulary, or that you lack audio;
- keep tips simple for a Russian-speaking learner."""


def _normalize_assessment(
    raw: dict,
    transcript: str,
    *,
    is_fallback: bool = False,
) -> PronunciationAssessment:
    score_raw = raw.get("score", 3)
    try:
        score = int(score_raw)
    except (TypeError, ValueError):
        score = 3
    score = min(5, max(1, score))

    problem_sounds = raw.get("problem_sounds") or raw.get("problemSounds") or []
    if isinstance(problem_sounds, str):
        problem_sounds = [problem_sounds]
    problem_sounds = [
        str(sound).strip() for sound in problem_sounds if str(sound).strip()
    ]
    problem_sounds = problem_sounds[:3] or ["/θ/", "/ð/"]

    tips = raw.get("tips") or []
    if isinstance(tips, str):
        tips = [tips]
    tips = [str(tip).strip() for tip in tips if str(tip).strip()]
    tips = tips[:2] or [
        "Говори чуть медленнее и чётко выделяй окончания слов.",
        "Запиши фразу ещё раз и сравни с TTS-озвучкой бота.",
    ]

    return PronunciationAssessment(
        transcript=transcript,
        score=score,
        problem_sounds=problem_sounds,
        tips=tips,
        is_fallback=is_fallback,
    )


def _mock_assessment(transcript: str) -> PronunciationAssessment:
    text = transcript.lower()
    problem_sounds: list[str] = []
    tips: list[str] = []
    score = 4

    if "sink" in text or "tree" in text or "ting" in text:
        score = 2
        problem_sounds.append("/θ/")
        tips.append("Для /θ/ слегка поставь язык между зубами: think, three.")
    if "wery" in text or "vork" in text:
        score = min(score, 3)
        problem_sounds.append("/w/")
        tips.append("Для /w/ округляй губы, как в словах we, went, work.")
    if not problem_sounds:
        problem_sounds = ["/r/", "/w/"]
    if not tips:
        tips = [
            "Говори чуть медленнее и чётко выделяй ударный слог.",
            "Повтори короткую фразу 2–3 раза, сохраняя ровный темп.",
        ]

    return PronunciationAssessment(
        transcript=transcript,
        score=score,
        problem_sounds=problem_sounds[:3],
        tips=tips[:2],
    )


def fallback_assessment(transcript: str) -> PronunciationAssessment:
    """Мягкий fallback, если AI scoring недоступен."""
    return _normalize_assessment(
        {
            "score": 3,
            "problem_sounds": ["/θ/", "/w/"],
            "tips": [
                "Говори чуть медленнее и делай паузы между смысловыми фразами.",
                "Сравни своё произношение с TTS-ответом и повтори проблемную фразу.",
            ],
        },
        transcript,
        is_fallback=True,
    )


def format_pronunciation_feedback(feedback: PronunciationAssessment | None) -> str:
    """Форматирует feedback для HTML-сообщения Telegram."""
    if feedback is None:
        return ""
    sounds = ", ".join(feedback.problem_sounds)
    tip_lines = "\n".join(f"• {tip}" for tip in feedback.tips[:2])
    suffix = " (примерно)" if feedback.is_fallback else ""
    return (
        f"🗣 <b>Произношение</b>: {feedback.score}/5{suffix}\n"
        f"Звуки: {sounds}\n"
        f"Советы:\n{tip_lines}"
    )


class PronunciationService:
    """AI pronunciation scorer with feature flag and soft fallback."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_PRONUNCIATION_MODEL,
        enabled: Optional[bool] = None,
    ):
        self.api_key = (
            api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY", "")
        )
        self.model = model
        self.enabled = is_pronunciation_enabled() if enabled is None else enabled

    async def score_transcript(
        self,
        transcript: str,
        level: str = "A2",
    ) -> PronunciationAssessment | None:
        """Возвращает score 1-5 + 1-2 tips; не бросает ошибки наружу."""
        transcript = transcript.strip()
        if not self.enabled:
            return None
        if not transcript:
            return fallback_assessment(transcript)
        if self.api_key == "test_key":
            return _mock_assessment(transcript)
        if not self.api_key:
            return fallback_assessment(transcript)

        try:
            return await self._call_openrouter(transcript, level)
        except Exception:
            return fallback_assessment(transcript)

    async def _call_openrouter(
        self, transcript: str, level: str
    ) -> PronunciationAssessment:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/",
        }
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": build_pronunciation_prompt(transcript, level),
                }
            ],
            "temperature": 0.2,
            "max_tokens": 180,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        try:
            parsed = parse_ai_response(content)
        except ValueError:
            parsed = json.loads(content)
        return _normalize_assessment(parsed, transcript)
