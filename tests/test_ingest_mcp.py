from __future__ import annotations

import time
from datetime import datetime

import pytest

from patina.ingest import _obs_id, ingest_live
from patina.models import CalendarEvent, ChatMessage, DmChannel, EmailMessage
from patina.store import connect, get_db_path


class MockSlackMcpPort:
    @property
    def platform(self) -> str:
        return "slack_mcp"

    def list_dm_messages(self, since: float) -> list[ChatMessage]:
        return [
            ChatMessage(
                user_id="U00000ALICE",
                text="Hey, can you review the proposal?",
                timestamp=1781651078.945749,
                channel_id="D00000DM001",
                user_name="Alice",
                reactions=[{"name": "eyes", "users": ["U00000ALICE"]}],
            ),
        ]

    def list_mentions(self, since: float) -> list[ChatMessage]:
        return [
            ChatMessage(
                user_id="U00000EVE01",
                text="Can you join the client call at 3pm?",
                timestamp=1781900000.111111,
                channel_id="C00000CH001",
                channel_name="project-alpha",
            ),
        ]

    def list_channel_messages(self, channel_id, since):
        return []

    def get_thread(self, channel_id, thread_id):
        return []


class MockEmailPort:
    @property
    def platform(self) -> str:
        return "outlook_mcp"

    def list_inbox(self, since: float) -> list[EmailMessage]:
        return [
            EmailMessage(
                id="AAMkAGE2YTg5NWI",
                sender="bob@example.com",
                subject="Project Alpha Contract Review",
                text="[Subject: Project Alpha Contract Review] "
                "[Participants: bob@example.com]\n"
                "The contract is in final review stages.",
                timestamp=1781651078.0,
                recipients=["owner@example.com", "frank@example.com"],
                conversation_id="AAQkAGE2YTg5NWI_conv",
            ),
        ]

    def search_sent(self, query: str) -> list[EmailMessage]:
        return []


class MockCalendarPort:
    @property
    def platform(self) -> str:
        return "outlook_mcp"

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        return [
            CalendarEvent(
                id="AAMkCAL001",
                subject="Quarterly Review",
                start=1781600000.0,
                end=1781601800.0,
                attendees=["owner@example.com", "bob@example.com"],
                organizer="frank@example.com",
            ),
        ]


class MockDualPort:
    @property
    def platform(self) -> str:
        return "outlook_mcp"

    def list_inbox(self, since: float) -> list[EmailMessage]:
        return [
            EmailMessage(
                id="AAMk001",
                sender="alice@example.com",
                subject="Budget update",
                text="[Subject: Budget update] [Participants: alice@example.com]\nApproved.",
                timestamp=1781700000.0,
                recipients=["owner@example.com"],
            ),
        ]

    def search_sent(self, query: str) -> list[EmailMessage]:
        return []

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        return [
            CalendarEvent(
                id="AAMkCAL999",
                subject="Budget meeting",
                start=1781700000.0,
                end=1781701800.0,
                organizer="alice@example.com",
            ),
        ]


def test_slack_mcp_creates_observations_and_entities(tmp_path):
    home = tmp_path / "patina_home"
    port = MockSlackMcpPort()
    result = ingest_live(port=port, source="slack_mcp", home=home)
    assert result["messages_inserted"] == 2
    assert result["entities_created"] >= 2

    conn = connect(get_db_path(home))
    rows = conn.execute(
        "SELECT sender_entity_id FROM observations WHERE sender_entity_id IS NOT NULL"
    ).fetchall()
    assert len(rows) == 2
    conn.close()


def test_email_creates_observations_with_subject(tmp_path):
    home = tmp_path / "patina_home"
    port = MockEmailPort()
    result = ingest_live(port=port, source="outlook_email", home=home)
    assert result["messages_inserted"] == 1

    conn = connect(get_db_path(home))
    row = conn.execute("SELECT text FROM observations").fetchone()
    assert "[Subject: Project Alpha Contract Review]" in row[0]
    conn.close()


def test_calendar_creates_meeting_observations(tmp_path):
    home = tmp_path / "patina_home"
    port = MockCalendarPort()
    result = ingest_live(port=port, source="outlook_calendar", home=home)
    assert result["messages_inserted"] == 1

    conn = connect(get_db_path(home))
    row = conn.execute("SELECT text FROM observations").fetchone()
    assert "[Meeting: Quarterly Review]" in row[0]
    assert "frank@example.com" in row[0]
    assert "bob@example.com" in row[0]
    conn.close()


def test_calendar_organizer_entity_created(tmp_path):
    home = tmp_path / "patina_home"
    port = MockCalendarPort()
    ingest_live(port=port, source="outlook_calendar", home=home)

    conn = connect(get_db_path(home))
    rows = conn.execute(
        "SELECT sender_entity_id FROM observations WHERE sender_entity_id IS NOT NULL"
    ).fetchall()
    assert len(rows) == 1
    conn.close()


def test_dual_port_processes_both(tmp_path):
    home = tmp_path / "patina_home"
    port = MockDualPort()
    result = ingest_live(port=port, source="outlook_dual", home=home)
    assert result["messages_inserted"] == 2

    conn = connect(get_db_path(home))
    texts = [r[0] for r in conn.execute("SELECT text FROM observations").fetchall()]
    has_email = any("[Subject:" in t for t in texts)
    has_meeting = any("[Meeting:" in t for t in texts)
    assert has_email
    assert has_meeting
    conn.close()


def test_email_dedup(tmp_path):
    home = tmp_path / "patina_home"
    port = MockEmailPort()
    ingest_live(port=port, source="outlook_email", home=home)
    result2 = ingest_live(port=port, source="outlook_email", home=home)
    assert result2["messages_skipped"] == 1
    assert result2["messages_inserted"] == 0


def test_config_swap_no_code_change(tmp_path):
    home = tmp_path / "patina_home"

    mcp_port = MockSlackMcpPort()
    result1 = ingest_live(port=mcp_port, source="slack_mcp", home=home)
    assert result1["messages_inserted"] == 2

    class MockOAuthSlackPort:
        @property
        def platform(self) -> str:
            return "slack"

        def list_dm_messages(self, since):
            return [
                ChatMessage(
                    user_id="U00000ALICE",
                    text="Hey, can you review the proposal?",
                    timestamp=1781651078.945749,
                    channel_id="D00000DM001",
                    user_name="Alice",
                ),
            ]

        def list_mentions(self, since):
            return []

        def list_channel_messages(self, channel_id, since):
            return []

        def get_thread(self, channel_id, thread_id):
            return []

    oauth_port = MockOAuthSlackPort()
    result2 = ingest_live(port=oauth_port, source="slack_oauth", home=home)
    assert result2["messages_inserted"] >= 0


def test_ingest_dm_1on1_channel(tmp_path):
    home = tmp_path / "patina_home"
    now = time.time()

    class MockPort:
        @property
        def platform(self) -> str:
            return "slack_mcp"

        def list_dm_messages(self, since):
            return []

        def list_mentions(self, since):
            return []

        def list_channel_messages(self, channel_id, since):
            if channel_id == "D123":
                return [
                    ChatMessage(
                        user_id="U00000ZARA1",
                        text="Hey, want to grab lunch?",
                        timestamp=now,
                        channel_id="D123",
                        user_name="Zara",
                    ),
                ]
            return []

        def get_thread(self, channel_id, thread_id):
            return []

        def list_dms(self, include_dormant=False):
            return [DmChannel(channel_id="D123", is_group=False, last_activity_ts=now)]

    result = ingest_live(port=MockPort(), source="slack_mcp", home=home)
    assert result["messages_inserted"] == 1

    conn = connect(get_db_path(home))
    rows = conn.execute("SELECT text FROM observations WHERE channel_id = 'D123'").fetchall()
    assert len(rows) == 1
    assert rows[0]["text"] == "Hey, want to grab lunch?"
    conn.close()


