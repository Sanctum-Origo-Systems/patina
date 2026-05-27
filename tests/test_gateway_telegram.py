from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from patina.gateway.telegram import TelegramAdapter


def _make_update(user_id: int, text: str):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.send_action = AsyncMock()
    update.message.text = text
    update.message.date = datetime(2025, 5, 26, tzinfo=UTC)
    update.message.reply_text = AsyncMock()
    return update


def test_handle_message_sends_to_agent():
    adapter = TelegramAdapter(token="test", agent_url="http://test:8321")

    update = _make_update(123, "hello")
    context = MagicMock()

    with patch.object(adapter, "send_to_agent", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = "agent response"
        asyncio.run(adapter._handle_message(update, context))

    mock_send.assert_called_once()
    msg = mock_send.call_args[0][0]
    assert msg.text == "hello"
    assert msg.channel == "telegram-123"
    update.message.reply_text.assert_called_once_with("agent response")


def test_handle_message_shows_typing():
    adapter = TelegramAdapter(token="test")
    update = _make_update(123, "hello")

    with patch.object(adapter, "send_to_agent", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = "ok"
        asyncio.run(adapter._handle_message(update, MagicMock()))

    update.effective_chat.send_action.assert_called_once_with("typing")


def test_handle_message_rejects_unauthorized():
    adapter = TelegramAdapter(token="test", allowed_users=[999])
    update = _make_update(123, "hello")

    asyncio.run(adapter._handle_message(update, MagicMock()))

    update.message.reply_text.assert_called_once_with("Not authorized.")


def test_handle_message_allows_when_no_restriction():
    adapter = TelegramAdapter(token="test", allowed_users=None)
    update = _make_update(123, "hello")

    with patch.object(adapter, "send_to_agent", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = "ok"
        asyncio.run(adapter._handle_message(update, MagicMock()))

    mock_send.assert_called_once()


def test_handle_start():
    adapter = TelegramAdapter(token="test")
    update = _make_update(123, "/start")
    asyncio.run(adapter._handle_start(update, MagicMock()))
    update.message.reply_text.assert_called_once_with("Connected. Send me a message.")


def test_handle_message_error_shows_error():
    adapter = TelegramAdapter(token="test")
    update = _make_update(123, "hello")

    with patch.object(adapter, "send_to_agent", new_callable=AsyncMock) as mock_send:
        mock_send.side_effect = Exception("Connection refused")
        asyncio.run(adapter._handle_message(update, MagicMock()))

    reply_text = update.message.reply_text.call_args[0][0]
    assert "Error:" in reply_text
    assert "Connection refused" in reply_text
