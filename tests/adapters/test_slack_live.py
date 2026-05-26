from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from patina.adapters.slack_live import SlackAPIError, SlackLiveAdapter
from patina.ports.chat import ChatPort


def test_satisfies_chat_port():
    adapter = SlackLiveAdapter("xoxb-test")
    assert isinstance(adapter, ChatPort)


def test_platform():
    adapter = SlackLiveAdapter("xoxb-test")
    assert adapter.platform == "slack"


def test_parse_messages():
    adapter = SlackLiveAdapter("xoxb-test")
    raw = [
        {"user": "U001", "text": "Hello", "ts": "1700000100.000"},
        {"user": "U002", "text": "World", "ts": "1700000200.000"},
        {"subtype": "bot_message", "text": "Bot", "ts": "1700000300.000"},
    ]
    msgs = adapter._parse_messages(raw, "C001")
    assert len(msgs) == 2
    assert msgs[0].user_id == "U001"
    assert msgs[1].text == "World"


def test_auth_error():
    adapter = SlackLiveAdapter("xoxb-invalid")

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"ok": False, "error": "invalid_auth"}).encode()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_response):
        try:
            adapter._api("auth.test")
            assert False, "Should have raised"
        except SlackAPIError as e:
            assert "Authentication" in str(e)
