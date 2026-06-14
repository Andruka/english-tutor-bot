"""Tests for Telegram placement-test handler."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import Chat, Message, User


def make_message(user_id: int = 101, message_id: int = 7) -> Message:
    return Message(
        message_id=message_id,
        date=0,
        text="/test",
        from_user=User(id=user_id, is_bot=False, first_name="Test", username="tester"),
        chat=Chat(id=user_id, type="private"),
    )


def make_callback(user_id: int, data: str):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=user_id),
        message=SimpleNamespace(edit_text=AsyncMock()),
        answer=AsyncMock(),
    )


@pytest.fixture(autouse=True)
def clear_active_placement_tests():
    from bot.handlers import placement

    placement._active_tests.clear()
    yield
    placement._active_tests.clear()


async def flush_tasks():
    """Yield control so fire-and-forget create_task callbacks run."""
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_cmd_test_starts_session_and_sends_first_question():
    from bot.handlers.placement import _active_tests, cmd_test

    with patch.object(Message, "answer", new_callable=AsyncMock) as mock_answer:
        msg = make_message(user_id=501, message_id=11)
        await cmd_test(msg)

    assert 501 in _active_tests
    mock_answer.assert_awaited_once()
    text = mock_answer.await_args.args[0]
    assert "Тест на определение уровня" in text
    assert "Прогресс: 1/15" in text
    reply_markup = mock_answer.await_args.kwargs["reply_markup"]
    assert reply_markup.inline_keyboard


@pytest.mark.asyncio
async def test_last_answer_saves_result_updates_user_level_and_shows_result(tmp_path):
    import bot.db as bdb
    from bot.db import UserRepository, get_conn, init_db
    from bot.handlers.placement import _active_tests, cb_answer
    from bot.services.placement_test_service import finalize_test, run_placement_test

    db_path = tmp_path / "placement_handler.db"
    old_db_path = bdb._db_path
    bdb._db_path = str(db_path)
    await init_db(str(db_path))

    user_id = 777
    try:
        conn = await get_conn()
        repo = UserRepository(conn)
        await repo.create(user_id=user_id, level="A1", username="placement_user")
        await conn.close()

        session = run_placement_test(user_id=user_id, seed="handler-final")
        for question in session.questions[:-1]:
            session.answers[question.id] = True
        expected = finalize_test(session).determined_level
        # Reset so handler re-finalizes
        session.correct_count = 0
        session.total_count = 0
        session.score = 0.0
        session.determined_level = "A1"
        session.level_scores = {}
        _active_tests[user_id] = session
        last_index = len(session.questions) - 1
        last_question = session.questions[last_index]
        correct_choice_index = last_question.choices.index(last_question.correct_answer)
        callback = make_callback(
            user_id=user_id,
            data=f"pt_answer:{last_index}:{correct_choice_index}",
        )

        await cb_answer(callback)
        await flush_tasks()

        assert user_id not in _active_tests
        callback.message.edit_text.assert_awaited()
        final_text = callback.message.edit_text.await_args.args[0]
        assert "Тест завершён" in final_text
        assert f"Твой уровень: <b>{expected}</b>" in final_text
        assert "•" in final_text

        conn = await get_conn()
        try:
            cursor = await conn.execute(
                """SELECT score, total_questions, correct_answers, determined_level
                   FROM placement_test_results WHERE user_id = ?""",
                (user_id,),
            )
            row = await cursor.fetchone()
            user = await UserRepository(conn).get(user_id)
        finally:
            await conn.close()

        assert row is not None
        assert row[1] == 15
        assert row[2] == 15
        assert row[3] == expected
        assert user.level == expected
    finally:
        bdb._db_path = old_db_path


@pytest.mark.asyncio
async def test_continue_and_restart_callbacks():
    from bot.handlers.placement import _active_tests, cb_continue, cb_restart
    from bot.services.placement_test_service import run_placement_test

    user_id = 888
    session = run_placement_test(user_id=user_id, seed="handler-flow")
    # Answer first question only
    session.answers[session.questions[0].id] = True
    _active_tests[user_id] = session

    # Continue
    cb = make_callback(user_id=user_id, data="pt_continue")
    await cb_continue(cb)
    cb.message.edit_text.assert_awaited()
    assert "Прогресс: 2/15" in cb.message.edit_text.await_args.args[0]

    # Restart — needs message.answer and message.message_id for _start_new_test
    cb2 = make_callback(user_id=user_id, data="pt_restart")
    cb2.message.answer = AsyncMock()
    cb2.message.message_id = 123
    await cb_restart(cb2)
    assert user_id in _active_tests
    assert len(_active_tests[user_id].answers) == 0