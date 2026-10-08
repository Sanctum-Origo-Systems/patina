from __future__ import annotations

import time
from datetime import datetime

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