def test_ingest_dm_group_channel(tmp_path):
    home = tmp_path / "patina_home"
    now = time.time()

    class MockPort:
        @property
        def platform(self) -> str:
            return "slack_mcp"

        def list_dm_messages(self, since):
            return []

        def list_mentions(self, since):
            return []

        def list_channel_messages(self, channel_id, since):
            if channel_id == "C456":
                return [
                    ChatMessage(
                        user_id="U00000QUINN",
                        text="Group project update",
                        timestamp=now,
                        channel_id="C456",
                        user_name="Quinn",
                    ),
                    ChatMessage(
                        user_id="U00000RILEY",
                        text="Sounds good, will review",
                        timestamp=now + 1,
                        channel_id="C456",
                        user_name="Riley",
                    ),
                ]
            return []

        def get_thread(self, channel_id, thread_id):
            return []

        def list_dms(self, include_dormant=False):
            return [DmChannel(channel_id="C456", is_group=True, last_activity_ts=now)]

    result = ingest_live(port=MockPort(), source="slack_mcp", home=home)
    assert result["messages_inserted"] == 2

    conn = connect(get_db_path(home))
    rows = conn.execute("SELECT text FROM observations WHERE channel_id = 'C456'").fetchall()
    assert len(rows) == 2
    texts = {r["text"] for r in rows}
    assert "Group project update" in texts
    assert "Sounds good, will review" in texts
    conn.close()


def test_ingest_dm_stale_channel_skipped(tmp_path):
    home = tmp_path / "patina_home"
    stale_ts = time.time() - (181 * 86400)
    channel_messages_calls: list[str] = []

    class MockPort:
        @property
        def platform(self) -> str:
            return "slack_mcp"

        def list_dm_messages(self, since):
            return []

        def list_mentions(self, since):
            return []

        def list_channel_messages(self, channel_id, since):
            channel_messages_calls.append(channel_id)
            return []

        def get_thread(self, channel_id, thread_id):
            return []

        def list_dms(self, include_dormant=False):
            return [DmChannel(channel_id="D_STALE", last_activity_ts=stale_ts)]

    ingest_live(port=MockPort(), source="slack_mcp", home=home)
    assert "D_STALE" not in channel_messages_calls


def test_ingest_dm_second_run_dedup(tmp_path):
    home = tmp_path / "patina_home"
    now = time.time()

    class MockPort:
        @property
        def platform(self) -> str:
            return "slack_mcp"

        def list_dm_messages(self, since):
            return []

        def list_mentions(self, since):
            return []

        def list_channel_messages(self, channel_id, since):
            if channel_id == "D_DEDUP":
                return [
                    ChatMessage(
                        user_id="U00000ZARA1",
                        text="First message",
                        timestamp=now,
                        channel_id="D_DEDUP",
                        user_name="Zara",
                    ),
                    ChatMessage(
                        user_id="U00000QUINN",
                        text="Second message",
                        timestamp=now + 1,
                        channel_id="D_DEDUP",
                        user_name="Quinn",
                    ),
                ]
            return []

        def get_thread(self, channel_id, thread_id):
            return []

        def list_dms(self, include_dormant=False):
            return [DmChannel(channel_id="D_DEDUP", last_activity_ts=now)]

    port = MockPort()
    result1 = ingest_live(port=port, source="slack_mcp", home=home)
    result2 = ingest_live(port=port, source="slack_mcp", home=home)
    assert result1["messages_inserted"] == 2
    assert result2["messages_skipped"] == result1["messages_inserted"]
    assert result2["messages_inserted"] == 0


def test_ingest_dm_independent_of_watched_channels(tmp_path):
    home = tmp_path / "patina_home"
    now = time.time()
    channel_messages_calls: list[str] = []

    class MockPort:
        @property
        def platform(self) -> str:
            return "slack_mcp"

        def list_dm_messages(self, since):
            return []

        def list_mentions(self, since):
            return []

        def list_channel_messages(self, channel_id, since):
            channel_messages_calls.append(channel_id)
            if channel_id == "D_INDEP":
                return [
                    ChatMessage(
                        user_id="U00000RILEY",
                        text="Independent DM message",
                        timestamp=now,
                        channel_id="D_INDEP",
                        user_name="Riley",
                    ),
                ]
            return []

        def get_thread(self, channel_id, thread_id):
            return []

        def list_dms(self, include_dormant=False):
            return [DmChannel(channel_id="D_INDEP", last_activity_ts=now)]

    result = ingest_live(port=MockPort(), source="slack_mcp", home=home)
    assert "D_INDEP" in channel_messages_calls
    assert result["messages_inserted"] == 1


def test_ingest_dm_obs_id_cross_path_equivalence(tmp_path):
    home = tmp_path / "patina_home"
    now = time.time()

    shared_msg = ChatMessage(
        user_id="U00000ZARA1",
        text="Cross path message",
        timestamp=now,
        channel_id="D_CROSS",
        user_name="Zara",
    )

    class MockPort:
        @property
        def platform(self) -> str:
            return "slack_mcp"

        def list_dm_messages(self, since):
            return [shared_msg]

        def list_mentions(self, since):
            return []

        def list_channel_messages(self, channel_id, since):
            if channel_id == "D_CROSS":
                return [shared_msg]
            return []

        def get_thread(self, channel_id, thread_id):
            return []

        def list_dms(self, include_dormant=False):
            return [DmChannel(channel_id="D_CROSS", last_activity_ts=now)]

    result = ingest_live(port=MockPort(), source="slack_mcp", home=home)

    conn = connect(get_db_path(home))
    rows = conn.execute("SELECT id FROM observations WHERE channel_id = 'D_CROSS'").fetchall()
    assert len(rows) == 1

    dm_path_id = _obs_id("slack_mcp", "D_CROSS", None, now)
    backfill_path_id = _obs_id("slack_mcp", "D_CROSS", None, now)
    assert dm_path_id == backfill_path_id
    assert rows[0]["id"] == dm_path_id

    assert result["messages_skipped"] >= 1
    conn.close()


def test_mcp_ingest_resolves_owner_entity(tmp_path):
    """AC6: MCP ingest path resolves owner when sender matches configured identifier."""
    import yaml

    from patina.extraction import extract_sender_entity
    from patina.graph import upsert_entity
    from patina.owner import get_owner_entity_id, mark_entity_as_owner
    from patina.store import connect as db_connect
    from patina.store import get_db_path, init_db, run_pending_migrations

    home = tmp_path / "patina_home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(yaml.dump({"owner": {"user_ids": ["U00000ALICE"]}}))

    db_path = get_db_path(home)
    init_db(db_path)
    conn = db_connect(db_path)
    run_pending_migrations(conn)
    owner = extract_sender_entity("U00000ALICE", "Alice")
    upsert_entity(conn, owner)
    mark_entity_as_owner(conn, owner.id)
    owner_id = owner.id
    conn.close()

    port = MockSlackMcpPort()
    ingest_live(port=port, source="slack_mcp", home=home)

    conn = db_connect(get_db_path(home))
    row = conn.execute(
        "SELECT sender_entity_id FROM observations WHERE text = 'Hey, can you review the proposal?'"
    ).fetchone()
    assert row is not None
    assert row["sender_entity_id"] == owner_id
    assert row["sender_entity_id"] == get_owner_entity_id(conn)
    conn.close()


def test_id_named_entity_renamed_on_retry(tmp_path):
    """AC: entity created with Slack ID name gets renamed when profile resolves."""
    import json

    from patina.store import connect as db_connect
    from patina.store import get_db_path

    home = tmp_path / "patina_home"

    class FailingPort:
        @property
        def platform(self):
            return "slack_mcp"

        def list_dm_messages(self, since):
            return [
                ChatMessage(
                    user_id="W0EXAMPLE9",
                    text="Message from unresolved user",
                    timestamp=1781900000.111111,
                    channel_id="D00000DM099",
                    user_name=None,
                ),
            ]

        def list_mentions(self, since):
            return []

        def list_channel_messages(self, channel_id, since):
            return []

        def get_thread(self, channel_id, thread_id):
            return []

    result1 = ingest_live(port=FailingPort(), source="slack_mcp", home=home)
    assert result1["messages_inserted"] == 1

    conn = db_connect(get_db_path(home))
    entity_row = conn.execute(
        "SELECT name, aliases FROM entities WHERE type = 'person' AND name LIKE 'W0EXAMPLE%'"
    ).fetchone()
    assert entity_row is not None
    assert entity_row["name"] == "W0EXAMPLE9"
    conn.close()

    class ResolvedPort:
        @property
        def platform(self):
            return "slack_mcp"

        def list_dm_messages(self, since):
            return [
                ChatMessage(
                    user_id="W0EXAMPLE9",
                    text="New message after profile resolved",
                    timestamp=1781900001.222222,
                    channel_id="D00000DM099",
                    user_name="Dana Brook",
                ),
            ]

        def list_mentions(self, since):
            return []

        def list_channel_messages(self, channel_id, since):
            return []

        def get_thread(self, channel_id, thread_id):
            return []

    result2 = ingest_live(port=ResolvedPort(), source="slack_mcp", home=home)
    assert result2["messages_inserted"] == 1

    conn = db_connect(get_db_path(home))
    entity_row = conn.execute(
        "SELECT name, aliases FROM entities WHERE type = 'person' AND aliases LIKE '%W0EXAMPLE9%'"
    ).fetchone()
    assert entity_row is not None
    assert entity_row["name"] == "Dana Brook"
    aliases = json.loads(entity_row["aliases"])
    assert "W0EXAMPLE9" in aliases
    conn.close()


