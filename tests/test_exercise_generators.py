"""Integration tests for all deterministic exercise generators.

These tests exercise the public package exports together rather than each module
in isolation.  They verify that the three generator implementations share the
same request contract, produce self-validating canonical exercises for the full
CEFR range, and reject invalid edge-case inputs consistently.
"""

from __future__ import annotations

import pytest

from bot.exercise_generators import (
    ChoiceRequest,
    GapFillRequest,
    TranslationRequest,
    generate_choice_exercise,
    generate_gap_fill_exercise,
    generate_translation_exercise,
    validate_choice_exercise,
    validate_gap_fill_exercise,
    validate_translation_exercise,
)


GENERATORS = (
    pytest.param(
        "choice",
        ChoiceRequest,
        generate_choice_exercise,
        validate_choice_exercise,
        id="choice",
    ),
    pytest.param(
        "gap_fill",
        GapFillRequest,
        generate_gap_fill_exercise,
        validate_gap_fill_exercise,
        id="gap-fill",
    ),
    pytest.param(
        "translation",
        TranslationRequest,
        generate_translation_exercise,
        validate_translation_exercise,
        id="translation",
    ),
)

EXPECTED_DIFFICULTY = {
    "A1": 1,
    "A2": 2,
    "B1": 3,
    "B2": 4,
    "C1": 5,
    "C2": 6,
}


@pytest.mark.parametrize("exercise_type,request_cls,generate,validate", GENERATORS)
@pytest.mark.parametrize("level", ["A1", "A2", "B1", "B2", "C1", "C2"])
def test_all_generators_produce_valid_exercises_for_every_cefr_level(
    exercise_type,
    request_cls,
    generate,
    validate,
    level,
):
    request = request_cls(
        user_id=10_001,
        level=level,
        topic="work",
        seed=f"integration-{exercise_type}-{level}",
    )

    exercise = generate(request)

    assert exercise["type"] == exercise_type
    assert exercise["schema_version"] == "1.0"
    assert exercise["level"] == level
    assert exercise["topic"] == "work"
    assert exercise["exercise_id"].startswith("ex_")
    assert len(exercise["exercise_id"]) > len("ex_")
    assert exercise["prompt"].strip()
    assert exercise["target_item"].strip()
    assert exercise["correct_answer"]["value"].strip()
    assert exercise["correct_answer"]["case_sensitive"] is False
    assert exercise["metadata"]["difficulty"] == EXPECTED_DIFFICULTY[level]
    assert exercise["metadata"]["generation_source"] == "template"
    assert exercise["metadata"]["review_required"] is False
    assert exercise["metadata"]["estimated_time_seconds"] > 0
    assert isinstance(exercise["metadata"]["grammar_tags"], list)
    assert isinstance(exercise["metadata"]["vocabulary_tags"], list)
    assert validate(exercise) == []


@pytest.mark.parametrize("exercise_type,request_cls,generate,validate", GENERATORS)
@pytest.mark.parametrize(
    ("level", "offset", "expected_adapted_level"),
    [("A1", -1, "A1"), ("C2", 1, "C2")],
)
def test_lowest_and_highest_levels_clamp_adapted_grammar_level(
    exercise_type,
    request_cls,
    generate,
    validate,
    level,
    offset,
    expected_adapted_level,
):
    exercise = generate(
        request_cls(
            user_id=10_002,
            level=level,
            topic="weather",
            seed=f"boundary-{exercise_type}-{level}",
            difficulty_offset=offset,
        )
    )

    assert exercise["level"] == level
    assert exercise["metadata"]["difficulty"] == EXPECTED_DIFFICULTY[level]
    assert exercise["metadata"]["adapted_grammar_level"] == expected_adapted_level
    assert validate(exercise) == []


@pytest.mark.parametrize("exercise_type,request_cls,generate,validate", GENERATORS)
def test_generators_accept_dict_requests_and_are_seed_reproducible(
    exercise_type,
    request_cls,
    generate,
    validate,
):
    request_data = {
        "user_id": 10_003,
        "level": "B1",
        "topic": "work",
        "skill_focus": "grammar",
        "seed": f"dict-{exercise_type}",
        "history": {"weak_categories": ["present_perfect"]},
    }

    first = generate(dict(request_data))
    second = generate(request_cls(**request_data))
    other_user = generate({**request_data, "user_id": 10_004})

    assert first == second
    assert first["exercise_id"] != other_user["exercise_id"]
    assert first["target_item"] == other_user["target_item"]
    assert first["correct_answer"] == other_user["correct_answer"]
    assert validate(first) == []
    assert validate(other_user) == []


