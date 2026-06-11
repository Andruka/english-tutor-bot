"""Deterministic gap-fill exercise generator for the English tutor bot.

The module intentionally has no runtime dependencies outside the Python standard
library so it can be used in tests, bot handlers, or as a local fallback when an
AI-generated exercise fails validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import random
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
    "A1": 20,
    "A2": 20,
    "B1": 35,
    "B2": 55,
    "C1": 80,
    "C2": 80,
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

# Curated templates are deliberately short, safe, and CEFR-appropriate.  The
# target word must appear as a standalone token in the original sentence.
TEMPLATE_BANK: dict[str, dict[str, list[dict[str, Any]]]] = {
    "A1": {
        "travel": [
            {
                "target_item": "ticket",
                "answer": "ticket",
                "aliases": ["a ticket"],
                "sentence": "I need a ticket for the bus.",
                "explanation": "'Ticket' is something you buy before travelling by bus, train, or plane.",
                "vocabulary_tags": ["travel", "transport"],
                "distractors": ["bag", "map", "hotel"],
            },
            {
                "target_item": "train",
                "answer": "train",
                "aliases": [],
                "sentence": "The train is fast.",
                "explanation": "A train is transport that travels on rails.",
                "vocabulary_tags": ["travel", "transport"],
                "distractors": ["kitchen", "apple", "sister"],
            },
            {
                "target_item": "hotel",
                "answer": "hotel",
                "aliases": [],
                "sentence": "We sleep in a hotel.",
                "explanation": "A hotel is a place where travellers can sleep.",
                "vocabulary_tags": ["travel", "places"],
                "distractors": ["ticket", "rain", "book"],
            },
        ],
        "family": [
            {
                "target_item": "mother",
                "answer": "mother",
                "aliases": ["mum", "mom"],
                "sentence": "My mother is at home.",
                "explanation": "'Mother' means мама.",
                "vocabulary_tags": ["family"],
                "distractors": ["ticket", "school", "water"],
            },
            {
                "target_item": "father",
                "answer": "father",
                "aliases": ["dad"],
                "sentence": "My father has a car.",
                "explanation": "'Father' means папа.",
                "vocabulary_tags": ["family"],
                "distractors": ["train", "bread", "rain"],
            },
            {
                "target_item": "sister",
                "answer": "sister",
                "aliases": [],
                "sentence": "My sister is ten.",
                "explanation": "'Sister' means сестра.",
                "vocabulary_tags": ["family"],
                "distractors": ["hotel", "tea", "work"],
            },
            {
                "target_item": "brother",
                "answer": "brother",
                "aliases": [],
                "sentence": "My brother likes football.",
                "explanation": "'Brother' means брат.",
                "vocabulary_tags": ["family"],
                "distractors": ["ticket", "milk", "cold"],
            },
        ],
        "food": [
            {
                "target_item": "water",
                "answer": "water",
                "aliases": [],
                "sentence": "I drink water every day.",
                "explanation": "'Water' is a common drink.",
                "vocabulary_tags": ["food", "drinks"],
                "distractors": ["ticket", "chair", "cloud"],
            }
        ],
    },
    "A2": {
        "food": [
            {
                "target_item": "breakfast",
                "answer": "breakfast",
                "aliases": [],
                "sentence": "I had breakfast before school.",
                "explanation": "'Breakfast' is the morning meal.",
                "vocabulary_tags": ["food", "meals"],
                "distractors": ["airport", "weather", "quickly"],
            },
            {
                "target_item": "cheaper",
                "answer": "cheaper",
                "aliases": [],
                "sentence": "This cafe is cheaper than that restaurant.",
                "explanation": "Use a comparative adjective with 'than'.",
                "vocabulary_tags": ["food", "prices"],
                "grammar_tags": ["comparatives"],
                "distractors": ["cheap", "cheapest", "slowly"],
            },
        ],
        "travel": [
            {
                "target_item": "airport",
                "answer": "airport",
                "aliases": [],
                "sentence": "We arrived at the airport early.",
                "explanation": "An airport is a place where planes arrive and leave.",
                "vocabulary_tags": ["travel", "places"],
                "distractors": ["kitchen", "breakfast", "slowly"],
            }
        ],
    },
    "B1": {
        "work": [
            {
                "target_item": "present_perfect",
                "answer": "have",
                "aliases": ["'ve"],
                "sentence": "I have worked here since 2021.",
                "explanation": "Use present perfect with 'since' to connect a past start time with the present.",
                "vocabulary_tags": ["work"],
                "grammar_tags": ["present_perfect"],
                "distractors": ["am", "did", "will"],
            },
            {
                "target_item": "deadline",
                "answer": "deadline",
                "aliases": [],
                "sentence": "We must finish the report before the deadline.",
                "explanation": "A deadline is the latest time when work must be finished.",
                "vocabulary_tags": ["work", "projects"],
                "distractors": ["airport", "recipe", "slowly"],
            },
        ]
    },
    "B2": {
        "work": [
            {
                "target_item": "deadline",
                "answer": "meet",
                "aliases": [],
                "sentence": "The team needs to meet the deadline despite the delay.",
                "explanation": "The natural collocation is 'meet a deadline'.",
                "vocabulary_tags": ["work", "collocations"],
                "grammar_tags": ["complex_clause"],
                "distractors": ["touch", "arrive", "catch"],
            }
        ]
    },
}

GENERIC_FALLBACKS: dict[str, dict[str, Any]] = {
    "A1": {
        "target_item": "am",
        "answer": "am",
        "aliases": ["'m"],
        "sentence": "I am a student.",
        "explanation": "Use 'am' with 'I'.",
        "vocabulary_tags": ["introduction"],
        "grammar_tags": ["be"],
        "distractors": ["is", "are", "have"],
    },
    "A2": {
        "target_item": "went",
        "answer": "went",
        "aliases": [],
        "sentence": "Yesterday I went to the park.",
        "explanation": "'Went' is the past simple form of 'go'.",
        "vocabulary_tags": ["daily_routine"],
        "grammar_tags": ["past_simple"],
        "distractors": ["go", "going", "goes"],
    },
    "B1": {
        "target_item": "should",
        "answer": "should",
        "aliases": [],
        "sentence": "You should ask for help if the task is unclear.",
        "explanation": "Use 'should' to give advice.",
        "vocabulary_tags": ["work"],
        "grammar_tags": ["modals"],
        "distractors": ["musted", "did", "very"],
    },
    "B2": {
        "target_item": "although",
        "answer": "although",
        "aliases": ["though"],
        "sentence": "Although the meeting was long, the final decision was useful.",
        "explanation": "'Although' introduces a contrast clause.",
        "vocabulary_tags": ["work"],
        "grammar_tags": ["complex_clause"],
        "distractors": ["because", "during", "unless"],
    },
    "C1": {
        "target_item": "Had",
        "answer": "Had",
        "aliases": [],
        "sentence": "Had I known the risks, I would have chosen another route.",
        "explanation": "This is inversion in a third conditional structure.",
        "vocabulary_tags": ["travel"],
        "grammar_tags": ["inversion", "conditionals"],
        "distractors": ["If", "Because", "When"],
    },
    "C2": {
        "target_item": "nuance",
        "answer": "nuance",
        "aliases": [],
        "sentence": "The nuance of her reply was easy to miss in the written report.",
        "explanation": "'Nuance' means a subtle difference in meaning or feeling.",
        "vocabulary_tags": ["work", "style"],
        "grammar_tags": ["nuance"],
        "distractors": ["noise", "number", "delay"],
    },
}


@dataclass(frozen=True)
class ExerciseRequest:
    user_id: int
    level: str
    topic: str
    exercise_type: str = "gap_fill"
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
        if self.exercise_type != "gap_fill":
            raise ValueError(
                "gap_fill_generator only supports exercise_type='gap_fill'"
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


def generate_gap_fill_exercise(
    request: ExerciseRequest | dict[str, Any],
) -> dict[str, Any]:
    """Generate a deterministic, locally validated gap-fill exercise.

    ``seed`` controls candidate order and possible-answer shuffling.  The same
    request, including user_id, produces the same full exercise.  Changing only
    user_id changes the deterministic exercise_id but not the selected sentence.
    """

    if isinstance(request, dict):
        request = ExerciseRequest(**request)

    template = _select_template(request)
    sentence = _blank_sentence(template["sentence"], template["answer"])
    possible_answers = _possible_answers(template, request)
    grammar_tags = template.get("grammar_tags") or _default_grammar_tags(
        request, template
    )
    vocabulary_tags = template.get("vocabulary_tags", [request.topic])

    exercise = {
        "exercise_id": _exercise_id(request),
        "schema_version": "1.0",
        "type": "gap_fill",
        "level": request.level,
        "topic": request.topic,
        "skill_focus": request.skill_focus,
        "target_item": template["target_item"],
        "prompt": f"Complete the sentence: {sentence}",
        "payload": {
            "sentence": sentence,
            "gap_count": 1,
            "possible_answers": possible_answers,
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

    errors = validate_gap_fill_exercise(exercise)
    if errors:
        raise ValueError("invalid generated gap-fill exercise: " + "; ".join(errors))
    return exercise


def validate_gap_fill_exercise(exercise: dict[str, Any]) -> list[str]:
    """Return validation errors for a generated gap-fill exercise."""

    errors: list[str] = []
    prompt = str(exercise.get("prompt", ""))
    payload = exercise.get("payload") or {}
    sentence = str(payload.get("sentence", ""))
    correct = exercise.get("correct_answer") or {}
    possible_answers = payload.get("possible_answers") or []

    if exercise.get("type") != "gap_fill":
        errors.append("type must be gap_fill")
    if prompt.count("___") != 1:
        errors.append("prompt must contain exactly one blank marker")
    if sentence.count("___") != 1:
        errors.append("sentence must contain exactly one blank marker")
    if payload.get("gap_count") != 1:
        errors.append("gap_count must be 1")
    if exercise.get("level") not in ALLOWED_LEVELS:
        errors.append("level must be a supported CEFR level")
    if exercise.get("topic") not in ALLOWED_TOPICS:
        errors.append("topic must be an allowed topic")
    if correct.get("case_sensitive") is not False:
        errors.append("correct answer must be case-insensitive")
    answer = str(correct.get("value", "")).strip()
    if not answer:
        errors.append("correct answer value is required")
    if answer and answer not in possible_answers:
        errors.append("possible_answers must include the correct answer")
    if len({_normalize_choice(value) for value in possible_answers}) != len(
        possible_answers
    ):
        errors.append("possible_answers must be unique after normalization")
    level = str(exercise.get("level", ""))
    if level in LEVEL_WORD_LIMITS and _word_count(sentence) > LEVEL_WORD_LIMITS[level]:
        errors.append("sentence exceeds CEFR word limit")
    if "___" in answer:
        errors.append("correct answer must not contain blank marker")
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


def _blank_sentence(sentence: str, answer: str) -> str:
    words = sentence.split()
    normalized_answer = _strip_punctuation(answer).lower()
    for index, word in enumerate(words):
        if _strip_punctuation(word).lower() == normalized_answer:
            prefix = word[: len(word) - len(word.lstrip("'\"([{"))]
            suffix_chars = ""
            for char in reversed(word):
                if char in ".,!?;:)\"]}'":
                    suffix_chars = char + suffix_chars
                else:
                    break
            replacement = f"{prefix}___{suffix_chars}"
            words[index] = replacement
            return " ".join(words)
    raise ValueError(
        f"answer {answer!r} is not present as a standalone token in {sentence!r}"
    )


def _possible_answers(template: dict[str, Any], request: ExerciseRequest) -> list[str]:
    values = [template["answer"], *template.get("distractors", [])]
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _normalize_choice(value)
        if key not in seen:
            seen.add(key)
            unique.append(value)
    rng = _rng(request, salt=f"answers:{template['target_item']}")
    rng.shuffle(unique)
    return unique


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
            "correct": f"Верно: {answer}.",
            "incorrect": f"Почти. Правильный ответ: {answer}. {template['explanation']}",
        }
    return {
        "correct": f"Correct: {answer}.",
        "incorrect": f"Not quite. The correct answer is {answer}. {template['explanation']}",
    }


def _estimated_time(level: str) -> int:
    return 25 if level in {"A1", "A2"} else 35 if level == "B1" else 45


def _adapted_level(level: str, offset: int) -> str:
    index = ALLOWED_LEVELS.index(level)
    adapted_index = max(0, min(len(ALLOWED_LEVELS) - 1, index + offset))
    return ALLOWED_LEVELS[adapted_index]


def _exercise_id(request: ExerciseRequest) -> str:
    if request.seed is None:
        seed_material = (
            f"{request.user_id}:{request.level}:{request.topic}:{time.time_ns()}"
        )
    else:
        seed_material = (
            f"{request.user_id}:{request.level}:{request.topic}:{request.skill_focus}:"
            f"{request.target_item}:{request.seed}"
        )
    digest = hashlib.sha1(seed_material.encode("utf-8")).hexdigest()[:16].upper()
    return f"ex_{digest}"


def _rng(request: ExerciseRequest, salt: str) -> random.Random:
    seed = request.seed or str(time.time_ns())
    material = f"{request.level}:{request.topic}:{request.skill_focus}:{request.target_item}:{seed}:{salt}"
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _strip_punctuation(value: str) -> str:
    return value.strip(".,!?;:()[]{}\"'")


def _normalize_choice(value: str) -> str:
    return " ".join(str(value).casefold().split())


def _word_count(text: str) -> int:
    return len([word for word in text.replace("___", " blank ").split() if word])


__all__ = [
    "ExerciseRequest",
    "generate_gap_fill_exercise",
    "validate_gap_fill_exercise",
]