def test_slack_mcp_sender_slack_id_in_metadata(tmp_path):
    """AC: slack_mcp adapter writes sender_slack_id into observation metadata."""
    import json

    home = tmp_path / "patina_home"
    port = MockSlackMcpPort()
    ingest_live(port=port, source="slack_mcp", home=home)

    conn = connect(get_db_path(home))
    rows = conn.execute("SELECT metadata FROM observations").fetchall()
    assert len(rows) >= 1
    for row in rows:
        meta = json.loads(row["metadata"])
        assert "sender_slack_id" in meta
        assert meta["sender_slack_id"] != ""
    conn.close()


def test_calendar_organizer_dn_in_metadata(tmp_path):
    """AC: outlook_mcp calendar adapter writes organizer_dn into observation metadata."""
    import json

    home = tmp_path / "patina_home"
    port = MockCalendarPort()
    ingest_live(port=port, source="outlook_calendar", home=home)

    conn = connect(get_db_path(home))
    row = conn.execute("SELECT metadata FROM observations").fetchone()
    meta = json.loads(row["metadata"])
    assert meta["organizer_dn"] == "frank@example.com"
    conn.close()


def test_slack_live_sender_slack_id_in_metadata(tmp_path):
    """AC: slack_live adapter writes sender_slack_id into observation metadata."""
    import json

    home = tmp_path / "patina_home"

    class MockSlackLivePort:
        @property
        def platform(self) -> str:
            return "slack"

        def list_dm_messages(self, since: float) -> list[ChatMessage]:
            return [
                ChatMessage(
                    user_id="U00000FRANK",
                    text="Quick question about the release",
                    timestamp=1781900100.123456,
                    channel_id="D00000DM055",
                    user_name="Frank",
                    sender_slack_id="U00000FRANK",
                ),
            ]

        def list_mentions(self, since: float) -> list[ChatMessage]:
            return []

        def list_channel_messages(self, channel_id, since):
            return []

        def get_thread(self, channel_id, thread_id):
            return []

    port = MockSlackLivePort()
    ingest_live(port=port, source="slack_live", home=home)

    conn = connect(get_db_path(home))
    row = conn.execute("SELECT metadata FROM observations").fetchone()
    meta = json.loads(row["metadata"])
    assert meta["sender_slack_id"] == "U00000FRANK"
    conn.close()


def test_still_failing_lookup_leaves_entity_unchanged(tmp_path):
    """AC: a still-failing lookup leaves the entity name as the Slack ID."""
    home = tmp_path / "patina_home"

    class FailingPort:
        @property
        def platform(self):
            return "slack_mcp"

        def list_dm_messages(self, since):
            return [
                ChatMessage(
                    user_id="W0NOPROF01",
                    text="Message from unresolved user",
                    timestamp=1781900000.111111,
                    channel_id="D00000DM098",
                    user_name=None,
                ),
            ]

        def list_mentions(self, since):
            return []

        def list_channel_messages(self, channel_id, since):
            return []

        def get_thread(self, channel_id, thread_id):
            return []

    ingest_live(port=FailingPort(), source="slack_mcp", home=home)
    ingest_live(port=FailingPort(), source="slack_mcp", home=home)

    conn = connect(get_db_path(home))
    entity_row = conn.execute(
        "SELECT name FROM entities WHERE type = 'person' AND name = 'W0NOPROF01'"
    ).fetchone()
    assert entity_row is not None
    assert entity_row["name"] == "W0NOPROF01"
    conn.close()


LIVE_SHAPE_INBOX_ITEM = {
    "conversationId": "AAQkADExampleConv001=",
    "id": "AAMkADExampleMsg001=",
    "itemClasses": ["IPM.Note"],
    "topic": "Re: The quick brown fox — Q3 plan",
    "senders": ["Example, Jordan (Contractor)", "Sample, Riley"],
    "toRecipients": [
        {"name": "Owner, Jane", "email": "owner@example.com"},
        {"name": "Müller, Avery", "email": "avery.muller@example.com"},
        {"name": "Team Alpha DL", "email": "team-alpha@example.com", "isDistributionList": True},
    ],
    "ccRecipients": [{"name": "Lee, Casey", "email": "casey.lee@example.com"}],
    "receivedDateTime": "2026-11-03T09:15:42Z",
    "preview": "The quick brown fox jumps over the lazy dog.",
}


class _RawEmailPort:
    """EmailPort that runs raw Outlook items through ``_email_from_raw``."""

    def __init__(self, items: list[dict]) -> None:
        self._items = items

    @property
    def platform(self) -> str:
        return "outlook_mcp"

    def list_inbox(self, since: float) -> list[EmailMessage]:
        from patina.adapters.outlook_mcp import _email_from_raw

        return [_email_from_raw(item) for item in self._items]

    def search_sent(self, query: str) -> list[EmailMessage]:
        return []


def _without(raw: dict, *keys: str) -> dict:
    return {k: v for k, v in raw.items() if k not in keys}


def _stored_email_rows(home) -> list[dict]:
    import json

    conn = connect(get_db_path(home))
    rows = conn.execute(
        "SELECT channel_id, thread_id, timestamp, metadata FROM observations"
    ).fetchall()
    conn.close()
    return [
        {
            "channel_id": r["channel_id"],
            "thread_id": r["thread_id"],
            "timestamp": r["timestamp"],
            "metadata": json.loads(r["metadata"]),
        }
        for r in rows
    ]


def test_outlook_email_source_facts_live_shape(tmp_path):
    """AC: live-shape inbox item stores its raw source facts in metadata["source"]."""
    from patina.adapters.outlook_mcp import _email_from_raw
    from patina.ingest import _emails_to_chat_messages

    raw = LIVE_SHAPE_INBOX_ITEM
    chat = _emails_to_chat_messages([_email_from_raw(raw)])
    assert len(chat) == 1
    assert chat[0].source_facts["message_id"] == raw["id"]

    home = tmp_path / "patina_home"
    result = ingest_live(
        port=_RawEmailPort([raw]), source="outlook_mcp_email", home=home, lookback_days=10000
    )
    assert result["messages_inserted"] == 1

    rows = _stored_email_rows(home)
    assert len(rows) == 1
    row = rows[0]
    source = row["metadata"]["source"]
    assert source["message_id"] == raw["id"]
    assert source["item_class"] == raw["itemClasses"]
    assert source["sender_key"] == raw["senders"][0]
    assert source["to"] == raw["toRecipients"]
    assert source["to"][2]["isDistributionList"] is True
    assert source["cc"] == raw["ccRecipients"]
    assert source["received_raw"] == raw["receivedDateTime"]
    assert "timestamp_missing" not in source

    assert row["thread_id"] == raw["conversationId"]
    assert row["channel_id"] == f"email:{raw['conversationId']}"
    assert row["metadata"]["channel_name"] is None
    assert row["metadata"]["reactions"] == []
    assert row["timestamp"] > 0


def test_outlook_email_source_facts_omit_absent_recipients(tmp_path):
    """AC: no toRecipients/ccRecipients key -> no ``to``/``cc`` key, not empty lists."""
    raw = _without(LIVE_SHAPE_INBOX_ITEM, "toRecipients", "ccRecipients")
    home = tmp_path / "patina_home"
    ingest_live(
        port=_RawEmailPort([raw]), source="outlook_mcp_email", home=home, lookback_days=10000
    )

    (row,) = _stored_email_rows(home)
    source = row["metadata"]["source"]
    assert "to" not in source
    assert "cc" not in source
    assert source["message_id"] == raw["id"]


