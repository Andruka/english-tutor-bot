"""Deterministic CEFR placement test service.

The service builds a short, AI-free placement test from the existing curated
exercise TEMPLATE_BANKs and evaluates submitted answers with case-insensitive,
alias-aware scoring.
"""

from __future__ import annotations

import hashlib
import random
import re
import string
from dataclasses import dataclass, field
from typing import Any

from bot.exercise_generators.choice_generator import TEMPLATE_BANK as CHOICE_BANK
from bot.exercise_generators.gap_fill_generator import TEMPLATE_BANK as GAP_FILL_BANK
from bot.exercise_generators.translation_generator import TEMPLATE_BANK as TRANSLATION_BANK

CEFR_LEVELS: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")
DEFAULT_QUESTION_COUNT = 15
TOTAL_QUESTIONS = DEFAULT_QUESTION_COUNT


@dataclass
class PlacementQuestion:
    """Object representation used by the Telegram placement handler."""

    id: str
    level: str
    sentence: str
    choices: list[str]
    correct_answer: str
    explanation: str = ""


@dataclass
class PlacementTestResult:
    """In-memory placement-test session."""

    user_id: int
    questions: list[PlacementQuestion]
    answers: dict[str, bool] = field(default_factory=dict)
    correct_count: int = 0
    total_count: int = 0
    score: float = 0.0
    determined_level: str = "A1"
    level_scores: dict[str, float] = field(default_factory=dict)

_BANKS: tuple[tuple[str, dict[str, dict[str, list[dict[str, Any]]]]], ...] = (
    ("choice", CHOICE_BANK),
    ("gap_fill", GAP_FILL_BANK),
    ("translation", TRANSLATION_BANK),
)


def select_test_questions(
    user_id: int,
    seed: str | None = None,
    count: int = DEFAULT_QUESTION_COUNT,
) -> list[dict[str, Any]]:
    """Select deterministic placement questions from curated template banks.

    Selection depends on ``seed`` and ``count``. ``user_id`` is intentionally used
    only in the generated ``question_id`` so that two users with the same seed get
    the same prompts and correct answers, but their result payloads remain safely
    separable by id.
    """
    if count <= 0:
        return []

    rng = random.Random(seed if seed is not None else f"placement:{user_id}")
    candidates_by_level = {
        level: _templates_for_level(level) for level in CEFR_LEVELS
    }

    selected: list[dict[str, Any]] = []
    level_index = 0
    attempts = 0
    max_attempts = count * len(CEFR_LEVELS) * 4

    # Round-robin by level keeps the test balanced for both the default 15
    # questions and shorter test counts used by unit tests.
    while len(selected) < count and attempts < max_attempts:
        level = CEFR_LEVELS[level_index % len(CEFR_LEVELS)]
        level_index += 1
        attempts += 1

        candidates = candidates_by_level.get(level, [])
        if not candidates:
            continue

        candidate = rng.choice(candidates)
        if candidate in selected and len(selected) < sum(
            len(items) for items in candidates_by_level.values()
        ):
            continue
        selected.append(candidate)

    questions: list[dict[str, Any]] = []
    for order, candidate in enumerate(selected[:count], start=1):
        question = _build_question(candidate, user_id=user_id, order=order, seed=seed)
        questions.append(question)

    return questions


