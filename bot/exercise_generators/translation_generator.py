"""Deterministic translation exercise generator for the English tutor bot.

This module mirrors the standalone implementation style used by
``gap_fill_generator.py``: no non-stdlib runtime dependencies, deterministic
seeded template selection, canonical exercise dictionaries, and local validation.
It is suitable as a v1 local fallback and as the stable contract for future bot
or AI-hybrid integration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import random
import re
import time
from typing import Any, Literal

CEFRLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
SkillFocus = Literal[
    "vocabulary", "grammar", "collocation", "listening_recall", "mixed"
]

ALLOWED_LEVELS: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")
ALLOWED_TOPICS: tuple[str, ...] = (
    "introduction",
    "family",
    "daily_routine",
    "hobbies",
    "travel",
    "food",
    "work",
    "weather",
)

LEVEL_WORD_LIMITS: dict[str, int] = {
    "A1": 8,
    "A2": 10,
    "B1": 16,
    "B2": 24,
    "C1": 32,
    "C2": 36,
}

LEVEL_DIFFICULTY: dict[str, int] = {
    "A1": 1,
    "A2": 2,
    "B1": 3,
    "B2": 4,
    "C1": 5,
    "C2": 6,
}

LEVEL_GRAMMAR_TAGS: dict[str, list[str]] = {
    "A1": ["present_simple", "be", "have"],
    "A2": ["past_simple", "going_to_future", "comparatives"],
    "B1": ["present_perfect", "modals", "conditionals"],
    "B2": ["passive_voice", "reported_speech", "discourse_markers"],
    "C1": ["advanced_modality", "inversion", "register_control"],
    "C2": ["style_shift", "ellipsis", "nuance"],
}

# Curated translation templates.  ``source_text`` is Russian because the current
# bot locale is Russian-first; the expected answer and aliases are English.
TEMPLATE_BANK: dict[str, dict[str, list[dict[str, Any]]]] = {
    "A1": {
        "family": [
            {
                "target_item": "mother",
                "source_text": "Моя мама дома.",
                "answer": "My mother is at home.",
                "aliases": [
                    "My mum is at home.",
                    "My mom is home.",
                    "My mother is home.",
                ],
                "hints": ["mother = мама", "Use 'is' with one person."],
                "explanation": "At A1, use 'my' + family word + 'is' for one person.",
                "vocabulary_tags": ["family"],
                "required_content_words": ["my", "mother", "home"],
            },
            {
                "target_item": "father",
                "source_text": "У моего папы есть машина.",
                "answer": "My father has a car.",
                "aliases": ["My dad has a car."],
                "hints": ["father = папа", "Use 'has' with he/she/it."],
                "explanation": "Use 'has' for one person: my father has.",
                "vocabulary_tags": ["family"],
                "required_content_words": ["father", "has", "car"],
            },
            {
                "target_item": "sister",
                "source_text": "Моей сестре десять лет.",
                "answer": "My sister is ten.",
                "aliases": ["My sister is ten years old."],
                "hints": ["sister = сестра", "Say age with 'is'."],
                "explanation": "In English, age uses 'be': my sister is ten.",
                "vocabulary_tags": ["family"],
                "required_content_words": ["sister", "ten"],
            },
            {
                "target_item": "brother",
                "source_text": "Мой брат любит футбол.",
                "answer": "My brother likes football.",
                "aliases": ["My brother likes soccer."],
                "hints": ["brother = брат", "Add -s: he likes."],
                "explanation": "Use present simple with -s for he: likes.",
                "vocabulary_tags": ["family", "hobbies"],
                "grammar_tags": ["present_simple"],
                "required_content_words": ["brother", "likes", "football"],
            },
        ],
        "travel": [
            {
                "target_item": "ticket",
                "source_text": "Мне нужен билет на автобус.",
                "answer": "I need a ticket for the bus.",
                "aliases": ["I need a bus ticket."],
                "hints": ["ticket = билет", "Use 'need' after I."],
                "explanation": "'I need a ticket' is a simple way to say what you must have before travel.",
                "vocabulary_tags": ["travel", "transport"],
                "required_content_words": ["need", "ticket", "bus"],
            }
        ],
    },
    "A2": {
        "travel": [
            {
                "target_item": "airport",
                "source_text": "Мы приехали в аэропорт рано.",
                "answer": "We arrived at the airport early.",
                "aliases": ["We got to the airport early."],
                "hints": ["airport = аэропорт", "Use past simple: arrived."],
                "explanation": "Use past simple for a finished travel action: arrived.",
                "vocabulary_tags": ["travel", "places"],
                "grammar_tags": ["past_simple"],
                "required_content_words": ["arrived", "airport", "early"],
            },
            {
                "target_item": "going_to_future",
                "source_text": "Завтра я собираюсь купить билет.",
                "answer": "Tomorrow I am going to buy a ticket.",
                "aliases": [
                    "I am going to buy a ticket tomorrow.",
                    "I'm going to buy a ticket tomorrow.",
                ],
                "hints": ["собираюсь = am going to", "Put the verb after 'to'."],
                "explanation": "Use 'be going to' for a planned future action.",
                "vocabulary_tags": ["travel", "planning"],
                "grammar_tags": ["going_to_future"],
                "required_content_words": ["going", "buy", "ticket", "tomorrow"],
            },
        ],
        "food": [
            {
                "target_item": "breakfast",
                "source_text": "Я позавтракал перед школой.",
                "answer": "I had breakfast before school.",
                "aliases": ["I ate breakfast before school."],
                "hints": ["breakfast = завтрак", "Use past simple: had."],
                "explanation": "'Had breakfast' is a natural collocation for eating breakfast.",
                "vocabulary_tags": ["food", "meals"],
                "grammar_tags": ["past_simple"],
                "required_content_words": ["had", "breakfast", "school"],
            }
        ],
    },
    "B1": {
        "work": [
            {
                "target_item": "present_perfect",
                "source_text": "Я работаю здесь с 2021 года.",
                "answer": "I have worked here since 2021.",
                "aliases": ["I've worked here since 2021."],
                "hints": [
                    "Use present perfect with 'since'.",
                    "I have worked = я работаю с прошлого момента до сих пор.",
                ],
                "explanation": "Use present perfect with 'since' to connect a past start time with the present.",
                "vocabulary_tags": ["work"],
                "grammar_tags": ["present_perfect"],
                "required_content_words": ["have", "worked", "since", "2021"],
            },
            {
                "target_item": "deadline",
                "source_text": "Мы должны закончить отчет до срока.",
                "answer": "We must finish the report before the deadline.",
                "aliases": ["We have to finish the report before the deadline."],
                "hints": ["deadline = крайний срок", "must = должны"],
                "explanation": "A deadline is the latest time when work must be finished.",
                "vocabulary_tags": ["work", "projects"],
                "grammar_tags": ["modals"],
                "required_content_words": ["finish", "report", "deadline"],
            },
        ]
    },
    "B2": {
        "work": [
            {
                "target_item": "passive_voice",
                "source_text": "Решение было принято после долгого обсуждения.",
                "answer": "The decision was made after a long discussion.",
                "aliases": ["The decision was taken after a long discussion."],
                "hints": [
                    "Use passive voice: was + past participle.",
                    "decision = решение",
                ],
                "explanation": "Use passive voice when the result matters more than who made the decision.",
                "vocabulary_tags": ["work", "meetings"],
                "grammar_tags": ["passive_voice"],
                "required_content_words": ["decision", "was", "made", "discussion"],
            }
        ]
    },
    "C1": {
        "work": [
            {
                "target_item": "register_control",
                "source_text": "Не могли бы вы уточнить сроки, прежде чем мы приступим?",
                "answer": "Could you clarify the timeline before we proceed?",
                "aliases": ["Could you clarify the deadlines before we proceed?"],
                "hints": ["Use polite formal register.", "clarify = уточнить"],
                "explanation": "This phrasing uses a formal, polite request suitable for professional contexts.",
                "vocabulary_tags": ["work", "register"],
                "grammar_tags": ["advanced_modality", "register_control"],
                "required_content_words": ["clarify", "timeline", "proceed"],
            }
        ]
    },
    "C2": {
        "work": [
            {
                "target_item": "nuance",
                "source_text": "В его ответе был едва заметный оттенок сомнения.",
                "answer": "There was a barely perceptible nuance of doubt in his reply.",
                "aliases": ["His reply carried a barely perceptible nuance of doubt."],
                "hints": [
                    "nuance = оттенок смысла",
                    "Use precise abstract vocabulary.",
                ],
                "explanation": "C2 translation can preserve subtle meaning with precise lexis such as 'barely perceptible nuance'.",
                "vocabulary_tags": ["work", "style"],
                "grammar_tags": ["nuance"],
                "required_content_words": ["nuance", "doubt", "reply"],
            }
        ]
    },
}

GENERIC_FALLBACKS: dict[str, dict[str, Any]] = {
    "A1": {
        "target_item": "introduction",
        "source_text": "Я студент.",
        "answer": "I am a student.",
        "aliases": ["I'm a student."],
        "hints": ["I am = я есть/я являюсь", "student = студент"],
        "explanation": "Use 'am' with I.",
        "vocabulary_tags": ["introduction"],
        "grammar_tags": ["be"],
        "required_content_words": ["student"],
    },
    "A2": {
        "target_item": "past_simple",
        "source_text": "Вчера я ходил в парк.",
        "answer": "Yesterday I went to the park.",
        "aliases": ["I went to the park yesterday."],
        "hints": ["yesterday = вчера", "went = ходил/пошел"],
        "explanation": "Use past simple for a finished action yesterday.",
        "vocabulary_tags": ["daily_routine"],
        "grammar_tags": ["past_simple"],
        "required_content_words": ["yesterday", "went", "park"],
    },
    "B1": {
        "target_item": "advice",
        "source_text": "Тебе следует попросить помощи, если задача неясна.",
        "answer": "You should ask for help if the task is unclear.",
        "aliases": ["You should ask for help if the task isn't clear."],
        "hints": ["should = следует", "if = если"],
        "explanation": "Use 'should' to give advice.",
        "vocabulary_tags": ["work"],
        "grammar_tags": ["modals"],
        "required_content_words": ["should", "ask", "help", "unclear"],
    },
    "B2": {
        "target_item": "contrast_clause",
        "source_text": "Хотя встреча была долгой, решение оказалось полезным.",
        "answer": "Although the meeting was long, the decision was useful.",
        "aliases": ["Though the meeting was long, the decision was useful."],
        "hints": ["although = хотя", "Use a contrast clause."],
        "explanation": "'Although' introduces a contrast clause.",
        "vocabulary_tags": ["work"],
        "grammar_tags": ["complex_clause"],
        "required_content_words": ["although", "meeting", "decision", "useful"],
    },
    "C1": {
        "target_item": "inversion",
        "source_text": "Если бы я знал о рисках, я бы выбрал другой маршрут.",
        "answer": "Had I known the risks, I would have chosen another route.",
        "aliases": ["If I had known the risks, I would have chosen another route."],
        "hints": ["Advanced inversion: Had I known...", "chosen = выбрал"],
        "explanation": "This is inversion in a third conditional structure.",
        "vocabulary_tags": ["travel"],
        "grammar_tags": ["inversion", "conditionals"],
        "required_content_words": ["known", "risks", "chosen", "route"],
    },
    "C2": {
        "target_item": "style_shift",
        "source_text": "Ее замечание прозвучало непринужденно, но было тщательно выверено.",
        "answer": "Her remark sounded casual, yet it was carefully calibrated.",
        "aliases": ["Her comment sounded casual, yet it was carefully calibrated."],
        "hints": ["calibrated = carefully adjusted", "Preserve the contrast in tone."],
        "explanation": "C2 translation can preserve style and tone, not only literal meaning.",
        "vocabulary_tags": ["style"],
        "grammar_tags": ["style_shift"],
        "required_content_words": ["remark", "casual", "calibrated"],
    },
}


@dataclass(frozen=True)
class ExerciseRequest:
    user_id: int
    level: str
    topic: str
    exercise_type: str = "translation"
    skill_focus: str = "mixed"
    target_item: str | None = None
    source: str = "template"
    locale: str = "ru"
    seed: str | None = None
    difficulty_offset: int = 0
    history: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.level not in ALLOWED_LEVELS:
            raise ValueError(f"unknown CEFR level: {self.level}")
        if self.topic not in ALLOWED_TOPICS:
            raise ValueError(f"unknown topic: {self.topic}")
        if self.exercise_type != "translation":
            raise ValueError(
                "translation_generator only supports exercise_type='translation'"
            )
        if self.skill_focus not in {
            "vocabulary",
            "grammar",
            "collocation",
            "listening_recall",
            "mixed",
        }:
            raise ValueError(f"unknown skill_focus: {self.skill_focus}")
        if self.difficulty_offset < -1 or self.difficulty_offset > 1:
            raise ValueError("difficulty_offset must be between -1 and 1")
        if self.locale != "ru":
            raise ValueError("translation_generator currently supports locale='ru'")


def generate_translation_exercise(
    request: ExerciseRequest | dict[str, Any],
) -> dict[str, Any]:
    """Generate a deterministic translation exercise.

    The same request, including ``user_id``, returns the same complete exercise
    when ``seed`` is provided.  Changing only ``user_id`` changes the deterministic
    ``exercise_id`` while preserving the selected template.
    """

    if isinstance(request, dict):
        request = ExerciseRequest(**request)

    template = _select_template(request)
    grammar_tags = template.get("grammar_tags") or _default_grammar_tags(
        request, template
    )
    vocabulary_tags = template.get("vocabulary_tags", [request.topic])

    exercise = {
        "exercise_id": _exercise_id(request),
        "schema_version": "1.0",
        "type": "translation",
        "level": request.level,
        "topic": request.topic,
        "skill_focus": request.skill_focus,
        "target_item": template["target_item"],
        "prompt": f"Translate into English: {template['source_text']}",
        "payload": {
            "source_text": template["source_text"],
            "source_locale": request.locale,
            "target_locale": "en",
            "hints": list(template.get("hints", [])),
            "required_content_words": list(template.get("required_content_words", [])),
        },
        "correct_answer": {
            "value": template["answer"],
            "aliases": list(template.get("aliases", [])),
            "case_sensitive": False,
        },
        "distractors": [],
        "explanation": template["explanation"],
        "feedback": _feedback(template, request.locale),
        "metadata": {
            "estimated_time_seconds": _estimated_time(request.level),
            "difficulty": LEVEL_DIFFICULTY[request.level],
            "adapted_grammar_level": _adapted_level(
                request.level, request.difficulty_offset
            ),
            "grammar_tags": grammar_tags,
            "vocabulary_tags": vocabulary_tags,
            "generation_source": "template",
            "review_required": False,
        },
    }

    errors = validate_translation_exercise(exercise)
    if errors:
        raise ValueError("invalid generated translation exercise: " + "; ".join(errors))
    return exercise


def validate_translation_exercise(exercise: dict[str, Any]) -> list[str]:
    """Return validation errors for a generated translation exercise."""

    errors: list[str] = []
    payload = exercise.get("payload") or {}
    correct = exercise.get("correct_answer") or {}
    source_text = str(payload.get("source_text", ""))
    answer = str(correct.get("value", "")).strip()
    aliases = correct.get("aliases") or []
    hints = payload.get("hints") or []
    prompt = str(exercise.get("prompt", ""))

    if exercise.get("type") != "translation":
        errors.append("type must be translation")
    if exercise.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    if exercise.get("level") not in ALLOWED_LEVELS:
        errors.append("level must be a supported CEFR level")
    if exercise.get("topic") not in ALLOWED_TOPICS:
        errors.append("topic must be an allowed topic")
    if not prompt.startswith("Translate into English: "):
        errors.append("prompt must ask to translate into English")
    if source_text and source_text not in prompt:
        errors.append("prompt must include source_text")
    if payload.get("source_locale") != "ru":
        errors.append("source_locale must be ru")
    if payload.get("target_locale") != "en":
        errors.append("target_locale must be en")
    if not source_text:
        errors.append("source_text is required")
    elif not _looks_russian(source_text):
        errors.append("source_text must look like Russian text for locale ru")
    if not answer:
        errors.append("correct answer value is required")
    elif not _looks_english(answer):
        errors.append("correct answer must look like English text")
    if correct.get("case_sensitive") is not False:
        errors.append("correct answer must be case-insensitive")
    if not isinstance(aliases, list):
        errors.append("aliases must be a list")
    if not isinstance(hints, list) or not hints:
        errors.append("payload hints must contain at least one hint")
    if exercise.get("distractors") not in ([], None):
        errors.append("translation exercises must not include distractors")

    normalized_answers = {_normalize_answer(answer)}
    for alias in aliases if isinstance(aliases, list) else []:
        normalized_alias = _normalize_answer(str(alias))
        if normalized_alias in normalized_answers:
            errors.append("aliases must be unique after normalization")
            break
        normalized_answers.add(normalized_alias)
        if not _looks_english(str(alias)):
            errors.append("aliases must look like English text")
            break

    level = str(exercise.get("level", ""))
    if level in LEVEL_WORD_LIMITS and _word_count(answer) > LEVEL_WORD_LIMITS[level]:
        errors.append("correct answer exceeds CEFR word limit")

    metadata = exercise.get("metadata") or {}
    if metadata.get("difficulty") != LEVEL_DIFFICULTY.get(level):
        errors.append("metadata difficulty must match displayed CEFR level")
    if metadata.get("generation_source") not in {"template", "hybrid", "ai"}:
        errors.append("metadata generation_source must be template, hybrid, or ai")
    return errors


def _select_template(request: ExerciseRequest) -> dict[str, Any]:
    candidates = list(TEMPLATE_BANK.get(request.level, {}).get(request.topic, []))
    if not candidates:
        candidates = [GENERIC_FALLBACKS[request.level]]

    if request.target_item:
        explicit = [
            item for item in candidates if item["target_item"] == request.target_item
        ]
        if not explicit:
            explicit = [
                item
                for item in _all_level_candidates(request.level)
                if item["target_item"] == request.target_item
            ]
        if explicit:
            return dict(explicit[0])
        raise ValueError(
            f"target_item {request.target_item!r} is not available for level {request.level}"
        )

    weak_categories = set(request.history.get("weak_categories", []))
    if weak_categories:
        weak_matches = [
            item
            for item in candidates
            if item["target_item"] in weak_categories
            or weak_categories.intersection(item.get("grammar_tags", []))
            or weak_categories.intersection(item.get("vocabulary_tags", []))
        ]
        if weak_matches:
            return dict(_seeded_choice(weak_matches, request))

    recent = set(request.history.get("recent_target_items", []))
    fresh = [item for item in candidates if item["target_item"] not in recent]
    selectable = fresh or candidates
    return dict(_seeded_choice(selectable, request))


def _all_level_candidates(level: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for topic_candidates in TEMPLATE_BANK.get(level, {}).values():
        output.extend(topic_candidates)
    output.append(GENERIC_FALLBACKS[level])
    return output


def _seeded_choice(
    candidates: list[dict[str, Any]], request: ExerciseRequest
) -> dict[str, Any]:
    ordered = sorted(candidates, key=lambda item: item["target_item"])
    rng = _rng(request, salt="select")
    return ordered[rng.randrange(len(ordered))]


def _default_grammar_tags(
    request: ExerciseRequest, template: dict[str, Any]
) -> list[str]:
    if request.skill_focus == "grammar":
        return [template["target_item"]]
    return LEVEL_GRAMMAR_TAGS.get(
        _adapted_level(request.level, request.difficulty_offset), []
    )[:1]


def _feedback(template: dict[str, Any], locale: str) -> dict[str, str]:
    answer = template["answer"]
    if locale == "ru":
        return {
            "correct": f"Верно: {answer}",
            "incorrect": f"Почти. Возможный ответ: {answer}. {template['explanation']}",
        }
    return {
        "correct": f"Correct: {answer}",
        "incorrect": f"Not quite. A possible answer is {answer}. {template['explanation']}",
    }


def _estimated_time(level: str) -> int:
    return 30 if level in {"A1", "A2"} else 45 if level in {"B1", "B2"} else 60


def _adapted_level(level: str, offset: int) -> str:
    index = ALLOWED_LEVELS.index(level)
    adapted_index = max(0, min(len(ALLOWED_LEVELS) - 1, index + offset))
    return ALLOWED_LEVELS[adapted_index]


def _exercise_id(request: ExerciseRequest) -> str:
    if request.seed is None:
        seed_material = f"{request.user_id}:{request.level}:{request.topic}:translation:{time.time_ns()}"
    else:
        seed_material = (
            f"{request.user_id}:{request.level}:{request.topic}:{request.skill_focus}:"
            f"{request.target_item}:{request.seed}:translation"
        )
    digest = hashlib.sha1(seed_material.encode("utf-8")).hexdigest()[:16].upper()
    return f"ex_{digest}"


def _rng(request: ExerciseRequest, salt: str) -> random.Random:
    seed = request.seed or str(time.time_ns())
    material = f"{request.level}:{request.topic}:{request.skill_focus}:{request.target_item}:{seed}:{salt}"
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _normalize_answer(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"[.!?]+$", "", value)
    return " ".join(value.split())


def _looks_russian(value: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", value))


def _looks_english(value: str) -> bool:
    return bool(re.search(r"[A-Za-z]", value)) and not _looks_russian(value)


def _word_count(text: str) -> int:
    return len([word for word in re.findall(r"[A-Za-z0-9']+", text) if word])


__all__ = [
    "ExerciseRequest",
    "generate_translation_exercise",
    "validate_translation_exercise",
]