def test_outlook_email_source_facts_omit_absent_ids_and_sender(tmp_path):
    """AC: missing itemClasses, every id and sender -> keys absent, never "", None or 0."""
    raw = _without(LIVE_SHAPE_INBOX_ITEM, "itemClasses", "id", "conversationId", "senders")
    home = tmp_path / "patina_home"
    ingest_live(
        port=_RawEmailPort([raw]), source="outlook_mcp_email", home=home, lookback_days=10000
    )

    (row,) = _stored_email_rows(home)
    source = row["metadata"]["source"]
    assert "item_class" not in source
    assert "message_id" not in source
    assert "sender_key" not in source
    for value in source.values():
        assert value not in (None, "", 0, [])
    assert source["received_raw"] == raw["receivedDateTime"]


def test_outlook_email_missing_timestamp_skipped_and_counted(tmp_path):
    """AC: an item with no received time is skipped and counted, never stored at 0.0."""
    undated = _without(LIVE_SHAPE_INBOX_ITEM, "receivedDateTime")
    undated["conversationId"] = "AAQkADExampleConv002="
    undated["id"] = "AAMkADExampleMsg002="
    home = tmp_path / "patina_home"
    result = ingest_live(
        port=_RawEmailPort([LIVE_SHAPE_INBOX_ITEM, undated]),
        source="outlook_mcp_email",
        home=home,
        lookback_days=10000,
    )

    assert result["skip_reasons"] == {"missing_timestamp": 1}
    assert result["messages_inserted"] == 1
    rows = _stored_email_rows(home)
    assert len(rows) == 1
    assert all(r["timestamp"] != 0.0 for r in rows)
    assert rows[0]["thread_id"] == LIVE_SHAPE_INBOX_ITEM["conversationId"]


LIVE_SHAPE_CALENDAR_EVENT = {
    "meetingId": "AAMkADExampleEvt001=",
    "subject": "The quick brown fox — weekly sync",
    "start": "2026-11-04T15:00:00-06:00",
    "end": "2026-11-04T15:30:00-06:00",
    "organizer": {"name": "Example, Jordan (Contractor)", "email": "jordan.example@example.com"},
    "attendees": [
        {"name": "Owner, Jane", "email": "owner@example.com", "type": "required"},
        {"name": "Müller, Avery", "email": "avery.muller@example.com", "type": "optional"},
        {"name": "Team Alpha DL", "email": "team-alpha@example.com", "type": "required"},
    ],
}

LIVE_SHAPE_SLACK_MCP_MESSAGE = {
    "user": "U0EXAMPLE01",
    "text": "The quick brown fox — ready for review?",
    "ts": "1781651078.945749",
    "thread_ts": "1781650000.000100",
    "channel": {"id": "D0EXAMPLE01", "name": "jordan.example", "is_im": True},
    "reactions": [{"name": "eyes", "users": ["U0EXAMPLE02"]}],
}

SLACK_LIVE_DM_CHANNEL = "D0EXAMPLE03"
LIVE_SHAPE_SLACK_LIVE_MESSAGE = {
    "type": "message",
    "user": "U0EXAMPLE03",
    "text": "The quick brown fox jumps over the lazy dog.",
    "ts": "1781652000.123456",
    "reactions": [{"name": "thumbsup", "users": ["U0EXAMPLE01"], "count": 1}],
}

LIVE_SHAPE_IMAP_MESSAGE = (
    b'From: "Example, Jordan" <jordan.example@example.com>\r\n'
    b'To: "Owner, Jane" <owner@example.com>, avery.muller@example.com\r\n'
    b"Cc: =?utf-8?q?M=C3=BCller=2C_Avery?= <avery.muller@example.com>\r\n"
    b"Subject: Re: The quick brown fox\r\n"
    b"Date: Tue, 03 Nov 2026 09:15:42 -0600\r\n"
    b"Message-ID: <CAexample001@mail.example.com>\r\n"
    b"In-Reply-To: <CAexample000@mail.example.com>\r\n"
    b"\r\n"
    b"The quick brown fox jumps over the lazy dog."
)


class _RawCalendarPort:
    """CalendarPort that runs raw Outlook events through ``_calendar_event_from_raw``."""

    def __init__(self, items: list[dict]) -> None:
        self._items = items

    @property
    def platform(self) -> str:
        return "outlook_mcp"

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        from patina.adapters.outlook_mcp import _calendar_event_from_raw

        return [_calendar_event_from_raw(item) for item in self._items]


def _slack_mcp_port(items: list[dict]):
    """Real ``SlackMcpAdapter`` over a fake bridge serving ``items`` as unreads."""
    import json
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from patina.adapters.slack_mcp import SlackMcpAdapter

    responses = {
        "get_unreads": json.dumps(items),
        "get_user_profile": json.dumps({"real_name": "Jordan Example"}),
    }

    def call_tool(name, arguments=None, **kwargs):
        text = responses.get(name, "[]")
        return SimpleNamespace(isError=False, content=[SimpleNamespace(text=text)])

    bridge = MagicMock()
    bridge.call_tool = MagicMock(side_effect=call_tool)
    return SlackMcpAdapter(bridge)


def _slack_live_port(messages: list[dict], mentions: list[dict] | None = None):
    """Real ``SlackLiveAdapter`` whose ``_api`` serves ``messages`` as one DM history."""
    from patina.adapters.slack_live import SlackLiveAdapter

    adapter = SlackLiveAdapter("xoxb-example")

    def api(method: str, params: dict | None = None) -> dict:
        if method == "conversations.list":
            return {"ok": True, "channels": [{"id": SLACK_LIVE_DM_CHANNEL}]}
        if method == "conversations.history" and params["channel"] == SLACK_LIVE_DM_CHANNEL:
            return {"ok": True, "messages": messages}
        if method == "search.messages":
            return {"ok": True, "messages": {"matches": mentions or []}}
        return {"ok": True, "messages": []}

    adapter._api = api  # type: ignore[method-assign]
    return adapter


def _imap_port(raw_messages: list[bytes]):
    """Real ``ImapEmailAdapter`` whose inbox runs ``raw_messages`` through ``_parse_message``."""
    from patina.adapters.email_imap import ImapEmailAdapter

    class _Port(ImapEmailAdapter):
        def list_inbox(self, since: float) -> list[EmailMessage]:
            return [self._parse_message(raw) for raw in raw_messages]

        def search_sent(self, query: str) -> list[EmailMessage]:
            return []

    return _Port(host="imap.example.com", port=993, username="owner@example.com", password="x")


def _snapshot(home) -> dict:
    """Stored observation columns, dedupe keys and entities, minus ``metadata["source"]``."""
    import json

    conn = connect(get_db_path(home))
    obs = conn.execute(
        "SELECT o.id, o.channel_id, o.thread_id, o.timestamp, o.metadata, e.name AS sender"
        " FROM observations o LEFT JOIN entities e ON e.id = o.sender_entity_id ORDER BY o.id"
    ).fetchall()
    ents = conn.execute("SELECT id, type, name, aliases FROM entities ORDER BY id").fetchall()
    conn.close()
    observations = []
    for r in obs:
        meta = json.loads(r["metadata"])
        meta.pop("source", None)
        observations.append(
            {
                "id": r["id"],
                "channel_id": r["channel_id"],
                "thread_id": r["thread_id"],
                "timestamp": r["timestamp"],
                "sender": r["sender"],
                "metadata": meta,
            }
        )
    entities = [(r["id"], r["type"], r["name"], r["aliases"]) for r in ents]
    return {"observations": observations, "entities": entities}


def _ingest_source(port, source: str, home) -> dict:
    """Ingest through ``ingest_live`` and return the single stored ``metadata["source"]``."""
    result = ingest_live(port=port, source=source, home=home, lookback_days=10000)
    assert result["messages_inserted"] == 1
    (row,) = _stored_email_rows(home)
    return row["metadata"].get("source", {})


def _assert_no_placeholders(source: dict) -> None:
    for value in source.values():
        assert value not in (None, "", 0, [])


def test_calendar_source_facts_live_shape(tmp_path):
    """AC: calendar event stores event id, organizer key and attendees as given."""
    raw = LIVE_SHAPE_CALENDAR_EVENT
    source = _ingest_source(
        _RawCalendarPort([raw]), "outlook_mcp_calendar", tmp_path / "patina_home"
    )

    assert source["message_id"] == raw["meetingId"]
    assert source["sender_key"] == raw["organizer"]["email"]
    assert source["attendees"] == raw["attendees"]
    assert source["attendees"][1]["name"] == "Müller, Avery"
    _assert_no_placeholders(source)


