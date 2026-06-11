"""Tests for the deterministic multiple-choice exercise generator."""

from bot.exercise_generators.choice_generator import (
    ExerciseRequest,
    generate_choice_exercise,
    validate_choice_exercise,
)


def word_count(text: str) -> int:
    return len([word for word in text.replace("___", " blank ").split() if word])


def test_generates_seeded_a1_choice_with_four_unique_options_and_single_correct_answer():
    request = ExerciseRequest(user_id=101, level="A1", topic="travel", seed="stable-a1")

    exercise = generate_choice_exercise(request)

    assert exercise["type"] == "choice"
    assert exercise["schema_version"] == "1.0"
    assert exercise["level"] == "A1"
    assert exercise["topic"] == "travel"
    assert exercise["prompt"].count("___") == 1
    assert exercise["payload"]["blank_index"] == 1
    assert len(exercise["payload"]["choices"]) == 4
    assert len({choice.casefold() for choice in exercise["payload"]["choices"]}) == 4
    assert exercise["correct_answer"]["value"] in exercise["payload"]["choices"]
    assert (
        sum(
            choice == exercise["correct_answer"]["value"]
            for choice in exercise["payload"]["choices"]
        )
        == 1
    )
    assert len(exercise["distractors"]) == 3
    assert {d["value"] for d in exercise["distractors"]}.isdisjoint(
        {exercise["correct_answer"]["value"]}
    )
    assert word_count(exercise["prompt"]) <= 20
    assert exercise["metadata"]["difficulty"] == 1
    assert exercise["metadata"]["generation_source"] == "template"
    assert exercise["metadata"]["review_required"] is False
    assert validate_choice_exercise(exercise) == []


def test_seed_makes_choice_reproducible_but_user_changes_exercise_id():
    first = generate_choice_exercise(
        ExerciseRequest(user_id=101, level="A2", topic="food", seed="same-seed")
    )
    second = generate_choice_exercise(
        ExerciseRequest(user_id=101, level="A2", topic="food", seed="same-seed")
    )
    other_user = generate_choice_exercise(
        ExerciseRequest(user_id=202, level="A2", topic="food", seed="same-seed")
    )

    assert first == second
    assert first["exercise_id"] != other_user["exercise_id"]
    assert first["prompt"] == other_user["prompt"]
    assert first["payload"]["choices"] == other_user["payload"]["choices"]


def test_history_and_explicit_target_control_choice_target_selection():
    generated = generate_choice_exercise(
        ExerciseRequest(
            user_id=101,
            level="A1",
            topic="family",
            seed="family-seed",
            history={"recent_target_items": ["mother", "father", "sister"]},
        )
    )
    explicit = generate_choice_exercise(
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
    assert explicit["correct_answer"]["value"] == "mother"
    assert "___" in explicit["prompt"]


def test_b2_collocation_choice_uses_subtle_same_level_distractors_and_adapted_metadata():
    exercise = generate_choice_exercise(
        ExerciseRequest(
            user_id=101,
            level="B2",
            topic="work",
            skill_focus="collocation",
            seed="deadline-seed",
            difficulty_offset=-1,
            target_item="meet a deadline",
        )
    )

    assert exercise["target_item"] == "meet a deadline"
    assert exercise["correct_answer"]["value"] == "meet"
    assert set(exercise["payload"]["choices"]) == {"meet", "touch", "catch", "arrive"}
    assert "collocations" in exercise["metadata"]["vocabulary_tags"]
    assert exercise["metadata"]["adapted_grammar_level"] == "B1"
    assert word_count(exercise["prompt"]) <= 55
    assert validate_choice_exercise(exercise) == []


def test_validation_reports_bad_choice_shape():
    bad = generate_choice_exercise(
        ExerciseRequest(user_id=101, level="A1", topic="travel", seed="bad")
    )
    bad["payload"]["choices"] = [
        bad["correct_answer"]["value"],
        bad["correct_answer"]["value"],
        "hotel",
    ]
    bad["distractors"] = [
        {"value": bad["correct_answer"]["value"], "reason": "duplicate"}
    ]
    bad["prompt"] = "Choose the best word: I need a ticket for the bus."

    errors = validate_choice_exercise(bad)

    assert "prompt must contain exactly one blank marker" in errors
    assert "choice exercises must provide exactly four choices" in errors
    assert "choices must be unique after normalization" in errors
    assert "distractors must not include the correct answer" in errors
