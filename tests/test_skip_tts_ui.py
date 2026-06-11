"""Tests for Skip TTS chat UI controls."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_skip_tts_button_markup_uses_backend_callback_data():
    """Text responses expose a Skip TTS button wired to the skip callback."""
    from bot.handlers.common import build_skip_tts_reply_markup

    markup = build_skip_tts_reply_markup("resp-123")

    button = markup.inline_keyboard[0][0]
    assert button.text == "⏭ Skip TTS"
    assert button.callback_data == "skip_tts:resp-123"


@pytest.mark.asyncio
async def test_skip_tts_callback_marks_response_and_confirms_to_user():
    """Clicking Skip TTS calls the backend skip handler and updates UI feedback."""
    from bot.handlers.dialogue import handle_skip_tts_callback

    callback = SimpleNamespace(
        data="skip_tts:resp-123",
        from_user=SimpleNamespace(id=42),
        message=SimpleNamespace(
            text="Hello! Let's practice.",
            edit_reply_markup=AsyncMock(),
        ),
        answer=AsyncMock(),
    )

    with patch("bot.handlers.dialogue.mark_text_response_tts_skipped") as mark_skipped:
        await handle_skip_tts_callback(callback)

    mark_skipped.assert_called_once_with(
        "42",
        "resp-123",
        "Hello! Let's practice.",
    )
    assert callback.message.edit_reply_markup.await_count == 2
    in_flight_markup = callback.message.edit_reply_markup.await_args_list[0].kwargs[
        "reply_markup"
    ]
    final_markup = callback.message.edit_reply_markup.await_args_list[1].kwargs[
        "reply_markup"
    ]
    assert in_flight_markup.inline_keyboard[0][0].text == "⏳ Skipping TTS..."
    assert final_markup.inline_keyboard[0][0].text == "✅ TTS skipped"
    callback.answer.assert_awaited_once_with("TTS skipped for this response.")
