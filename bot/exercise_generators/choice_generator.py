"""Deterministic multiple-choice exercise generator for the English tutor bot.

The implementation is a local template fallback for the choice exercise type:
it has no non-stdlib runtime dependencies, produces canonical exercise
dictionaries, supports seeded reproducibility, and validates the generated shape.
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

# Four answer options are provided for every template: one correct answer plus
# three plausible distractors.  A1/A2 templates may include one wrong part of
# speech distractor, as allowed by the design plan.
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
                "distractors": [
                    {
                        "value": "hotel",
                        "reason": "same travel topic but wrong object for boarding a bus",
                    },
                    {
                        "value": "map",
                        "reason": "useful for travel but not something needed to board",
                    },
                    {
                        "value": "slowly",
                        "reason": "wrong part of speech for the noun gap",
                    },
                ],
            },
            {
                "target_item": "train",
                "answer": "train",
                "aliases": [],
                "sentence": "The train is fast.",
                "explanation": "A train is transport that travels on rails.",
                "vocabulary_tags": ["travel", "transport"],
                "distractors": [
                    {"value": "hotel", "reason": "travel-related place, not transport"},
                    {
                        "value": "ticket",
                        "reason": "travel-related object, not the vehicle",
                    },
                    {
                        "value": "kitchen",
                        "reason": "familiar A1 noun from another topic",
                    },
                ],
            },
            {
                "target_item": "hotel",
                "answer": "hotel",
                "aliases": [],
                "sentence": "We sleep in a hotel.",
                "explanation": "A hotel is a place where travellers can sleep.",
                "vocabulary_tags": ["travel", "places"],
                "distractors": [
                    {
                        "value": "train",
                        "reason": "travel transport, not a place to sleep",
                    },
                    {"value": "ticket", "reason": "travel object, not accommodation"},
                    {
                        "value": "rain",
                        "reason": "common A1 weather word from another topic",
                    },
                ],
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
                "distractors": [
                    {"value": "sister", "reason": "family word, but not a parent"},
                    {
                        "value": "father",
                        "reason": "family word with a different meaning",
                    },
                    {"value": "ticket", "reason": "known A1 noun from another topic"},
                ],
            },
            {
                "target_item": "father",
                "answer": "father",
                "aliases": ["dad"],
                "sentence": "My father has a car.",
                "explanation": "'Father' means папа.",
                "vocabulary_tags": ["family"],
                "distractors": [
                    {
                        "value": "mother",
                        "reason": "family word with a different meaning",
                    },
                    {"value": "brother", "reason": "family word, but not a parent"},
                    {"value": "train", "reason": "known A1 noun from another topic"},
                ],
            },
            {
                "target_item": "sister",
                "answer": "sister",
                "aliases": [],
                "sentence": "My sister is ten.",
                "explanation": "'Sister' means сестра.",
                "vocabulary_tags": ["family"],
                "distractors": [
                    {"value": "mother", "reason": "family word, but not a sibling"},
                    {
                        "value": "brother",
                        "reason": "sibling word with a different meaning",
                    },
                    {"value": "hotel", "reason": "known A1 noun from another topic"},
                ],
            },
            {
                "target_item": "brother",
                "answer": "brother",
                "aliases": [],
                "sentence": "My brother likes football.",
                "explanation": "'Brother' means брат.",
                "vocabulary_tags": ["family", "hobbies"],
                "grammar_tags": ["present_simple"],
                "distractors": [
                    {
                        "value": "sister",
                        "reason": "sibling word with a different meaning",
                    },
                    {"value": "father", "reason": "family word, but not a sibling"},
                    {"value": "ticket", "reason": "known A1 noun from another topic"},
                ],
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
                "distractors": [
                    {"value": "bread", "reason": "food item but not a drink"},
                    {
                        "value": "tea",
                        "reason": "drink, but not the basic word in this sentence",
                    },
                    {"value": "ticket", "reason": "known A1 noun from another topic"},
                ],
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
                "grammar_tags": ["past_simple"],
                "distractors": [
                    {
                        "value": "dinner",
                        "reason": "meal word, but at the wrong time of day",
                    },
                    {"value": "airport", "reason": "same CEFR level but wrong topic"},
                    {
                        "value": "quickly",
                        "reason": "wrong part of speech for the meal noun gap",
                    },
                ],
            },
            {
                "target_item": "cheaper",
                "answer": "cheaper",
                "aliases": [],
                "sentence": "This cafe is cheaper than that restaurant.",
                "explanation": "Use a comparative adjective with 'than'.",
                "vocabulary_tags": ["food", "prices"],
                "grammar_tags": ["comparatives"],
                "distractors": [
                    {
                        "value": "cheap",
                        "reason": "base adjective, but 'than' needs a comparative",
                    },
                    {
                        "value": "cheapest",
                        "reason": "superlative form, not comparative",
                    },
                    {"value": "slowly", "reason": "wrong part of speech"},
                ],
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
                "grammar_tags": ["past_simple"],
                "distractors": [
                    {
                        "value": "station",
                        "reason": "travel place, but usually for trains or buses",
                    },
                    {"value": "hotel", "reason": "travel place, but for sleeping"},
                    {"value": "breakfast", "reason": "same CEFR level but wrong topic"},
                ],
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
                "distractors": [
                    {
                        "value": "am",
                        "reason": "present form of be, not the auxiliary for present perfect",
                    },
                    {
                        "value": "did",
                        "reason": "past simple auxiliary, not used with 'since' here",
                    },
                    {
                        "value": "will",
                        "reason": "future auxiliary, but the sentence connects past to present",
                    },
                ],
            },
            {
                "target_item": "deadline",
                "answer": "deadline",
                "aliases": [],
                "sentence": "We must finish the report before the deadline.",
                "explanation": "A deadline is the latest time when work must be finished.",
                "vocabulary_tags": ["work", "projects"],
                "grammar_tags": ["modals"],
                "distractors": [
                    {
                        "value": "meeting",
                        "reason": "work noun, but not a final time limit",
                    },
                    {"value": "airport", "reason": "same CEFR level but wrong topic"},
                    {"value": "quickly", "reason": "wrong part of speech"},
                ],
            },
        ]
    },
    "B2": {
        "work": [
            {
                "target_item": "meet a deadline",
                "answer": "meet",
                "aliases": [],
                "sentence": "We need to meet the deadline by Friday.",
                "explanation": "The natural collocation is 'meet a deadline'.",
                "vocabulary_tags": ["work", "collocations"],
                "grammar_tags": ["collocation"],
                "distractors": [
                    {
                        "value": "touch",
                        "reason": "literal verb, wrong collocation with deadline",
                    },
                    {
                        "value": "catch",
                        "reason": "semantically close, but not used with deadline",
                    },
                    {"value": "arrive", "reason": "wrong verb frame for this noun"},
                ],
            },
            {
                "target_item": "passive_voice",
                "answer": "approved",
                "aliases": [],
                "sentence": "The proposal was approved after a long discussion.",
                "explanation": "Use a past participle after 'was' to form the passive voice.",
                "vocabulary_tags": ["work", "meetings"],
                "grammar_tags": ["passive_voice"],
                "distractors": [
                    {
                        "value": "approve",
                        "reason": "base verb, not past participle after 'was'",
                    },
                    {
                        "value": "approving",
                        "reason": "-ing form, not passive voice here",
                    },
                    {"value": "approval", "reason": "noun form, not a verb form"},
                ],
            },
        ]
    },
    "C1": {
        "work": [
            {
                "target_item": "register_control",
                "answer": "clarify",
                "aliases": [],
                "sentence": "Could you clarify the timeline before we proceed?",
                "explanation": "'Clarify' is a precise, formal verb for making something clearer.",
                "vocabulary_tags": ["work", "register"],
                "grammar_tags": ["advanced_modality", "register_control"],
                "distractors": [
                    {
                        "value": "explain",
                        "reason": "possible in some contexts, but less precise after 'Could you' here",
                    },
                    {
                        "value": "talk",
                        "reason": "too informal and needs a different verb pattern",
                    },
                    {
                        "value": "clear",
                        "reason": "adjective/base verb mismatch in this sentence",
                    },
                ],
            }
        ]
    },
    "C2": {
        "work": [
            {
                "target_item": "nuance",
                "answer": "nuance",
                "aliases": [],
                "sentence": "The nuance of her reply was easy to miss.",
                "explanation": "'Nuance' means a subtle difference in meaning or feeling.",
                "vocabulary_tags": ["work", "style"],
                "grammar_tags": ["nuance"],
                "distractors": [
                    {"value": "noise", "reason": "similar sound, but wrong meaning"},
                    {
                        "value": "number",
                        "reason": "common noun, but not an abstract subtle meaning",
                    },
                    {
                        "value": "delay",
                        "reason": "work-related noun, but not about subtle meaning",
                    },
                ],
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
        "distractors": [
            {"value": "is", "reason": "used with he/she/it, not I"},
            {"value": "are", "reason": "used with you/we/they, not I"},
            {"value": "have", "reason": "different basic verb"},
        ],
    },
    "A2": {
        "target_item": "went",
        "answer": "went",
        "aliases": [],
        "sentence": "Yesterday I went to the park.",
        "explanation": "'Went' is the past simple form of 'go'.",
        "vocabulary_tags": ["daily_routine"],
        "grammar_tags": ["past_simple"],
        "distractors": [
            {"value": "go", "reason": "base verb, not past simple"},
            {"value": "going", "reason": "-ing form, not past simple"},
            {"value": "goes", "reason": "present simple third-person form"},
        ],
    },
    "B1": {
        "target_item": "should",
        "answer": "should",
        "aliases": [],
        "sentence": "You should ask for help if the task is unclear.",
        "explanation": "Use 'should' to give advice.",
        "vocabulary_tags": ["work"],
        "grammar_tags": ["modals"],
        "distractors": [
            {"value": "musted", "reason": "invalid modal form"},
            {"value": "did", "reason": "past auxiliary, not advice"},
            {"value": "very", "reason": "wrong part of speech"},
        ],
    },
    "B2": {
        "target_item": "although",
        "answer": "although",
        "aliases": ["though"],
        "sentence": "Although the meeting was long, the final decision was useful.",
        "explanation": "'Although' introduces a contrast clause.",
        "vocabulary_tags": ["work"],
        "grammar_tags": ["complex_clause"],
        "distractors": [
            {"value": "because", "reason": "gives a reason, not a contrast"},
            {"value": "during", "reason": "preposition, not a contrast linker"},
            {"value": "unless", "reason": "condition linker, not contrast"},
        ],
    },
    "C1": {
        "target_item": "Had",
        "answer": "Had",
        "aliases": [],
        "sentence": "Had I known the risks, I would have chosen another route.",
        "explanation": "This is inversion in a third conditional structure.",
        "vocabulary_tags": ["travel"],
        "grammar_tags": ["inversion", "conditionals"],
        "distractors": [
            {"value": "If", "reason": "would require a different word order"},
            {"value": "Because", "reason": "reason linker, not conditional inversion"},
            {"value": "When", "reason": "time linker, not counterfactual condition"},
        ],
    },
    "C2": {
        "target_item": "nuance",
        "answer": "nuance",
        "aliases": [],
        "sentence": "The nuance of her reply was easy to miss in the written report.",
        "explanation": "'Nuance' means a subtle difference in meaning or feeling.",
        "vocabulary_tags": ["work", "style"],
        "grammar_tags": ["nuance"],
        "distractors": [
            {"value": "noise", "reason": "similar sound, but wrong meaning"},
            {
                "value": "number",
                "reason": "common noun, but not an abstract subtle meaning",
            },
            {
                "value": "delay",
                "reason": "work-related noun, but not about subtle meaning",
            },
        ],
    },
}


@dataclass(frozen=True)
class ExerciseRequest:
    user_id: int
    level: str
    topic: str
    exercise_type: str = "choice"
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
        if self.exercise_type != "choice":
            raise ValueError("choice_generator only supports exercise_type='choice'")
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


def generate_choice_exercise(
    request: ExerciseRequest | dict[str, Any],
) -> dict[str, Any]:
    """Generate a deterministic locally validated multiple-choice exercise."""

    if isinstance(request, dict):
        request = ExerciseRequest(**request)

    template = _select_template(request)
    sentence = _blank_sentence(template["sentence"], template["answer"])
    choices = _choices(template, request)
    grammar_tags = template.get("grammar_tags") or _default_grammar_tags(
        request, template
    )
    vocabulary_tags = template.get("vocabulary_tags", [request.topic])

    exercise = {
        "exercise_id": _exercise_id(request),
        "schema_version": "1.0",
        "type": "choice",
        "level": request.level,
        "topic": request.topic,
        "skill_focus": request.skill_focus,
        "target_item": template["target_item"],
        "prompt": f"Choose the best word: {sentence}",
        "payload": {
            "choices": choices,
            "blank_index": 1,
            "sentence": sentence,
        },
        "correct_answer": {
            "value": template["answer"],
            "aliases": list(template.get("aliases", [])),
            "case_sensitive": False,
        },
        "distractors": [dict(item) for item in template["distractors"]],
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

    errors = validate_choice_exercise(exercise)
    if errors:
        raise ValueError("invalid generated choice exercise: " + "; ".join(errors))
    return exercise


def validate_choice_exercise(exercise: dict[str, Any]) -> list[str]:
    """Return validation errors for a generated multiple-choice exercise."""

    errors: list[str] = []
    prompt = str(exercise.get("prompt", ""))
    payload = exercise.get("payload") or {}
    choices = payload.get("choices") or []
    correct = exercise.get("correct_answer") or {}
    distractors = exercise.get("distractors") or []
    answer = str(correct.get("value", "")).strip()
    aliases = correct.get("aliases") or []

    if exercise.get("type") != "choice":
        errors.append("type must be choice")
    if exercise.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    if prompt.count("___") != 1:
        errors.append("prompt must contain exactly one blank marker")
    if payload.get("blank_index") != 1:
        errors.append("blank_index must be 1")
    if exercise.get("level") not in ALLOWED_LEVELS:
        errors.append("level must be a supported CEFR level")
    if exercise.get("topic") not in ALLOWED_TOPICS:
        errors.append("topic must be an allowed topic")
    if not isinstance(choices, list) or len(choices) != 4:
        errors.append("choice exercises must provide exactly four choices")
    if len({_normalize_choice(value) for value in choices}) != len(choices):
        errors.append("choices must be unique after normalization")
    if correct.get("case_sensitive") is not False:
        errors.append("correct answer must be case-insensitive")
    if not answer:
        errors.append("correct answer value is required")
    elif _normalize_choice(answer) not in {
        _normalize_choice(value) for value in choices
    }:
        errors.append("choices must include the correct answer")

    accepted = {_normalize_choice(answer)} | {
        _normalize_choice(alias) for alias in aliases
    }
    matching_choices = [
        choice for choice in choices if _normalize_choice(choice) in accepted
    ]
    if len(matching_choices) != 1:
        errors.append("choices must contain exactly one accepted correct answer")

    if not isinstance(distractors, list):
        errors.append("distractors must contain exactly three entries")
    else:
        distractor_values = {
            _normalize_choice(item.get("value", ""))
            for item in distractors
            if isinstance(item, dict)
        }
        if _normalize_choice(answer) in distractor_values:
            errors.append("distractors must not include the correct answer")
        if len(distractors) != 3:
            errors.append("distractors must contain exactly three entries")
        if len(distractor_values) != len(distractors):
            errors.append("distractors must be unique after normalization")
        for item in distractors:
            if (
                not isinstance(item, dict)
                or not item.get("value")
                or not item.get("reason")
            ):
                errors.append("each distractor must include value and reason")
                break

    level = str(exercise.get("level", ""))
    if level in LEVEL_WORD_LIMITS and _word_count(prompt) > LEVEL_WORD_LIMITS[level]:
        errors.append("prompt exceeds CEFR word limit")

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


def _blank_sentence(sentence: str, answer: str) -> str:
    words = sentence.split()
    normalized_answer = _strip_punctuation(answer).casefold()
    for index, word in enumerate(words):
        if _strip_punctuation(word).casefold() == normalized_answer:
            prefix = word[: len(word) - len(word.lstrip("'\"([{"))]
            suffix_chars = ""
            for char in reversed(word):
                if char in ".,!?;:)\"]}'":
                    suffix_chars = char + suffix_chars
                else:
                    break
            words[index] = f"{prefix}___{suffix_chars}"
            return " ".join(words)
    raise ValueError(
        f"answer {answer!r} is not present as a standalone token in {sentence!r}"
    )


def _choices(template: dict[str, Any], request: ExerciseRequest) -> list[str]:
    values = [template["answer"], *[item["value"] for item in template["distractors"]]]
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _normalize_choice(value)
        if key not in seen:
            seen.add(key)
            unique.append(value)
    rng = _rng(request, salt=f"choices:{template['target_item']}")
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
    return 30 if level in {"A1", "A2"} else 40 if level in {"B1", "B2"} else 55


def _adapted_level(level: str, offset: int) -> str:
    index = ALLOWED_LEVELS.index(level)
    adapted_index = max(0, min(len(ALLOWED_LEVELS) - 1, index + offset))
    return ALLOWED_LEVELS[adapted_index]


def _exercise_id(request: ExerciseRequest) -> str:
    if request.seed is None:
        seed_material = (
            f"{request.user_id}:{request.level}:{request.topic}:choice:{time.time_ns()}"
        )
    else:
        seed_material = (
            f"{request.user_id}:{request.level}:{request.topic}:{request.skill_focus}:"
            f"{request.target_item}:{request.seed}:choice"
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
    "generate_choice_exercise",
    "validate_choice_exercise",
]
