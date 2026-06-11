"""Tests for the deterministic translation exercise generator."""

from bot.exercise_generators.translation_generator import (
    ExerciseRequest,
    generate_translation_exercise,
    validate_translation_exercise,
)


def word_count(text: str) -> int:
    return len([word for word in text.split() if word])


def test_generates_a1_translation_with_expected_answer_aliases_and_hint():
    request = ExerciseRequest(
        user_id=101, level="A1", topic="family", seed="stable-family"
    )

    exercise = generate_translation_exercise(request)

    assert exercise["type"] == "translation"
    assert exercise["schema_version"] == "1.0"
    assert exercise["level"] == "A1"
    assert exercise["topic"] == "family"
    assert exercise["prompt"].startswith("Translate into English: ")
    assert exercise["payload"]["source_locale"] == "ru"
    assert exercise["payload"]["target_locale"] == "en"
    assert exercise["payload"]["source_text"] in exercise["prompt"]
    assert exercise["correct_answer"]["value"]
    assert exercise["correct_answer"]["case_sensitive"] is False
    assert "hints" in exercise["payload"]
    assert exercise["payload"]["hints"]
    assert exercise["metadata"]["difficulty"] == 1
    assert exercise["metadata"]["generation_source"] == "template"
    assert word_count(exercise["correct_answer"]["value"]) <= 8
    assert validate_translation_exercise(exercise) == []


def test_seed_makes_translation_reproducible_but_user_changes_exercise_id():
    first = generate_translation_exercise(
        ExerciseRequest(user_id=101, level="A2", topic="travel", seed="same-seed")
    )
    second = generate_translation_exercise(
        ExerciseRequest(user_id=101, level="A2", topic="travel", seed="same-seed")
    )
    other_user = generate_translation_exercise(
        ExerciseRequest(user_id=202, level="A2", topic="travel", seed="same-seed")
    )

    assert first == second
    assert first["exercise_id"] != other_user["exercise_id"]
    assert first["payload"]["source_text"] == other_user["payload"]["source_text"]
    assert first["correct_answer"] == other_user["correct_answer"]


def test_history_and_explicit_target_control_target_selection():
    generated = generate_translation_exercise(
        ExerciseRequest(
            user_id=101,
            level="A1",
            topic="family",
            seed="family-seed",
            history={"recent_target_items": ["mother", "father", "sister"]},
        )
    )
    explicit = generate_translation_exercise(
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
    assert explicit["correct_answer"]["value"] == "My mother is at home."


def test_b1_weak_grammar_category_gets_priority_and_adapted_metadata():
    exercise = generate_translation_exercise(
        ExerciseRequest(
            user_id=101,
            level="B1",
            topic="work",
            skill_focus="grammar",
            seed="grammar-seed",
            difficulty_offset=1,
            history={"weak_categories": ["present_perfect"]},
        )
    )

    assert exercise["target_item"] == "present_perfect"
    assert "present_perfect" in exercise["metadata"]["grammar_tags"]
    assert exercise["metadata"]["adapted_grammar_level"] == "B2"
    assert word_count(exercise["correct_answer"]["value"]) <= 16
    assert validate_translation_exercise(exercise) == []


def test_validation_reports_bad_translation_shape():
    bad = generate_translation_exercise(
        ExerciseRequest(user_id=101, level="A1", topic="family", seed="bad")
    )
    bad["payload"]["source_text"] = "My mother is at home."
    bad["correct_answer"]["value"] = "Моя мама дома."
    bad["payload"]["hints"] = []

    errors = validate_translation_exercise(bad)

    assert "source_text must look like Russian text for locale ru" in errors
    assert "correct answer must look like English text" in errors
    assert "payload hints must contain at least one hint" in errors