@pytest.mark.parametrize("exercise_type,request_cls,generate,validate", GENERATORS)
def test_valid_but_empty_template_topics_fall_back_to_level_appropriate_content(
    exercise_type,
    request_cls,
    generate,
    validate,
):
    exercise = generate(
        request_cls(
            user_id=10_005,
            level="C2",
            topic="weather",
            seed=f"fallback-{exercise_type}",
        )
    )

    assert exercise["level"] == "C2"
    assert exercise["topic"] == "weather"
    assert exercise["metadata"]["difficulty"] == 6
    assert exercise["metadata"]["grammar_tags"]
    assert exercise["metadata"]["vocabulary_tags"]
    assert validate(exercise) == []


@pytest.mark.parametrize("exercise_type,request_cls,generate,validate", GENERATORS)
def test_invalid_empty_topic_is_rejected_before_generation(
    exercise_type,
    request_cls,
    generate,
    validate,
):
    with pytest.raises(ValueError, match="unknown topic"):
        request_cls(
            user_id=10_006,
            level="A1",
            topic="",
            seed=f"empty-topic-{exercise_type}",
        )

    with pytest.raises(ValueError, match="unknown topic"):
        generate(
            {
                "user_id": 10_006,
                "level": "A1",
                "topic": "",
                "seed": f"empty-topic-dict-{exercise_type}",
            }
        )


@pytest.mark.parametrize("exercise_type,request_cls,generate,validate", GENERATORS)
def test_invalid_level_and_out_of_range_difficulty_offsets_are_rejected(
    exercise_type,
    request_cls,
    generate,
    validate,
):
    with pytest.raises(ValueError, match="unknown CEFR level"):
        request_cls(
            user_id=10_007,
            level="pre-A1",
            topic="work",
            seed=f"bad-level-{exercise_type}",
        )

    with pytest.raises(ValueError, match="difficulty_offset must be between -1 and 1"):
        request_cls(
            user_id=10_008,
            level="A1",
            topic="work",
            seed=f"bad-offset-{exercise_type}",
            difficulty_offset=2,
        )


@pytest.mark.parametrize("exercise_type,request_cls,generate,validate", GENERATORS)
def test_history_recent_items_do_not_force_invalid_repetition_when_fresh_content_exists(
    exercise_type,
    request_cls,
    generate,
    validate,
):
    exercise = generate(
        request_cls(
            user_id=10_009,
            level="A1",
            topic="family",
            seed=f"history-{exercise_type}",
            history={"recent_target_items": ["mother", "father", "sister"]},
        )
    )

    assert exercise["target_item"] == "brother"
    assert validate(exercise) == []


def test_choice_generator_integration_shape_contains_one_correct_option_and_three_distractors():
    exercise = generate_choice_exercise(
        ChoiceRequest(user_id=10_010, level="B2", topic="work", seed="choice-shape")
    )

    choices = exercise["payload"]["choices"]
    correct = exercise["correct_answer"]["value"]

    assert exercise["prompt"].count("___") == 1
    assert exercise["payload"]["sentence"].count("___") == 1
    assert len(choices) == 4
    assert len({choice.casefold() for choice in choices}) == 4
    assert choices.count(correct) == 1
    assert len(exercise["distractors"]) == 3
    assert {item["value"] for item in exercise["distractors"]}.isdisjoint({correct})
    assert validate_choice_exercise(exercise) == []


def test_gap_fill_generator_integration_shape_contains_single_gap_and_possible_answers():
    exercise = generate_gap_fill_exercise(
        GapFillRequest(user_id=10_011, level="C1", topic="travel", seed="gap-shape")
    )

    assert exercise["prompt"].count("___") == 1
    assert exercise["payload"]["sentence"].count("___") == 1
    assert exercise["payload"]["gap_count"] == 1
    assert (
        exercise["correct_answer"]["value"] in exercise["payload"]["possible_answers"]
    )
    assert len(exercise["payload"]["possible_answers"]) >= 3
    assert validate_gap_fill_exercise(exercise) == []


def test_translation_generator_integration_shape_translates_russian_to_english():
    exercise = generate_translation_exercise(
        TranslationRequest(
            user_id=10_012, level="C2", topic="work", seed="translation-shape"
        )
    )

    assert exercise["prompt"].startswith("Translate into English: ")
    assert exercise["payload"]["source_locale"] == "ru"
    assert exercise["payload"]["target_locale"] == "en"
    assert exercise["payload"]["source_text"] in exercise["prompt"]
    assert exercise["payload"]["hints"]
    assert exercise["payload"]["required_content_words"]
    assert exercise["distractors"] == []
    assert validate_translation_exercise(exercise) == []