def evaluate_test(
    questions: list[dict[str, Any]],
    submitted_answers: dict[str, str],
) -> dict[str, Any]:
    """Evaluate placement-test answers and estimate CEFR level.

    Answers are matched against ``correct_answer.value`` and any aliases using
    case-insensitive normalization that ignores surrounding whitespace and final
    punctuation. Missing answers are counted as incorrect and preserved in the
    returned answer report with an empty ``submitted_answer``.
    """
    answers: dict[str, dict[str, Any]] = {}
    level_totals: dict[str, int] = {}
    level_correct: dict[str, int] = {}
    correct_answers = 0

    for question in questions:
        question_id = str(question["question_id"])
        level = str(question.get("level", ""))
        correct_answer = question.get("correct_answer") or {}
        expected_values = [correct_answer.get("value", "")]
        expected_values.extend(correct_answer.get("aliases") or [])
        submitted = submitted_answers.get(question_id, "")
        is_correct = _answer_matches(str(submitted), expected_values)

        level_totals[level] = level_totals.get(level, 0) + 1
        if is_correct:
            correct_answers += 1
            level_correct[level] = level_correct.get(level, 0) + 1
        else:
            level_correct.setdefault(level, 0)

        answers[question_id] = {
            "submitted_answer": submitted,
            "correct_answer": correct_answer.get("value", ""),
            "is_correct": is_correct,
        }

    total_questions = len(questions)
    score = round((correct_answers / total_questions) * 100) if total_questions else 0

    level_breakdown: dict[str, dict[str, int]] = {}
    for level in CEFR_LEVELS:
        total = level_totals.get(level, 0)
        if not total:
            continue
        correct = level_correct.get(level, 0)
        level_breakdown[level] = {
            "correct": correct,
            "total": total,
            "score": round((correct / total) * 100),
        }

    return {
        "total_questions": total_questions,
        "correct_answers": correct_answers,
        "score": score,
        "estimated_level": _estimate_level(score, level_breakdown),
        "answers": answers,
        "level_breakdown": level_breakdown,
    }


def run_placement_test(user_id: int, seed: str | None = None) -> PlacementTestResult:
    """Create an in-memory placement-test session for the bot handler."""
    question_dicts = select_test_questions(user_id=user_id, seed=seed)
    questions = [_to_placement_question(question) for question in question_dicts]
    return PlacementTestResult(
        user_id=user_id,
        questions=questions,
        total_count=len(questions),
    )


def finalize_test(result: PlacementTestResult) -> PlacementTestResult:
    """Score a bot-handler session and update its result object."""
    correct_answers = sum(1 for is_correct in result.answers.values() if is_correct)
    total_questions = len(result.questions)
    score_percent = round((correct_answers / total_questions) * 100) if total_questions else 0

    level_totals: dict[str, int] = {}
    level_correct: dict[str, int] = {}
    for question in result.questions:
        level_totals[question.level] = level_totals.get(question.level, 0) + 1
        if result.answers.get(question.id, False):
            level_correct[question.level] = level_correct.get(question.level, 0) + 1
        else:
            level_correct.setdefault(question.level, 0)

    level_breakdown = {
        level: {
            "correct": level_correct.get(level, 0),
            "total": total,
            "score": round((level_correct.get(level, 0) / total) * 100),
        }
        for level, total in level_totals.items()
    }

    result.correct_count = correct_answers
    result.total_count = total_questions
    result.score = score_percent / 100 if total_questions else 0.0
    result.determined_level = _estimate_level(score_percent, level_breakdown)
    result.level_scores = {
        level: values["score"] / 100 for level, values in level_breakdown.items()
    }
    return result