def test_calendar_source_facts_omit_absent_attendees(tmp_path):
    """AC: no attendees key -> no attendee key (not an empty list), no placeholders."""
    raw = _without(LIVE_SHAPE_CALENDAR_EVENT, "attendees")
    source = _ingest_source(
        _RawCalendarPort([raw]), "outlook_mcp_calendar", tmp_path / "patina_home"
    )

    assert "attendees" not in source
    _assert_no_placeholders(source)
    assert source["message_id"] == raw["meetingId"]


def test_calendar_source_facts_omit_absent_id_and_organizer(tmp_path):
    """AC: no meetingId/organizer -> no message_id/sender_key; organizer_dn unchanged."""
    raw = _without(LIVE_SHAPE_CALENDAR_EVENT, "meetingId", "organizer")
    home = tmp_path / "patina_home"
    ingest_live(port=_RawCalendarPort([raw]), source="outlook_mcp_calendar", home=home)

    (row,) = _stored_email_rows(home)
    source = row["metadata"]["source"]
    assert "message_id" not in source
    assert "sender_key" not in source
    assert source["attendees"] == raw["attendees"]
    _assert_no_placeholders(source)
    assert "organizer_dn" not in row["metadata"]


def test_slack_mcp_source_facts(tmp_path):
    """AC: slack_mcp keeps ts, channel id and raw user id, unmodified."""
    raw = LIVE_SHAPE_SLACK_MCP_MESSAGE
    source = _ingest_source(_slack_mcp_port([raw]), "slack_mcp", tmp_path / "patina_home")

    assert source == {
        "message_id": raw["ts"],
        "channel_id": raw["channel"]["id"],
        "sender_key": raw["user"],
        "received_raw": raw["ts"],
    }


def test_slack_mcp_source_facts_omit_absent_user(tmp_path):
    """AC: a message with no user id has no sender_key and no placeholders."""
    raw = _without(LIVE_SHAPE_SLACK_MCP_MESSAGE, "user")
    source = _ingest_source(_slack_mcp_port([raw]), "slack_mcp", tmp_path / "patina_home")

    assert "sender_key" not in source
    _assert_no_placeholders(source)
    assert source["message_id"] == raw["ts"]


def test_slack_live_source_facts(tmp_path):
    """AC: slack_live keeps ts, channel id and raw user id, unmodified."""
    raw = LIVE_SHAPE_SLACK_LIVE_MESSAGE
    source = _ingest_source(_slack_live_port([raw]), "slack_live", tmp_path / "patina_home")

    assert source == {
        "message_id": raw["ts"],
        "channel_id": SLACK_LIVE_DM_CHANNEL,
        "sender_key": raw["user"],
        "received_raw": raw["ts"],
    }


def test_slack_live_mention_source_facts_omit_absent_channel(tmp_path):
    """AC: a search match with no channel has no channel_id key and no placeholders."""
    mention = {"user": "U0EXAMPLE04", "text": "The quick brown fox", "ts": "1781653000.000200"}
    source = _ingest_source(
        _slack_live_port([], mentions=[mention]), "slack_live", tmp_path / "patina_home"
    )

    assert source == {
        "message_id": mention["ts"],
        "sender_key": mention["user"],
        "received_raw": mention["ts"],
    }


def test_imap_source_facts_live_shape(tmp_path):
    """AC: IMAP keeps Message-ID, From, To, Cc and the raw Date string as given."""
    source = _ingest_source(_imap_port([LIVE_SHAPE_IMAP_MESSAGE]), "imap", tmp_path / "patina_home")

    assert source == {
        "message_id": "<CAexample001@mail.example.com>",
        "sender_key": '"Example, Jordan" <jordan.example@example.com>',
        "to": '"Owner, Jane" <owner@example.com>, avery.muller@example.com',
        "cc": "=?utf-8?q?M=C3=BCller=2C_Avery?= <avery.muller@example.com>",
        "received_raw": "Tue, 03 Nov 2026 09:15:42 -0600",
    }


def test_imap_source_facts_omit_absent_cc_and_to(tmp_path):
    """AC: no Cc (or To) header -> no ``cc`` (or ``to``) key, not an empty value."""
    no_cc = LIVE_SHAPE_IMAP_MESSAGE.replace(
        b"Cc: =?utf-8?q?M=C3=BCller=2C_Avery?= <avery.muller@example.com>\r\n", b""
    )
    source = _ingest_source(_imap_port([no_cc]), "imap", tmp_path / "cc")
    assert "cc" not in source
    assert source["to"] == '"Owner, Jane" <owner@example.com>, avery.muller@example.com'
    _assert_no_placeholders(source)

    no_to = no_cc.replace(
        b'To: "Owner, Jane" <owner@example.com>, avery.muller@example.com\r\n', b""
    )
    source = _ingest_source(_imap_port([no_to]), "imap", tmp_path / "to")
    assert "to" not in source
    assert "cc" not in source
    _assert_no_placeholders(source)


# Values the pre-change code produced for each fixture (dedupe key = observation id).
_PRE_CHANGE = {
    "calendar": {
        "id": "957eb453f0b7aab9",
        "channel_id": "calendar:AAMkADExampleEvt001=",
        "thread_id": None,
        "timestamp": 1793826000.0,
        "sender": "jordan.example@example.com",
        "metadata": {
            "channel_name": None,
            "reactions": [],
            "organizer_dn": "jordan.example@example.com",
        },
        "entities": [("299cda95d3ab4c19", "jordan.example@example.com")],
    },
    "slack_mcp": {
        "id": "af8c5d99acc02558",
        "channel_id": "D0EXAMPLE01",
        "thread_id": "1781650000.000100",
        "timestamp": 1781651078.945749,
        "sender": "Jordan Example",
        "metadata": {
            "channel_name": "jordan.example",
            "reactions": [{"name": "eyes", "users": ["U0EXAMPLE02"]}],
            "sender_slack_id": "U0EXAMPLE01",
        },
        "entities": [("31a5b1c7e1f4fc34", "Jordan Example")],
    },
    "slack_live": {
        "id": "09cb5eeb31d1411d",
        "channel_id": "D0EXAMPLE03",
        "thread_id": None,
        "timestamp": 1781652000.123456,
        "sender": "U0EXAMPLE03",
        "metadata": {
            "channel_name": "",
            "reactions": [{"name": "thumbsup", "users": ["U0EXAMPLE01"], "count": 1}],
            "sender_slack_id": "U0EXAMPLE03",
        },
        "entities": [("5628c694c4a28714", "U0EXAMPLE03")],
    },
    "imap": {
        "id": "ae717383ba73a43d",
        "channel_id": "email:<CAexample000@mail.example.com>",
        "thread_id": "<CAexample000@mail.example.com>",
        "timestamp": 1793718942.0,
        "sender": '"Example, Jordan" <jordan.example@example.com>',
        "metadata": {"channel_name": None, "reactions": []},
        "entities": [("5287242857412ac4", '"Example, Jordan" <jordan.example@example.com>')],
    },
}

_REGRESSION_CASES = {
    "calendar": (
        lambda: _RawCalendarPort([LIVE_SHAPE_CALENDAR_EVENT]),
        "outlook_mcp_calendar",
        "patina.adapters.outlook_mcp",
    ),
    "slack_mcp": (
        lambda: _slack_mcp_port([LIVE_SHAPE_SLACK_MCP_MESSAGE]),
        "slack_mcp",
        "patina.adapters.slack_mcp",
    ),
    "slack_live": (
        lambda: _slack_live_port([LIVE_SHAPE_SLACK_LIVE_MESSAGE]),
        "slack_live",
        "patina.adapters.slack_live",
    ),
    "imap": (
        lambda: _imap_port([LIVE_SHAPE_IMAP_MESSAGE]),
        "imap",
        "patina.adapters.email_imap",
    ),
}


@pytest.mark.parametrize("case", sorted(_REGRESSION_CASES))
def test_source_facts_leave_columns_dedupe_and_entities_unchanged(tmp_path, monkeypatch, case):
    """AC: thread/channel/sender/timestamp, dedupe key and entities match pre-change values."""
    import importlib

    make_port, source, module_name = _REGRESSION_CASES[case]
    expected = _PRE_CHANGE[case]

    with_facts = tmp_path / "with_facts"
    ingest_live(port=make_port(), source=source, home=with_facts, lookback_days=10000)
    snap = _snapshot(with_facts)

    (obs,) = snap["observations"]
    for key in ("id", "channel_id", "thread_id", "timestamp", "sender", "metadata"):
        assert obs[key] == expected[key], key
    assert [(e[0], e[2]) for e in snap["entities"]] == expected["entities"]

    # Re-ingest with the adapter writing no source facts (the pre-change rows):
    # every column, dedupe key and entity must come out identical.
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, "put_fact", lambda facts, key, value: None)
    without_facts = tmp_path / "without_facts"
    ingest_live(port=make_port(), source=source, home=without_facts, lookback_days=10000)
    (row,) = _stored_email_rows(without_facts)
    assert "source" not in row["metadata"]
    assert _snapshot(without_facts) == snap

    # Second run over the same store dedupes on the unchanged key.
    again = ingest_live(port=make_port(), source=source, home=with_facts, lookback_days=10000)
    assert again["messages_skipped"] == 1
    assert again["messages_inserted"] == 0


