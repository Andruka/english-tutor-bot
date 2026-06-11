"""Тесты хендлеров упражнений."""

import pytest
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch, MagicMock
from aiogram.types import Message, User, Chat, CallbackQuery

from bot.handlers.exercise import _active_exercises


def make_message(
    text: str,
    user_id: int = 1,
    username: str = "TestUser",
    first_name: str = "Test",
    message_id: int | None = None,
) -> Message:
    """Создаёт имитацию Message для тестов хендлеров."""
    return Message(
        message_id=message_id or user_id,
        date=0,
        text=text,
        from_user=User(
            id=user_id, is_bot=False, first_name=first_name, username=username
        ),
        chat=Chat(id=user_id, type="private"),
        sender_chat=None,
    )


def make_callback_query(
    data: str,
    user_id: int = 1,
    message_text: str = "",
    message_id: int = 100,
) -> CallbackQuery:
    """Создаёт имитацию CallbackQuery для тестов хендлеров."""
    msg = make_message(message_text, user_id, message_id=message_id)
    return CallbackQuery(
        id=f"cb_{user_id}_{message_id}",
        from_user=User(id=user_id, is_bot=False, first_name="Test"),
        chat_instance="test",
        message=msg,
        data=data,
    )


@contextmanager
def mock_cb(cb):
    """Навешивает AsyncMock на методы CallbackQuery / Message (class-level, т.к. Pydantic frozen)."""
    with (
        patch.object(CallbackQuery, "answer", new_callable=AsyncMock) as mock_answer,
        patch.object(Message, "edit_text", new_callable=AsyncMock) as mock_edit_text,
        patch.object(
            Message, "edit_reply_markup", new_callable=AsyncMock
        ) as mock_edit_reply,
    ):
        yield {
            "edit_text": mock_edit_text,
            "edit_reply_markup": mock_edit_reply,
            "answer": mock_answer,
        }


# ─── /exercise menu ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exercise_menu():
    """/exercise показывает меню типов упражнений."""
    from bot.handlers.exercise import cmd_exercise

    with patch.object(Message, "answer", new_callable=AsyncMock) as mock_answer:
        msg = make_message("/exercise")
        await cmd_exercise(msg)

        mock_answer.assert_called_once()
        text = mock_answer.call_args[0][0]
        assert "Упражнения" in text or "выбери" in text.lower()
        reply_markup = mock_answer.call_args[1].get("reply_markup")
        assert reply_markup is not None


