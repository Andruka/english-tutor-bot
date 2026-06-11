"""Exercise generators: gap-fill, multiple choice, translation."""

from bot.exercise_generators.choice_generator import (
    ExerciseRequest as ChoiceRequest,
    generate_choice_exercise,
    validate_choice_exercise,
)
from bot.exercise_generators.gap_fill_generator import (
    ExerciseRequest as GapFillRequest,
    generate_gap_fill_exercise,
    validate_gap_fill_exercise,
)
from bot.exercise_generators.translation_generator import (
    ExerciseRequest as TranslationRequest,
    generate_translation_exercise,
    validate_translation_exercise,
)

__all__ = [
    "ChoiceRequest",
    "generate_choice_exercise",
    "validate_choice_exercise",
    "GapFillRequest",
    "generate_gap_fill_exercise",
    "validate_gap_fill_exercise",
    "TranslationRequest",
    "generate_translation_exercise",
    "validate_translation_exercise",
]