def _relevance_live_items() -> dict[str, dict]:
    """Live-shape inbox items for the direct, distribution-list and bot cases (#617)."""
    direct = LIVE_SHAPE_INBOX_ITEM
    dl_only = {
        **LIVE_SHAPE_INBOX_ITEM,
        "conversationId": "AAQkADExampleConv003=",
        "id": "AAMkADExampleMsg003=",
        "toRecipients": [
            {"name": "Team All", "email": "team-all@example.com", "isDistributionList": True},
        ],
        "ccRecipients": [{"name": "Lee, Casey", "email": "casey.lee@example.com"}],
    }
    bot = {
        **LIVE_SHAPE_INBOX_ITEM,
        "conversationId": "AAQkADExampleConv004=",
        "id": "AAMkADExampleMsg004=",
        "topic": "Your weekly digest — The quick brown fox",
        "senders": ["no-reply@example.com"],
    }
    return {"direct": direct, "dl_only": dl_only, "bot": bot}


_RELEVANCE_EXPECTED = {
    "direct": (True, "direct"),
    "dl_only": (False, "not_direct"),
    "bot": (False, "bot_or_list"),
}


def _write_owner_email(home) -> None:
    import yaml

    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(yaml.dump({"owner": {"emails": ["owner@example.com"]}}))


def test_outlook_relevance_on_live_shape_adapter_output(tmp_path):
    """AC: OutlookMcpAdapter output with #611 source facts drives outlook_relevance."""
    import json
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from patina.adapters.outlook_mcp import OutlookMcpAdapter
    from patina.ingest import outlook_relevance

    home = tmp_path / "patina_home"
    _write_owner_email(home)
    items = _relevance_live_items()

    payload = json.dumps({"emails": list(items.values())}, ensure_ascii=False)
    bridge = MagicMock()
    bridge.call_tool.return_value = SimpleNamespace(
        isError=False, content=[SimpleNamespace(text=payload)]
    )
    emails = {em.source_facts["message_id"]: em for em in OutlookMcpAdapter(bridge).list_inbox(0)}

    for case, raw in items.items():
        em = emails[raw["id"]]
        result = outlook_relevance(
            em.source_facts,
            thread_participants=raw["senders"],
            subject=em.subject,
            objectives=[],
            home=home,
        )
        assert tuple(result) == _RELEVANCE_EXPECTED[case], case


def test_outlook_relevance_on_stored_live_shape_source_facts(tmp_path):
    """AC: the same decisions hold for the metadata["source"] that ingest stores."""
    from patina.ingest import outlook_relevance

    home = tmp_path / "patina_home"
    _write_owner_email(home)
    items = _relevance_live_items()
    ingest_live(
        port=_RawEmailPort(list(items.values())),
        source="outlook_mcp_email",
        home=home,
        lookback_days=10000,
    )

    by_thread = {r["thread_id"]: r["metadata"]["source"] for r in _stored_email_rows(home)}
    assert len(by_thread) == len(items)
    for case, raw in items.items():
        result = outlook_relevance(by_thread[raw["conversationId"]], objectives=[], home=home)
        assert tuple(result) == _RELEVANCE_EXPECTED[case], case


# --- #618: relevance filter at Outlook ingest ---

_JORDAN = "Example, Jordan (Contractor)"
_OWNER_TO = [
    {"name": "Owner, Jane", "email": "owner@example.com"},
    {"name": "Müller, Avery", "email": "avery.muller@example.com"},
]
_TEAM_ALL_TO = [{"name": "Team All", "email": "team-all@example.com", "isDistributionList": True}]
_CC_CASEY = [{"name": "Lee, Casey", "email": "casey.lee@example.com"}]


def _filter_home(tmp_path, *, enabled: bool = True):
    import yaml

    home = tmp_path / "patina_home"
    home.mkdir(parents=True, exist_ok=True)
    config = {"owner": {"emails": ["owner@example.com"]}}
    if enabled:
        config["ingest"] = {"outlook_relevance_filter": True}
    (home / "config.yaml").write_text(yaml.dump(config))
    return home


def _inbox_item(n: int, **overrides) -> dict:
    """Live-shape inbox item with its own conversation/message id and received time."""
    item = dict(LIVE_SHAPE_INBOX_ITEM)
    item["conversationId"] = f"AAQkADExampleConv6{n:02d}="
    item["id"] = f"AAMkADExampleMsg6{n:02d}="
    item["receivedDateTime"] = f"2026-11-03T09:{n:02d}:42Z"
    item.update(overrides)
    return item


def _direct_item(n: int = 1) -> dict:
    return _inbox_item(n, toRecipients=_OWNER_TO, ccRecipients=_CC_CASEY, senders=[_JORDAN])


def _dl_only_item(n: int = 2, *, senders: list[str] | None = None, **overrides) -> dict:
    return _inbox_item(
        n,
        toRecipients=_TEAM_ALL_TO,
        ccRecipients=_CC_CASEY,
        senders=senders or [_JORDAN],
        **overrides,
    )


def _bot_item(n: int, sender: str) -> dict:
    return _inbox_item(
        n,
        topic="Your weekly digest — The quick brown fox",
        toRecipients=_OWNER_TO,
        senders=[sender],
    )


def _customer_item(n: int = 7) -> dict:
    return _dl_only_item(n, senders=["dana.placeholder@customer.example.com"])


def _add_fox_objective(home, **kwargs):
    from patina.priority.objectives import add_objective

    return add_objective("Fox launch", "quick brown fox", home=home, **kwargs)


def _ingest_outlook(home, items):
    return ingest_live(
        port=_RawEmailPort(items), source="outlook_mcp_email", home=home, lookback_days=10000
    )


def _table_rows(home, table: str) -> list[tuple]:
    conn = connect(get_db_path(home))
    try:
        return [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()]
    finally:
        conn.close()


def test_relevance_filter_keeps_direct_email(tmp_path):
    """AC: Owner as a named To recipient + person sender -> one observation, kept ``direct``."""
    home = _filter_home(tmp_path)
    result = _ingest_outlook(home, [_direct_item()])

    assert result["messages_inserted"] == 1
    assert result["relevance"] == {"direct": 1}
    assert len(_stored_email_rows(home)) == 1


def test_relevance_filter_drops_distribution_list_only_email(tmp_path):
    """AC: Owner reached only via team-all@example.com, no objective -> dropped_not_direct."""
    home = _filter_home(tmp_path)
    result = _ingest_outlook(home, [_dl_only_item()])

    assert result["messages_inserted"] == 0
    assert result["relevance"] == {"dropped_not_direct": 1}
    assert _stored_email_rows(home) == []


@pytest.mark.parametrize("sender", ["no-reply@example.com", "notifications@tool.example"])
def test_relevance_filter_drops_bot_sender(tmp_path, sender):
    """AC: a no-reply / notifications sender with the Owner in To -> dropped_bot_or_list."""
    home = _filter_home(tmp_path)
    result = _ingest_outlook(home, [_bot_item(3, sender)])

    assert result["messages_inserted"] == 0
    assert result["relevance"] == {"dropped_bot_or_list": 1}
    assert _stored_email_rows(home) == []