# ─── cb_select_type ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_new_user_gets_prompt_to_start():
    """Пользователь без регистрации получает приглашение к /start."""
    from bot.handlers.exercise import cb_select_type

    cb = make_callback_query("ex_type:gap_fill", user_id=99999)

    with mock_cb(cb) as mocks:
        with patch(
            "bot.handlers.exercise.UserRepository.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await cb_select_type(cb)

            mocks["edit_text"].assert_called_once()
            text = mocks["edit_text"].call_args[0][0]
            assert "/start" in text


@pytest.mark.asyncio
async def test_gap_fill_generation():
    """Генерация gap-fill."""
    from bot.handlers.exercise import cb_select_type

    mock_user = MagicMock(user_id=1, level="A2")
    cb = make_callback_query("ex_type:gap_fill", user_id=1)

    with mock_cb(cb) as mocks:
        with patch(
            "bot.handlers.exercise.UserRepository.get",
            new_callable=AsyncMock,
            return_value=mock_user,
        ):
            await cb_select_type(cb)

            assert 1 in _active_exercises
            exercise = _active_exercises[1]
            assert exercise["type"] == "gap_fill"
            assert "___" in exercise["payload"]["sentence"]
            mocks["answer"].assert_called_once()
            mocks["edit_text"].assert_called_once()

    _active_exercises.pop(1, None)


@pytest.mark.asyncio
async def test_choice_generation():
    """Генерация choice."""
    from bot.handlers.exercise import cb_select_type

    mock_user = MagicMock(user_id=1, level="B1")
    cb = make_callback_query("ex_type:choice", user_id=1)

    with mock_cb(cb) as mocks:
        with patch(
            "bot.handlers.exercise.UserRepository.get",
            new_callable=AsyncMock,
            return_value=mock_user,
        ):
            await cb_select_type(cb)

            assert 1 in _active_exercises
            exercise = _active_exercises[1]
            assert exercise["type"] == "choice"
            assert len(exercise["payload"]["choices"]) == 4
            mocks["edit_text"].assert_called_once()

    _active_exercises.pop(1, None)


@pytest.mark.asyncio
async def test_translation_generation():
    """Генерация translation."""
    from bot.handlers.exercise import cb_select_type

    mock_user = MagicMock(user_id=1, level="A2")
    cb = make_callback_query("ex_type:translation", user_id=1)

    with mock_cb(cb) as mocks:
        with patch(
            "bot.handlers.exercise.UserRepository.get",
            new_callable=AsyncMock,
            return_value=mock_user,
        ):
            await cb_select_type(cb)

            assert 1 in _active_exercises
            exercise = _active_exercises[1]
            assert exercise["type"] == "translation"
            assert exercise["payload"]["source_locale"] == "ru"
            assert exercise["payload"]["target_locale"] == "en"
            mocks["edit_text"].assert_called_once()

    _active_exercises.pop(1, None)


# ─── cb_check_answer ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_correct_answer():
    """Правильный ответ через callback."""
    from bot.handlers.exercise import cb_select_type, cb_check_answer

    mock_user = MagicMock(user_id=1, level="A2")
    cb = make_callback_query("ex_type:gap_fill", user_id=1)

    with mock_cb(cb):
        with patch(
            "bot.handlers.exercise.UserRepository.get",
            new_callable=AsyncMock,
            return_value=mock_user,
        ):
            await cb_select_type(cb)

            exercise = _active_exercises[1]
            answer_cb = make_callback_query(
                f"ex_answer:{exercise['exercise_id']}:{exercise['correct_answer']['value']}",
                user_id=1,
            )

    with mock_cb(answer_cb) as answer_mocks:
        await cb_check_answer(answer_cb)

        answer_mocks["answer"].assert_called_once()
        answer_mocks["edit_text"].assert_called_once()
        text = answer_mocks["edit_text"].call_args[0][0]
        assert "Верно" in text

    _active_exercises.pop(1, None)


@pytest.mark.asyncio
async def test_wrong_answer_shows_hint():
    """Неверный ответ показывает подсказку."""
    from bot.handlers.exercise import cb_select_type, cb_check_answer

    mock_user = MagicMock(user_id=1, level="A1")
    cb = make_callback_query("ex_type:gap_fill", user_id=1)

    with mock_cb(cb):
        with patch(
            "bot.handlers.exercise.UserRepository.get",
            new_callable=AsyncMock,
            return_value=mock_user,
        ):
            await cb_select_type(cb)

            exercise = _active_exercises[1]
            answer_cb = make_callback_query(
                f"ex_answer:{exercise['exercise_id']}:WRONG_ANSWER",
                user_id=1,
            )

    with mock_cb(answer_cb) as answer_mocks:
        await cb_check_answer(answer_cb)

        answer_mocks["answer"].assert_called_with(
            "❌ Неверно. Попробуй ещё раз или посмотри ответ.", show_alert=True
        )

    _active_exercises.pop(1, None)


@pytest.mark.asyncio
async def test_stale_exercise_returns_alert():
    """Устаревшее упражнение — alert."""
    from bot.handlers.exercise import cb_check_answer

    cb = make_callback_query("ex_answer:stale_id:answer", user_id=1)

    with mock_cb(cb) as mocks:
        await cb_check_answer(cb)

        mocks["answer"].assert_called_once()
        text = mocks["answer"].call_args[0][0]
        assert "уже неактивно" in text


# ─── cb_show_answer ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_show_answer():
    """Просмотр правильного ответа."""
    from bot.handlers.exercise import cb_select_type, cb_show_answer

    mock_user = MagicMock(user_id=1, level="A2")
    cb = make_callback_query("ex_type:gap_fill", user_id=1)

    with mock_cb(cb):
        with patch(
            "bot.handlers.exercise.UserRepository.get",
            new_callable=AsyncMock,
            return_value=mock_user,
        ):
            await cb_select_type(cb)

            exercise = _active_exercises[1]
            show_cb = make_callback_query(
                f"ex_show_answer:{exercise['exercise_id']}",
                user_id=1,
            )

    with mock_cb(show_cb) as show_mocks:
        await cb_show_answer(show_cb)

        show_mocks["edit_text"].assert_called_once()
        text = show_mocks["edit_text"].call_args[0][0]
        assert exercise["correct_answer"]["value"] in text
        show_mocks["answer"].assert_called_once()

    _active_exercises.pop(1, None)


# ─── handle_translation_answer (text) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_translation_answer_correct():
    """Текстовый ответ на translation — верно."""
    from bot.handlers.exercise import handle_translation_answer

    _active_exercises[1] = {
        "type": "translation",
        "exercise_id": "ex_test",
        "correct_answer": {"value": "Hello", "case_sensitive": False},
    }
    msg = make_message("hello", user_id=1)

    with patch.object(Message, "answer", new_callable=AsyncMock) as mock_answer:
        await handle_translation_answer(msg)

        mock_answer.assert_called_once()
        text = mock_answer.call_args[0][0]
        assert "Верно" in text
    assert 1 not in _active_exercises


@pytest.mark.asyncio
async def test_translation_answer_wrong():
    """Текстовый ответ на translation — неверно."""
    from bot.handlers.exercise import handle_translation_answer

    _active_exercises[1] = {
        "type": "translation",
        "exercise_id": "ex_test",
        "correct_answer": {"value": "Hello", "case_sensitive": False},
    }
    msg = make_message("goodbye", user_id=1)

    with patch.object(Message, "answer", new_callable=AsyncMock) as mock_answer:
        await handle_translation_answer(msg)

        mock_answer.assert_called_once()
        text = mock_answer.call_args[0][0]
        assert "Не совсем" in text
    assert 1 not in _active_exercises


# ─── HasActiveTranslationExercise filter ──────────────────────────────────


@pytest.mark.asyncio
async def test_translation_filter():
    """Фильтр активен только для translation."""
    from bot.handlers.exercise import HasActiveTranslationExercise

    f = HasActiveTranslationExercise()
    assert await f(make_message("hi", user_id=1)) is False

    _active_exercises[1] = {"type": "gap_fill"}
    assert await f(make_message("hi", user_id=1)) is False

    _active_exercises[1] = {"type": "translation"}
    assert await f(make_message("hi", user_id=1)) is True

    _active_exercises.pop(1, None)


# ─── cb_back_to_menu ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_back_to_menu():
    """Возврат в меню очищает активное упражнение."""
    from bot.handlers.exercise import cb_back_to_menu

    _active_exercises[1] = {"type": "gap_fill", "exercise_id": "ex_test"}
    cb = make_callback_query("ex_back_to_menu", user_id=1)

    with mock_cb(cb) as mocks:
        await cb_back_to_menu(cb)

        assert 1 not in _active_exercises
        mocks["edit_text"].assert_called_once()
        text = mocks["edit_text"].call_args[0][0]
        assert "Упражнения" in text
        mocks["answer"].assert_called_once()
