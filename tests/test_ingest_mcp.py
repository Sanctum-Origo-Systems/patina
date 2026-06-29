from __future__ import annotations

from datetime import datetime

from patina.ingest import ingest_live
from patina.models import CalendarEvent, ChatMessage, EmailMessage
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
                text="The contract is in final review stages.",
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
                text="Approved.",
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
