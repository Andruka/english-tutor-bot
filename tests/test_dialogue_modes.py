"""Tests for K011 dialogue modes."""

import os
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import Chat, Message, User


class DummyMessage:
    def __init__(self):
        self.reply = AsyncMock()


def make_message(text: str, user_id: int = 1) -> Message:
    return Message(
        message_id=user_id,
        date=0,
        text=text,
        from_user=User(id=user_id, is_bot=False, first_name="Test"),
        chat=Chat(id=user_id, type="private"),
        sender_chat=None,
    )


@pytest.mark.asyncio
async def test_post_process_dialogue_prefixes_non_free_talk_reply_with_mode_icon(
    tmp_path,
):
    """K011: ответ в Role Play / Grammar Focus должен показывать иконку режима."""
    import bot.db as bdb
    from bot.db import UserRepository, get_conn, init_db
    from bot.handlers.common import post_process_dialogue
    from bot.services.ai_service import MODE_ROLE_PLAY

    old_db_path = bdb._db_path
    db_path = str(tmp_path / "mode_icon.db")
    bdb._db_path = db_path
    await init_db(db_path)
    conn = await get_conn()
    try:
        repo = UserRepository(conn)
        await repo.create(user_id=123, level="A2", username="mode_icon")
        message = DummyMessage()
        result = {
            "reply": "Welcome to the hotel! How can I help you?",
            "corrections": [],
            "rating": 5,
            "vocabulary_tip": "",
            "explanation": "",
            "new_words": [],
        }

        with patch("bot.handlers.common.send_tts_voice", new_callable=AsyncMock):
            await post_process_dialogue(
                message,
                123,
                "Hello",
                result,
                conn,
                topic="travel",
                mode=MODE_ROLE_PLAY,
            )

        sent_text = message.reply.call_args.args[0]
        assert sent_text.startswith("🎭 Welcome to the hotel!")
    finally:
        await conn.close()
        bdb._db_path = old_db_path


@pytest.mark.asyncio
async def test_cmd_mode_shows_inline_keyboard_with_three_modes():
    """K011: /mode показывает inline-клавиатуру с тремя режимами."""
    from bot.handlers.dialogue import cmd_mode

    msg = make_message("/mode", user_id=456)
    with patch.object(Message, "answer", new_callable=AsyncMock) as mock_answer:
        await cmd_mode(msg)

    text = mock_answer.call_args.args[0]
    markup = mock_answer.call_args.kwargs["reply_markup"]
    assert "Режим диалога" in text
    button_texts = [row[0].text for row in markup.inline_keyboard]
    callback_data = [row[0].callback_data for row in markup.inline_keyboard]
    assert len(button_texts) == 3
    assert any("Свободная беседа" in text for text in button_texts)
    assert any("Ролевая игра" in text for text in button_texts)
    assert any("Грамматика" in text for text in button_texts)
    assert callback_data == [
        "mode_set:free_talk",
        "mode_set:role_play",
        "mode_set:grammar_focus",
    ]


@pytest.mark.asyncio
async def test_get_or_create_tutor_uses_selected_mode_and_random_focus(monkeypatch):
    """K011: создаваемая сессия получает выбранный режим и его контекст."""
    from bot.handlers import dialogue
    from bot.services.ai_service import MODE_GRAMMAR_FOCUS

    user_id = 789
    monkeypatch.setitem(os.environ, "OPENROUTER_API_KEY", "test_key")
    dialogue._tutor_sessions.pop(user_id, None)
    dialogue._user_modes[user_id] = MODE_GRAMMAR_FOCUS
    dialogue._user_grammar_foci[user_id] = "Articles (a/an/the)"

    tutor = dialogue.get_or_create_tutor(user_id, "A2", "travel")

    try:
        assert tutor.mode == MODE_GRAMMAR_FOCUS
        assert tutor.grammar_focus == "Articles (a/an/the)"
        assert "Mode: GRAMMAR FOCUS" in tutor.messages[0]["content"]
        assert "Articles (a/an/the)" in tutor.messages[0]["content"]
    finally:
        dialogue._tutor_sessions.pop(user_id, None)
        dialogue._user_modes.pop(user_id, None)
        dialogue._user_grammar_foci.pop(user_id, None)
