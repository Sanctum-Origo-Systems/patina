from __future__ import annotations

import email
import email.message
import json

import pytest

from patina.adapters._source_facts import RECIPIENT_KEYS, STATE_KEY, get_fact, render_facts
from patina.adapters.email_imap import ImapEmailAdapter
from patina.ingest import ingest_live
from patina.mcp.tools_catch_up import store_search
from patina.models import EmailMessage, SourceFact, SourceFactState
from patina.ports.email import EmailPort
from patina.store import connect, get_db_path


def test_satisfies_email_port():
    adapter = ImapEmailAdapter(
        host="imap.example.com",
        port=993,
        username="test@example.com",
        password="test",
    )
    assert isinstance(adapter, EmailPort)


def test_platform():
    adapter = ImapEmailAdapter(
        host="imap.example.com",
        port=993,
        username="test@example.com",
        password="test",
    )
    assert adapter.platform == "imap"


def test_parse_message():
    adapter = ImapEmailAdapter(
        host="imap.example.com",
        port=993,
        username="test@example.com",
        password="test",
    )
    raw = (
        b"From: sender@example.com\r\n"
        b"To: recipient@example.com\r\n"
        b"Subject: Test Subject\r\n"
        b"Date: Mon, 25 Nov 2024 10:00:00 +0000\r\n"
        b"Message-ID: <test123@example.com>\r\n"
        b"\r\n"
        b"Hello, this is a test email."
    )
    msg = adapter._parse_message(raw)
    assert msg is not None
    assert msg.sender == "sender@example.com"
    assert msg.subject == "Test Subject"
    assert "test email" in msg.text
    assert msg.recipients == ["recipient@example.com"]


def test_parse_message_source_facts():
    adapter = ImapEmailAdapter(
        host="imap.example.com",
        port=993,
        username="test@example.com",
        password="test",
    )
    raw = (
        b'From: "Sample, Riley" <riley.sample@example.com>\r\n'
        b"To: owner@example.com, casey.lee@example.com\r\n"
        b"Cc: Jordan Example <jordan.example@example.com>\r\n"
        b"Subject: The quick brown fox\r\n"
        b"Date: Mon, 25 Nov 2024 10:00:00 +0000\r\n"
        b"Message-ID: <fox123@example.com>\r\n"
        b"\r\n"
        b"The quick brown fox jumps over the lazy dog."
    )
    msg = adapter._parse_message(raw)
    assert msg.source_facts == {
        "message_id": "<fox123@example.com>",
        "sender_key": '"Sample, Riley" <riley.sample@example.com>',
        "to": "owner@example.com, casey.lee@example.com",
        "cc": "Jordan Example <jordan.example@example.com>",
        "received_raw": "Mon, 25 Nov 2024 10:00:00 +0000",
    }

    no_cc = raw.replace(b"Cc: Jordan Example <jordan.example@example.com>\r\n", b"")
    facts = adapter._parse_message(no_cc).source_facts
    assert "cc" not in facts
    assert facts["to"] == "owner@example.com, casey.lee@example.com"


def test_parse_message_source_facts_omit_absent_headers():
    adapter = ImapEmailAdapter(
        host="imap.example.com",
        port=993,
        username="test@example.com",
        password="test",
    )
    msg = adapter._parse_message(b"Subject: The quick brown fox\r\n\r\nNo headers here.")
    assert msg.source_facts == {}


# Anonymized live shape: quoted "Last, First" display name, an RFC 2047 subject
# ("The quick brown fox — café meeting") and a UTF-8 body with the same em dash
# and accented letter, no Cc header.
LIVE_SHAPE_HEADERS = (
    'From: "Example, Jordan" <jordan@example.invalid>\r\n'
    "Subject: =?utf-8?q?The_quick_brown_fox_=E2=80=94_caf=C3=A9_meeting?=\r\n"
    "Date: Mon, 25 Nov 2024 10:00:00 +0000\r\n"
    "Message-ID: <fox665@example.invalid>\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
)
LIVE_SHAPE_BODY = "\r\nThe quick brown fox — café at 10?\r\n"


def _live_shape(to_line: str | None) -> bytes:
    """The live shape with ``to_line`` as its To header (None: no To header)."""
    to = "" if to_line is None else to_line + "\r\n"
    return (LIVE_SHAPE_HEADERS + to + LIVE_SHAPE_BODY).encode("utf-8")