def _templates_for_level(level: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for exercise_type, bank in _BANKS:
        for topic in sorted(bank.get(level, {})):
            templates = bank[level][topic]
            for index, template in enumerate(templates):
                candidates.append(
                    {
                        "type": exercise_type,
                        "level": level,
                        "topic": topic,
                        "index": index,
                        "template": template,
                    }
                )
    return candidates


def _to_placement_question(question: dict[str, Any]) -> PlacementQuestion:
    payload = question.get("payload") or {}
    choices = payload.get("choices") or []
    if not choices:
        choices = _dedupe(
            [
                question["correct_answer"]["value"],
                *question["correct_answer"].get("aliases", []),
                "I don't know",
                "Skip",
            ]
        )[:4]
    return PlacementQuestion(
        id=question["question_id"],
        level=question["level"],
        sentence=question["prompt"],
        choices=list(choices),
        correct_answer=question["correct_answer"]["value"],
        explanation=question.get("explanation", ""),
    )


def _build_question(
    candidate: dict[str, Any],
    user_id: int,
    order: int,
    seed: str | None,
) -> dict[str, Any]:
    exercise_type = candidate["type"]
    level = candidate["level"]
    topic = candidate["topic"]
    template = candidate["template"]
    answer = str(template["answer"])
    aliases = list(template.get("aliases", []))

    if exercise_type == "choice":
        sentence = _blank_sentence(str(template["sentence"]), answer)
        choices = [answer]
        choices.extend(str(item["value"]) for item in template.get("distractors", []))
        choices = _dedupe(choices)[:4]
        random.Random(f"{seed}:{user_id}:{order}:choices").shuffle(choices)
        prompt = f"Choose the best word: {sentence}"
        payload = {"sentence": sentence, "choices": choices, "blank_index": 1}
    elif exercise_type == "gap_fill":
        sentence = _blank_sentence(str(template["sentence"]), answer)
        prompt = f"Complete the sentence: {sentence}"
        payload = {
            "sentence": sentence,
            "gap_count": 1,
            "possible_answers": _dedupe([answer, *template.get("distractors", [])]),
        }
    else:
        source_text = str(template.get("source_text", ""))
        prompt = f"Translate into English: {source_text}"
        payload = {
            "source_text": source_text,
            "source_locale": "ru",
            "target_locale": "en",
            "hints": list(template.get("hints", [])),
        }

    question_id = _question_id(
        user_id=user_id,
        order=order,
        seed=seed,
        exercise_type=exercise_type,
        level=level,
        topic=topic,
        target_item=str(template.get("target_item", answer)),
    )

    return {
        "order": order,
        "question_id": question_id,
        "type": exercise_type,
        "level": level,
        "topic": topic,
        "target_item": template.get("target_item", answer),
        "prompt": prompt,
        "payload": payload,
        "correct_answer": {
            "value": answer,
            "aliases": aliases,
            "case_sensitive": False,
        },
        "explanation": template.get("explanation", ""),
        "metadata": {
            "generation_source": "template",
            "template_bank": exercise_type,
        },
    }


def _question_id(
    *,
    user_id: int,
    order: int,
    seed: str | None,
    exercise_type: str,
    level: str,
    topic: str,
    target_item: str,
) -> str:
    raw = f"{user_id}:{seed}:{order}:{exercise_type}:{level}:{topic}:{target_item}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9]+", "-", target_item.lower()).strip("-")[:24]
    return f"pt-{order:02d}-{level.lower()}-{slug}-{digest}"


def _blank_sentence(sentence: str, answer: str) -> str:
    pattern = re.compile(rf"\b{re.escape(answer)}\b", flags=re.IGNORECASE)
    return pattern.sub("___", sentence, count=1)


def _answer_matches(submitted: str, expected_values: list[str]) -> bool:
    normalized_submitted = _normalize_answer(submitted)
    if not normalized_submitted:
        return False
    return normalized_submitted in {
        _normalize_answer(str(expected)) for expected in expected_values if expected
    }


def _normalize_answer(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.strip(string.whitespace + ".!?…")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _estimate_level(score: int, level_breakdown: dict[str, dict[str, int]]) -> str:
    # If a manually assembled test includes only a subset of levels, trust the
    # highest represented level with at least 50% mastery. This keeps diagnostics
    # like handcrafted alias tests meaningful.
    mastered = [
        level
        for level in CEFR_LEVELS
        if level_breakdown.get(level, {}).get("score", 0) >= 50
    ]
    if mastered and len(level_breakdown) < 4:
        return mastered[-1]

    if score >= 85:
        return "C1"
    if score >= 70:
        return "B2"
    if score >= 55:
        return "B1"
    if score >= 35:
        return "A2"
    return "A1"


def _dedupe(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = _normalize_answer(str(value))
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(str(value))
    return result


__all__ = [
    "PlacementQuestion",
    "PlacementTestResult",
    "TOTAL_QUESTIONS",
    "DEFAULT_QUESTION_COUNT",
    "select_test_questions",
    "evaluate_test",
    "run_placement_test",
    "finalize_test",
]