def test_relevance_filter_dropped_email_writes_nothing(tmp_path, monkeypatch):
    """AC: a dropped email adds no observation, no entity and no extraction input."""
    import patina.ingest as ingest_mod

    home = _filter_home(tmp_path)
    _ingest_outlook(home, [_direct_item(1)])
    obs_before = _table_rows(home, "observations")
    entities_before = _table_rows(home, "entities")

    seen_texts: list[str] = []
    real_extract = ingest_mod.extract_entities_from_text

    def _spy(text, *args, **kwargs):
        seen_texts.append(text)
        return real_extract(text, *args, **kwargs)

    monkeypatch.setattr(ingest_mod, "extract_entities_from_text", _spy)
    dropped = _dl_only_item(
        4,
        senders=["Placeholder, Taylor"],
        topic="Quarterly sync with Morgan Sample",
        preview="Taylor Placeholder asked Quinn Fictional about the lazy dog.",
    )
    result = _ingest_outlook(home, [dropped])

    assert result["relevance"] == {"dropped_not_direct": 1}
    assert result["messages_inserted"] == 0
    assert _table_rows(home, "observations") == obs_before
    assert _table_rows(home, "entities") == entities_before
    assert seen_texts == []


def test_relevance_filter_subject_keyword_alone_is_dropped(tmp_path):
    """AC: a subject matching an objective keyword is not a keep signal on its own."""
    home = _filter_home(tmp_path)
    _add_fox_objective(
        home,
        participants=["riley.sample@example.com"],
        customer_domains=["customer.example.com"],
    )
    result = _ingest_outlook(home, [_dl_only_item(5, topic="The quick brown fox — launch notes")])

    assert result["relevance"] == {"dropped_not_direct": 1}
    assert _stored_email_rows(home) == []


def test_relevance_filter_keeps_active_objective_engagement(tmp_path):
    """AC: an active objective's participant or customer domain, Owner not in To -> kept."""
    home = _filter_home(tmp_path)
    _add_fox_objective(
        home,
        participants=["riley.sample@example.com"],
        customer_domains=["customer.example.com"],
    )
    from_participant = _dl_only_item(6, senders=["riley.sample@example.com"])
    result = _ingest_outlook(home, [from_participant, _customer_item()])

    assert result["relevance"] == {"engagement": 2}
    assert result["messages_inserted"] == 2


def test_relevance_filter_drops_inactive_objective_customer_domain(tmp_path):
    """AC: the same customer domain with the objective inactive is dropped."""
    from patina.priority.objectives import remove_objective

    home = _filter_home(tmp_path)
    obj = _add_fox_objective(home, customer_domains=["customer.example.com"])
    assert remove_objective(obj.id, home=home)
    result = _ingest_outlook(home, [_customer_item()])

    assert result["relevance"] == {"dropped_not_direct": 1}
    assert _stored_email_rows(home) == []


def test_relevance_filter_counts_every_decision(tmp_path):
    """AC: a per-reason count for every decision, summing to the emails fetched."""
    home = _filter_home(tmp_path)
    _add_fox_objective(home, customer_domains=["customer.example.com"])
    items = [
        _direct_item(1),
        _dl_only_item(2),
        _bot_item(3, "no-reply@example.com"),
        _bot_item(8, "notifications@tool.example"),
        _customer_item(7),
    ]
    result = _ingest_outlook(home, items)

    assert result["relevance"] == {
        "direct": 1,
        "engagement": 1,
        "dropped_not_direct": 1,
        "dropped_bot_or_list": 2,
    }
    assert sum(result["relevance"].values()) == len(items)
    assert result["messages_inserted"] == 2


def test_relevance_filter_counts_undated_email(tmp_path):
    """Undated emails still get a decision, so the counts match the emails fetched."""
    home = _filter_home(tmp_path)
    undated = _without(_direct_item(9), "receivedDateTime")
    result = _ingest_outlook(home, [_direct_item(1), undated, _dl_only_item(2)])

    assert result["relevance"] == {"direct": 2, "dropped_not_direct": 1}
    assert result["skip_reasons"] == {"missing_timestamp": 1}
    assert result["messages_inserted"] == 1


def test_relevance_filter_off_by_default(tmp_path):
    """Without ``ingest.outlook_relevance_filter`` every email is ingested as before."""
    home = _filter_home(tmp_path, enabled=False)
    result = _ingest_outlook(home, [_direct_item(1), _dl_only_item(2)])

    assert result["messages_inserted"] == 2
    assert result["relevance"] == {}


def test_relevance_filter_applies_to_outlook_only(tmp_path):
    """Non-Outlook email sources are never filtered."""
    home = _filter_home(tmp_path)
    result = ingest_live(
        port=_RawEmailPort([_dl_only_item(2)]), source="imap", home=home, lookback_days=10000
    )

    assert result["messages_inserted"] == 1
    assert result["relevance"] == {}


# --- #641: live email_inbox shape (recipients strings, itemIds, no id/To/Cc) ---

LIVE_INBOX_ITEM_641 = {
    "conversationId": "AAQkADExampleConv641=",
    "topic": "RE: The quick brown fox — Q4 plan",
    "senders": ["Example, Jordan (Contractor)", "Sample, Riley"],
    "recipients": ["Owner, Jane", "Müller, Avery", "Lee, Casey"],
    "lastDeliveryTime": "2026-11-07T16:42:05Z",
    "preview": "The quick brown fox jumps over the lazy dog.",
    "unreadCount": 1,
    "hasAttachments": False,
    "messageCount": 2,
    "itemClasses": ["IPM.Note", "IPM.Note"],
    "itemIds": ["AAMkADExampleItem641a=", "AAMkADExampleItem641b="],
}

_LIVE_641_KEYS = {
    "conversationId",
    "topic",
    "senders",
    "recipients",
    "lastDeliveryTime",
    "preview",
    "unreadCount",
    "hasAttachments",
    "messageCount",
    "itemClasses",
    "itemIds",
}


def _live_641_item(n: int, **overrides) -> dict:
    item = dict(LIVE_INBOX_ITEM_641)
    item["conversationId"] = f"AAQkADExampleConv641{n:02d}="
    item["itemIds"] = [f"AAMkADExampleItem641{n:02d}="]
    item["lastDeliveryTime"] = f"2026-11-07T16:{n:02d}:05Z"
    item.update(overrides)
    return item


def _live_filter_home(tmp_path):
    """Filter on; the Owner is known by the display name live ``recipients`` use."""
    import yaml

    home = tmp_path / "patina_home"
    home.mkdir(parents=True, exist_ok=True)
    config = {
        "owner": {"emails": ["owner@example.com"], "display_names": ["Owner, Jane"]},
        "ingest": {"outlook_relevance_filter": True},
    }
    (home / "config.yaml").write_text(yaml.dump(config))
    return home


def test_live_641_fixture_has_exactly_the_live_keys():
    assert set(LIVE_INBOX_ITEM_641) == _LIVE_641_KEYS
    assert all(isinstance(r, str) for r in LIVE_INBOX_ITEM_641["recipients"])


def test_live_inbox_source_facts_carry_item_id_and_recipients(tmp_path):
    """AC: message_id comes from itemIds; recipients stored as given; no to/cc keys."""
    home = tmp_path / "patina_home"
    ingest_live(
        port=_RawEmailPort([LIVE_INBOX_ITEM_641]),
        source="outlook_mcp_email",
        home=home,
        lookback_days=10000,
    )

    (row,) = _stored_email_rows(home)
    source = row["metadata"]["source"]
    assert source["message_id"] == "AAMkADExampleItem641a="
    assert source["recipients"] == LIVE_INBOX_ITEM_641["recipients"]
    assert "to" not in source
    assert "cc" not in source
    assert source["sender_key"] == "Example, Jordan (Contractor)"
    assert source["received_raw"] == LIVE_INBOX_ITEM_641["lastDeliveryTime"]
    assert row["thread_id"] == LIVE_INBOX_ITEM_641["conversationId"]


@pytest.mark.parametrize("item_ids", [None, [], [""]])
def test_live_inbox_message_id_falls_back_to_conversation_id(item_ids):
    """AC: with no usable itemIds the conversation id is the message_id."""
    from patina.adapters.outlook_mcp import _email_from_raw

    raw = _without(LIVE_INBOX_ITEM_641, "itemIds")
    if item_ids is not None:
        raw["itemIds"] = item_ids
    em = _email_from_raw(raw)
    assert em.source_facts["message_id"] == raw["conversationId"]


def test_relevance_filter_keeps_owner_named_in_live_recipients(tmp_path):
    """AC: the Owner listed in live ``recipients`` strings is kept as direct."""
    home = _live_filter_home(tmp_path)
    result = _ingest_outlook(home, [LIVE_INBOX_ITEM_641])

    assert result["relevance"] == {"direct": 1}
    assert result["messages_inserted"] == 1