def _null_to_message() -> email.message.Message:
    """The live shape with a To header the source sent as null."""
    msg = email.message_from_bytes(_live_shape(None))
    msg["To"] = None
    return msg


def _adapter() -> ImapEmailAdapter:
    return ImapEmailAdapter(
        host="imap.example.com", port=993, username="owner@example.invalid", password="x"
    )


class _Port(ImapEmailAdapter):
    """Real adapter whose inbox runs fixed messages through ``_parse_email``."""

    def __init__(self, messages: list[email.message.Message]) -> None:
        super().__init__(host="imap.example.com", port=993, username="o", password="x")
        self._messages = messages

    def list_inbox(self, since: float) -> list[EmailMessage]:
        return [self._parse_email(m) for m in self._messages]

    def search_sent(self, query: str) -> list[EmailMessage]:
        return []


def _search_after_ingest(tmp_path, msg: email.message.Message) -> tuple[str, dict]:
    """Ingest ``msg`` as ``imap``, then return the store_search text and stored facts."""
    ingest_live(port=_Port([msg]), source="imap", home=tmp_path, lookback_days=100000)
    conn = connect(get_db_path(tmp_path))
    (row,) = conn.execute("SELECT metadata FROM observations").fetchall()
    conn.close()
    return store_search("quick brown fox"), json.loads(row["metadata"])["source"]


def test_no_to_header_stores_no_recipients_fact():
    msg = _adapter()._parse_message(_live_shape(None))
    assert msg.subject == "The quick brown fox — café meeting"
    facts = msg.source_facts
    assert get_fact(facts, "to") is None
    assert get_fact(facts, "cc") is None
    assert STATE_KEY not in facts
    assert render_facts(facts, RECIPIENT_KEYS) == "unknown"


def test_null_to_header_stores_unavailable_with_no_value():
    msg = _adapter()._parse_email(_null_to_message())
    assert get_fact(msg.source_facts, "to") == SourceFact(SourceFactState.UNAVAILABLE, None)
    assert "to" not in msg.source_facts
    assert msg.recipients == []
    assert render_facts(msg.source_facts, RECIPIENT_KEYS) == "unknown"


def test_empty_to_header_stores_empty_and_keeps_value():
    facts = _adapter()._parse_message(_live_shape("To:")).source_facts
    assert get_fact(facts, "to") == SourceFact(SourceFactState.EMPTY, "")
    assert facts["to"] == ""
    assert render_facts(facts, RECIPIENT_KEYS) == "none"


def test_present_to_header_keeps_encoded_non_ascii_value():
    to = "=?utf-8?q?Jordan_Ex=C3=A1mple?= <jordan@example.invalid>"
    facts = _adapter()._parse_message(_live_shape(f"To: {to}")).source_facts
    assert get_fact(facts, "to") == SourceFact(SourceFactState.PRESENT, to)
    assert render_facts(facts, RECIPIENT_KEYS) == to


@pytest.mark.parametrize(
    ("make", "state", "rendered"),
    [
        (lambda: email.message_from_bytes(_live_shape(None)), None, "unknown"),
        (_null_to_message, SourceFactState.UNAVAILABLE, "unknown"),
        (lambda: email.message_from_bytes(_live_shape("To:")), SourceFactState.EMPTY, "none"),
    ],
    ids=["missing", "unavailable", "empty"],
)
def test_store_search_shows_recipient_state(tmp_path, make, state, rendered):
    out, stored = _search_after_ingest(tmp_path, make())

    fact = get_fact(stored, "to")
    assert (fact.state if fact else None) == state
    assert f"Recipients: {rendered}" in out
    if rendered == "unknown":
        assert "Recipients: none" not in out


def test_missing_date_is_neither_ingest_time_nor_epoch(tmp_path):
    raw = _live_shape("To: jordan@example.invalid").replace(
        b"Date: Mon, 25 Nov 2024 10:00:00 +0000\r\n", b""
    )
    msg = _adapter()._parse_message(raw)

    assert "received_raw" not in msg.source_facts
    assert render_facts(msg.source_facts, ("received_raw",)) == "unknown"
    # Was ``time.time()`` (the ingest time); must not become 0.0 (the epoch) either.
    assert msg.timestamp is None

    result = ingest_live(
        port=_Port([email.message_from_bytes(raw)]),
        source="imap",
        home=tmp_path,
        lookback_days=100000,
    )
    assert result["messages_inserted"] == 0
    assert result["skip_reasons"] == {"missing_timestamp": 1}
