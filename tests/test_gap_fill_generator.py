"""Tests for the deterministic gap-fill exercise generator."""

from bot.exercise_generators.gap_fill_generator import (
    ExerciseRequest,
    generate_gap_fill_exercise,
    validate_gap_fill_exercise,
)


def word_count(text: str) -> int:
    return len([word for word in text.replace("___", " blank ").split() if word])


def test_generates_seeded_a1_gap_fill_with_possible_answers_and_single_blank():
    request = ExerciseRequest(user_id=101, level="A1", topic="travel", seed="stable-a1")

    exercise = generate_gap_fill_exercise(request)

    assert exercise["type"] == "gap_fill"
    assert exercise["level"] == "A1"
    assert exercise["topic"] == "travel"
    assert exercise["schema_version"] == "1.0"
    assert exercise["prompt"].count("___") == 1
    assert exercise["payload"]["sentence"].count("___") == 1
    assert exercise["payload"]["gap_count"] == 1
    assert word_count(exercise["payload"]["sentence"]) <= 20
    assert (
        exercise["correct_answer"]["value"] in exercise["payload"]["possible_answers"]
    )
    assert len(exercise["payload"]["possible_answers"]) >= 3
    assert exercise["metadata"]["difficulty"] == 1
    assert exercise["metadata"]["generation_source"] == "template"
    assert validate_gap_fill_exercise(exercise) == []


def test_seed_makes_generation_reproducible_but_user_changes_exercise_id():
    first = generate_gap_fill_exercise(
        ExerciseRequest(user_id=101, level="A2", topic="food", seed="same-seed")
    )
    second = generate_gap_fill_exercise(
        ExerciseRequest(user_id=101, level="A2", topic="food", seed="same-seed")
    )
    other_user = generate_gap_fill_exercise(
        ExerciseRequest(user_id=202, level="A2", topic="food", seed="same-seed")
    )

    assert first == second
    assert first["exercise_id"] != other_user["exercise_id"]
    assert first["payload"]["sentence"] == other_user["payload"]["sentence"]


def test_target_selection_respects_recent_history_unless_explicit_target_requested():
    generated = generate_gap_fill_exercise(
        ExerciseRequest(
            user_id=101,
            level="A1",
            topic="family",
            seed="family-seed",
            history={"recent_target_items": ["mother", "father", "sister"]},
        )
    )
    explicit = generate_gap_fill_exercise(
        ExerciseRequest(
            user_id=101,
            level="A1",
            topic="family",
            target_item="mother",
            history={"recent_target_items": ["mother"]},
        )
    )

    assert generated["target_item"] not in {"mother", "father", "sister"}
    assert explicit["target_item"] == "mother"
    assert "___" in explicit["payload"]["sentence"]


def test_b1_weak_grammar_category_gets_priority_and_level_appropriate_metadata():
    exercise = generate_gap_fill_exercise(
        ExerciseRequest(
            user_id=101,
            level="B1",
            topic="work",
            skill_focus="grammar",
            seed="grammar-seed",
            history={"weak_categories": ["present_perfect"]},
        )
    )

    assert exercise["target_item"] == "present_perfect"
    assert exercise["correct_answer"]["value"] == "have"
    assert "present_perfect" in exercise["metadata"]["grammar_tags"]
    assert word_count(exercise["payload"]["sentence"]) <= 35
    assert validate_gap_fill_exercise(exercise) == []


def test_validation_reports_bad_gap_fill_shape():
    bad = generate_gap_fill_exercise(
        ExerciseRequest(user_id=101, level="A1", topic="travel", seed="bad")
    )
    bad["payload"]["sentence"] = "I need a ticket."
    bad["prompt"] = "Complete: I need a ticket."

    errors = validate_gap_fill_exercise(bad)

    assert "sentence must contain exactly one blank marker" in errors
    assert "prompt must contain exactly one blank marker" in errors