def test_relevance_filter_live_recipients_rule(tmp_path):
    """Any Owner match in ``recipients`` keeps (To and Cc are not split live);
    a list-only email, where ``recipients`` names the list, not the Owner, drops."""
    home = _live_filter_home(tmp_path)
    owner_last = _live_641_item(1, recipients=["Müller, Avery", "Lee, Casey", "Owner, Jane"])
    owner_case = _live_641_item(2, recipients=["owner, jane"])
    list_only = _live_641_item(3, recipients=["Team All", "Lee, Casey"])
    bot = _live_641_item(4, senders=["no-reply@example.com"])
    result = _ingest_outlook(home, [owner_last, owner_case, list_only, bot])

    assert result["relevance"] == {
        "direct": 2,
        "dropped_not_direct": 1,
        "dropped_bot_or_list": 1,
    }


def test_relevance_live_recipients_count_as_engagement(tmp_path):
    """An active objective participant named only in ``recipients`` is engagement."""
    home = _live_filter_home(tmp_path)
    _add_fox_objective(home, participants=["Lee, Casey"])
    item = _live_641_item(5, recipients=["Team All", "Lee, Casey"])
    result = _ingest_outlook(home, [item])

    assert result["relevance"] == {"engagement": 1}


def test_dry_run_counts_inbox_once_across_email_and_calendar_adapters(tmp_path, monkeypatch):
    """AC: email and calendar adapters share outlook_mcp; fetched == distinct items."""
    from patina.ingest import ingest_all

    home = _live_filter_home(tmp_path)
    items = [
        LIVE_INBOX_ITEM_641,
        _live_641_item(1, recipients=["Müller, Avery"]),
        _live_641_item(2, senders=["no-reply@example.com"]),
    ]
    monkeypatch.setattr(
        "patina.ingest._load_adapters",
        lambda home: [
            ("outlook_mcp_email", _RawEmailPort(items)),
            ("outlook_mcp_calendar", _RawEmailPort(items)),
        ],
    )
    result = ingest_all(home=home, lookback_days=10000, dry_run=True)

    assert result["adapters_run"] == 2
    assert sum(result["relevance"].values()) == len(items)
    assert result["relevance"] == {
        "direct": 1,
        "dropped_not_direct": 1,
        "dropped_bot_or_list": 1,
    }
    assert not get_db_path(home).exists()


def test_relevance_dry_run_counts_without_creating_store(tmp_path):
    """ingest_live(dry_run=True) counts decisions (even with the filter off), writes nothing."""
    home = _filter_home(tmp_path, enabled=False)
    result = ingest_live(
        port=_RawEmailPort([_direct_item(1), _dl_only_item(2)]),
        source="outlook_mcp_email",
        home=home,
        lookback_days=10000,
        dry_run=True,
    )

    # No store: the display-name sender of the dropped email has no known address.
    assert result == {
        "relevance": {"direct": 1, "dropped_not_direct": 1},
        "sender_unresolved": 1,
    }
    assert not get_db_path(home).exists()


# --- #633: customer-domain engagement on live (display-name sender) items ---

# #641 live shape: display-name senders and recipients, Owner not named.
_CUSTOMER_LIVE_RECIPIENTS = ["Team All", "Lee, Casey"]


def _seed_sender_entity(home, name: str, aliases: list[str]) -> None:
    """A store entity for the sender, holding its email alias."""
    from patina.graph import upsert_entity
    from patina.models import Entity
    from patina.store import init_db

    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    try:
        upsert_entity(conn, Entity(id="ent-jordan", type="person", name=name, aliases=aliases))
        conn.commit()
    finally:
        conn.close()


def _dry_run_outlook(home, items):
    return ingest_live(
        port=_RawEmailPort(items),
        source="outlook_mcp_email",
        home=home,
        lookback_days=10000,
        dry_run=True,
    )


def test_live_sender_resolved_from_store_customer_domain_is_engagement(tmp_path):
    """AC: sender address resolves to partner.example, Owner not named, active -> engagement."""
    home = _live_filter_home(tmp_path)
    _seed_sender_entity(home, "Example, Jordan", ["jordan.example@partner.example"])
    _add_fox_objective(home, customer_domains=["partner.example"])
    item = _live_641_item(20, recipients=_CUSTOMER_LIVE_RECIPIENTS)
    assert item["senders"][0] == "Example, Jordan (Contractor)"

    result = _dry_run_outlook(home, [item])

    assert result == {"relevance": {"engagement": 1}, "sender_unresolved": 0}


def test_live_sender_resolved_from_store_inactive_objective_is_dropped(tmp_path):
    """AC: the same email with the objective inactive -> dropped not_direct."""
    from patina.priority.objectives import remove_objective

    home = _live_filter_home(tmp_path)
    _seed_sender_entity(home, "Example, Jordan", ["jordan.example@partner.example"])
    obj = _add_fox_objective(home, customer_domains=["partner.example"])
    assert remove_objective(obj.id, home=home)

    result = _dry_run_outlook(home, [_live_641_item(21, recipients=_CUSTOMER_LIVE_RECIPIENTS)])

    # Resolved, so not counted as unresolved: the objective is just inactive.
    assert result == {"relevance": {"dropped_not_direct": 1}, "sender_unresolved": 0}


def test_live_sender_resolved_from_store_keeps_under_filter(tmp_path):
    """With the filter on, the customer's email is ingested; its stored facts are unchanged."""
    home = _live_filter_home(tmp_path)
    _seed_sender_entity(home, "Example, Jordan", ["jordan.example@partner.example"])
    _add_fox_objective(home, customer_domains=["partner.example"])

    result = _ingest_outlook(home, [_live_641_item(22, recipients=_CUSTOMER_LIVE_RECIPIENTS)])

    assert result["relevance"] == {"engagement": 1}
    assert result["sender_unresolved"] == 0
    assert result["messages_inserted"] == 1
    (row,) = _stored_email_rows(home)
    assert "sender_address" not in row["metadata"]["source"]


def test_live_sender_unresolved_is_dropped_and_counted(tmp_path):
    """AC: a sender with no known address -> dropped not_direct, counted as unresolved."""
    home = _live_filter_home(tmp_path)
    _seed_sender_entity(home, "Sample, Riley", ["riley.sample@partner.example"])
    _add_fox_objective(home, customer_domains=["partner.example"])
    item = _live_641_item(23, recipients=_CUSTOMER_LIVE_RECIPIENTS)

    result = _dry_run_outlook(home, [item])

    assert result == {"relevance": {"dropped_not_direct": 1}, "sender_unresolved": 1}


def test_dry_run_all_totals_sender_unresolved(tmp_path, monkeypatch):
    from patina.ingest import ingest_all

    home = _live_filter_home(tmp_path)
    items = [
        LIVE_INBOX_ITEM_641,
        _live_641_item(24, recipients=_CUSTOMER_LIVE_RECIPIENTS),
        _live_641_item(25, senders=["no-reply@example.com"], recipients=["Lee, Casey"]),
    ]
    monkeypatch.setattr(
        "patina.ingest._load_adapters",
        lambda home: [("outlook_mcp_email", _RawEmailPort(items))],
    )

    result = ingest_all(home=home, lookback_days=10000, dry_run=True)

    assert result["relevance"] == {
        "direct": 1,
        "dropped_not_direct": 1,
        "dropped_bot_or_list": 1,
    }
    assert result["sender_unresolved"] == 1


@pytest.mark.parametrize(
    ("participant", "recipients"),
    [
        ("Müller, Avery (Contractor)", ["Team All", "Müller, Avery"]),
        ("Müller, Avery", ["Team All", "Müller, Avery (Contractor)"]),
    ],
)
def test_live_participant_with_suffix_matches_thread(tmp_path, participant, recipients):
    """AC: a participant stored as "Müller, Avery (Contractor)" matches the same person."""
    home = _live_filter_home(tmp_path)
    _add_fox_objective(home, participants=[participant])

    result = _dry_run_outlook(home, [_live_641_item(26, recipients=recipients)])

    assert result["relevance"] == {"engagement": 1}


def test_live_participant_stored_as_address_matches_resolved_sender(tmp_path):
    """A participant stored as an address matches a sender named on the thread only by name."""
    home = _live_filter_home(tmp_path)
    _seed_sender_entity(home, "Example, Jordan", ["jordan.example@partner.example"])
    _add_fox_objective(home, participants=["jordan.example@partner.example"])

    result = _dry_run_outlook(home, [_live_641_item(27, recipients=_CUSTOMER_LIVE_RECIPIENTS)])

    assert result["relevance"] == {"engagement": 1}
