"""Tests for placement test data model and deterministic scoring service."""

import aiosqlite
import pytest


@pytest.mark.asyncio
async def test_init_db_creates_placement_test_results_table(tmp_path):
    from bot.db import init_db

    db_path = tmp_path / "placement.db"
    await init_db(str(db_path))

    async with aiosqlite.connect(db_path) as conn:
        cursor = await conn.execute("PRAGMA table_info(placement_test_results)")
        columns = {row[1]: row[2] for row in await cursor.fetchall()}

    assert columns == {
        "result_id": "INTEGER",
        "user_id": "INTEGER",
        "answers_json": "TEXT",
        "total_questions": "INTEGER",
        "correct_answers": "INTEGER",
        "score": "REAL",
        "determined_level": "TEXT",
        "created_at": "TEXT",
    }


def test_select_test_questions_returns_15_seeded_template_questions():
    from bot.services.placement_test_service import select_test_questions

    first = select_test_questions(user_id=101, seed="placement-seed")
    second = select_test_questions(user_id=101, seed="placement-seed")
    other_seed = select_test_questions(user_id=101, seed="another-seed")

    assert first == second
    assert len(first) == 15
    assert [q["order"] for q in first] == list(range(1, 16))
    assert [q["question_id"] for q in first] != [q["question_id"] for q in other_seed]
    assert {q["type"] for q in first} <= {"choice", "gap_fill", "translation"}
    assert {q["level"] for q in first} >= {"A1", "A2", "B1", "B2", "C1"}
    assert all(q["metadata"]["generation_source"] == "template" for q in first)
    assert all(q["correct_answer"]["value"] for q in first)


def test_select_test_questions_respects_custom_count_and_is_user_stable_except_ids():
    from bot.services.placement_test_service import select_test_questions

    user_101 = select_test_questions(user_id=101, seed="same", count=6)
    user_202 = select_test_questions(user_id=202, seed="same", count=6)

    assert len(user_101) == 6
    assert len(user_202) == 6
    assert [q["question_id"] for q in user_101] != [q["question_id"] for q in user_202]
    assert [q["prompt"] for q in user_101] == [q["prompt"] for q in user_202]
    assert [q["correct_answer"] for q in user_101] == [q["correct_answer"] for q in user_202]


def test_evaluate_test_scores_normalized_answers_and_estimates_level():
    from bot.services.placement_test_service import evaluate_test, select_test_questions

    questions = select_test_questions(user_id=101, seed="score-seed", count=6)
    answers = {
        questions[0]["question_id"]: f"  {questions[0]['correct_answer']['value'].upper()}  ",
        questions[1]["question_id"]: "wrong answer",
        questions[2]["question_id"]: questions[2]["correct_answer"]["value"],
        questions[3]["question_id"]: "",
        questions[4]["question_id"]: questions[4]["correct_answer"]["value"],
    }

    result = evaluate_test(questions, answers)

    assert result["total_questions"] == 6
    assert result["correct_answers"] == 3
    assert result["score"] == 50
    assert result["estimated_level"] in ("A1", "A2")
    assert result["answers"][questions[0]["question_id"]]["is_correct"] is True
    assert result["answers"][questions[1]["question_id"]]["is_correct"] is False
    assert result["answers"][questions[5]["question_id"]]["submitted_answer"] == ""


def test_evaluate_test_accepts_aliases_and_reports_mastery_by_level():
    from bot.services.placement_test_service import evaluate_test

    questions = [
        {
            "question_id": "q1",
            "level": "A1",
            "correct_answer": {"value": "mother", "aliases": ["mum", "mom"]},
        },
        {
            "question_id": "q2",
            "level": "B1",
            "correct_answer": {"value": "I have worked here.", "aliases": []},
        },
        {
            "question_id": "q3",
            "level": "B1",
            "correct_answer": {"value": "I will travel tomorrow.", "aliases": ["I'll travel tomorrow"]},
        },
    ]

    result = evaluate_test(
        questions,
        {"q1": "Mum", "q2": "wrong", "q3": "I'll travel tomorrow."},
    )

    assert result["correct_answers"] == 2
    assert result["level_breakdown"] == {
        "A1": {"correct": 1, "total": 1, "score": 100},
        "B1": {"correct": 1, "total": 2, "score": 50},
    }
    assert result["estimated_level"] == "B1"


def test_finalize_test_full_flow():
    """Integration: run_placement_test -> answer all -> finalize_test."""
    from bot.services.placement_test_service import (
        run_placement_test,
        finalize_test,
    )

    result = run_placement_test(42, seed="integ")
    assert result.total_count == 15
    assert len(result.questions) == 15

    # All correct
    for q in result.questions:
        result.answers[q.id] = True

    result = finalize_test(result)
    assert result.correct_count == 15
    assert result.score == 1.0
    assert result.determined_level in ("B2", "C1", "C2")

    # All wrong
    result2 = run_placement_test(43, seed="integ")
    for q in result2.questions:
        result2.answers[q.id] = False

    result2 = finalize_test(result2)
    assert result2.correct_count == 0
    assert result2.score == 0.0
    assert result2.determined_level == "A1"


def test_run_placement_test_determinism():
    """Same seed + user_id produces same PlacementTestResult questions."""
    from bot.services.placement_test_service import run_placement_test

    a = run_placement_test(99, seed="det-check")
    b = run_placement_test(99, seed="det-check")

    assert [q.id for q in a.questions] == [q.id for q in b.questions]
    assert [q.choices for q in a.questions] == [q.choices for q in b.questions]