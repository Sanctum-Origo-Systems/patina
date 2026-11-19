from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from patina.adapters._source_facts import PARTICIPANT_KEYS, STATE_KEY, get_fact, render_facts
from patina.adapters.slack_live import SlackAPIError, SlackLiveAdapter
from patina.ingest import ingest_live
from patina.mcp.tools_catch_up import store_search
from patina.models import SourceFact, SourceFactState
from patina.ports.chat import ChatPort
from patina.store import connect, get_db_path


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


def test_parse_messages_sets_sender_slack_id():
    adapter = SlackLiveAdapter("xoxb-test")
    raw = [{"user": "U999", "text": "Hey there", "ts": "1700000400.000"}]
    msgs = adapter._parse_messages(raw, "C002")
    assert len(msgs) == 1
    assert msgs[0].sender_slack_id == "U999"


def test_parse_messages_source_facts():
    adapter = SlackLiveAdapter("xoxb-test")
    raw = [{"user": "U0EXAMPLE09", "text": "The quick brown fox", "ts": "1700000500.000100"}]
    msgs = adapter._parse_messages(raw, "C0EXAMPLE09", "project-fox")
    assert msgs[0].source_facts == {
        "message_id": "1700000500.000100",
        "channel_id": "C0EXAMPLE09",
        "sender_key": "U0EXAMPLE09",
        "received_raw": "1700000500.000100",
    }


# Anonymized live shape: a DM history message with non-ASCII text (em dash,
# accented letter); ``members`` comes on the channel object it was listed with.
LIVE_SHAPE_MESSAGE = {
    "user": "U0EXAMPLE65",
    "text": "The quick brown fox — café meeting",
    "ts": "1781900000.665001",
}

_PARTICIPANT_CASES = [
    pytest.param({}, None, "unknown", id="missing"),
    pytest.param({"members": None}, SourceFactState.UNAVAILABLE, "unknown", id="unavailable"),
    pytest.param({"members": []}, SourceFactState.EMPTY, "none", id="empty-list"),
    pytest.param({"members": ""}, SourceFactState.EMPTY, "none", id="empty-string"),
]


def _port(channel: dict, messages: list[dict], mentions: list[dict] | None = None):
    """Real adapter whose ``_api`` lists ``channel`` as the one DM, holding ``messages``."""
    adapter = SlackLiveAdapter("xoxb-example")

    def api(method: str, params: dict | None = None) -> dict:
        if method == "conversations.list":
            return {"ok": True, "channels": [channel]}
        if method == "conversations.history" and params["channel"] == channel["id"]:
            return {"ok": True, "messages": messages}
        if method == "search.messages":
            return {"ok": True, "messages": {"matches": mentions or []}}
        return {"ok": True, "messages": []}

    adapter._api = api  # type: ignore[method-assign]
    return adapter


@pytest.mark.parametrize(("channel", "state", "rendered"), _PARTICIPANT_CASES)
def test_parse_messages_participant_state(channel, state, rendered):
    adapter = SlackLiveAdapter("xoxb-test")
    ch = {"id": "D0EXAMPLE65", **channel}
    (msg,) = adapter._parse_messages([LIVE_SHAPE_MESSAGE], "D0EXAMPLE65", channel=ch)
    facts = msg.source_facts
    fact = get_fact(facts, "participants")
    if state is None:
        assert fact is None
        assert "participants" not in facts.get(STATE_KEY, {})
    else:
        assert fact.state is state
    if state is SourceFactState.UNAVAILABLE:
        assert "participants" not in facts
    if state is SourceFactState.EMPTY:
        assert facts["participants"] == channel["members"]
    assert render_facts(facts, PARTICIPANT_KEYS) == rendered


@pytest.mark.parametrize(("channel", "state", "rendered"), _PARTICIPANT_CASES)
def test_list_mentions_participant_state(channel, state, rendered):
    mention = {**LIVE_SHAPE_MESSAGE, "channel": {"id": "C0EXAMPLE65", "name": "fox", **channel}}
    (msg,) = _port({"id": "D0EXAMPLE65"}, [], [mention]).list_mentions(0.0)
    fact = get_fact(msg.source_facts, "participants")
    assert (fact.state if fact else None) == state
    assert render_facts(msg.source_facts, PARTICIPANT_KEYS) == rendered


def test_present_members_kept_as_given():
    members = ["U0EXAMPLE65", "U0EXAMPLE66"]
    adapter = SlackLiveAdapter("xoxb-test")
    ch = {"id": "D0EXAMPLE65", "members": members}
    (msg,) = adapter._parse_messages([LIVE_SHAPE_MESSAGE], "D0EXAMPLE65", channel=ch)
    assert get_fact(msg.source_facts, "participants") == SourceFact(
        SourceFactState.PRESENT, members
    )


@pytest.mark.parametrize(("channel", "state", "rendered"), _PARTICIPANT_CASES)
def test_store_search_shows_participant_state(tmp_path, channel, state, rendered):
    port = _port({"id": "D0EXAMPLE65", **channel}, [LIVE_SHAPE_MESSAGE])
    ingest_live(port=port, source="slack_live", home=tmp_path, lookback_days=100000)

    conn = connect(get_db_path(tmp_path))
    (row,) = conn.execute("SELECT metadata FROM observations").fetchall()
    conn.close()
    fact = get_fact(json.loads(row["metadata"])["source"], "participants")
    assert (fact.state if fact else None) == state

    out = store_search("quick brown fox")
    assert f"Participants: {rendered}" in out
    if rendered == "unknown":
        assert "Participants: none" not in out


def test_missing_ts_is_neither_ingest_time_nor_epoch(tmp_path):
    message = {k: v for k, v in LIVE_SHAPE_MESSAGE.items() if k != "ts"}
    adapter = SlackLiveAdapter("xoxb-test")
    (msg,) = adapter._parse_messages([message], "D0EXAMPLE65")

    assert get_fact(msg.source_facts, "received_raw") is None
    assert render_facts(msg.source_facts, ("received_raw",)) == "unknown"
    # Was float("0") (the epoch); must not become the ingest time either.
    assert msg.timestamp is None

    port = _port({"id": "D0EXAMPLE65"}, [message])
    result = ingest_live(port=port, source="slack_live", home=tmp_path, lookback_days=100000)
    assert result["messages_inserted"] == 0
    assert result["skip_reasons"] == {"missing_timestamp": 1}


def test_parse_messages_sender_slack_id_guard_consistency():
    """All three adapter sites must use the 'if x else None' guard pattern."""
    import inspect

    source = inspect.getsource(SlackLiveAdapter._parse_messages)
    assert "sender_slack_id=user_id if user_id else None" in source


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
