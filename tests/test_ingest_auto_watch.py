from __future__ import annotations

import yaml

from patina.ingest import ingest_live
from patina.models import ChatMessage
from patina.store import connect, get_db_path, init_db

OWNER_USER_ID = "U00000OWNER"


def _setup_home(tmp_path):
    home = tmp_path / "patina_home"
    home.mkdir()
    config = {"owner": {"user_ids": [OWNER_USER_ID]}}
    (home / "config.yaml").write_text(yaml.dump(config))
    return home


class MockAutoWatchPort:
    """Mock port that supports list_participant_channels for auto-watch."""

    def __init__(self, discovered_channels: list[tuple[str, str]], channel_messages=None):
        self._discovered = discovered_channels
        self._channel_messages = channel_messages or {}

    @property
    def platform(self) -> str:
        return "slack_mcp"

    def list_dm_messages(self, since: float) -> list[ChatMessage]:
        return []

    def list_mentions(self, since: float) -> list[ChatMessage]:
        return []

    def list_channel_messages(self, channel_id: str, since: float) -> list[ChatMessage]:
        return self._channel_messages.get(channel_id, [])

    def get_thread(self, channel_id: str, thread_id: str) -> list[ChatMessage]:
        return []

    def list_participant_channels(self, owner_user_id: str) -> list[tuple[str, str]]:
        return self._discovered


def test_auto_watch_registers_discovered_channel(tmp_path):
    """After ingest_live, watched_channels has a row for the auto-discovered channel."""
    home = _setup_home(tmp_path)
    port = MockAutoWatchPort([("C_NEW_MPIM", "team-chat")])

    ingest_live(port=port, source="slack_mcp", home=home)

    conn = connect(get_db_path(home))
    row = conn.execute(
        "SELECT channel_name, reason FROM watched_channels WHERE channel_id = 'C_NEW_MPIM'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["channel_name"] == "team-chat"
    assert row["reason"] == "auto-detected: user is participant"


def test_auto_watch_no_duplicates_on_second_run(tmp_path):
    """Running ingest_live twice does not produce duplicate rows."""
    home = _setup_home(tmp_path)
    port = MockAutoWatchPort([("C_MPIM01", "group-a"), ("C_MPIM02", "group-b")])

    ingest_live(port=port, source="slack_mcp", home=home)
    ingest_live(port=port, source="slack_mcp", home=home)

    conn = connect(get_db_path(home))
    count = conn.execute("SELECT COUNT(*) FROM watched_channels").fetchone()[0]
    conn.close()
    assert count == 2


def test_auto_watch_does_not_overwrite_existing_reason(tmp_path):
    """A manually-watched channel retains its original reason."""
    home = _setup_home(tmp_path)
    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO watched_channels (channel_id, channel_name, reason, added_at)"
        " VALUES ('C_MANUAL', 'ops-alerts', 'oncall duty', '2026-01-01T00:00:00')"
    )
    conn.commit()
    conn.close()

    port = MockAutoWatchPort([("C_MANUAL", "ops-alerts")])
    ingest_live(port=port, source="slack_mcp", home=home)

    conn = connect(db_path)
    row = conn.execute(
        "SELECT reason FROM watched_channels WHERE channel_id = 'C_MANUAL'"
    ).fetchone()
    conn.close()
    assert row["reason"] == "oncall duty"


def test_auto_watch_messages_ingested_same_run(tmp_path):
    """Messages from auto-discovered channels are ingested in the same run."""
    home = _setup_home(tmp_path)
    channel_messages = {
        "C_DISC01": [
            ChatMessage(
                user_id="U00000ALICE",
                text="Hello from discovered channel",
                timestamp=1781900000.0,
                channel_id="C_DISC01",
                channel_name="discovered",
                user_name="Alice Fictitious",
            ),
        ],
    }
    port = MockAutoWatchPort([("C_DISC01", "discovered")], channel_messages)

    result = ingest_live(port=port, source="slack_mcp", home=home)

    assert result["messages_inserted"] >= 1
    conn = connect(get_db_path(home))
    row = conn.execute("SELECT text FROM observations WHERE channel_id = 'C_DISC01'").fetchone()
    conn.close()
    assert row is not None
    assert "Hello from discovered channel" in row["text"]


def test_auto_watch_empty_discovery_no_error(tmp_path):
    """If list_participant_channels returns empty, ingest completes without error."""
    home = _setup_home(tmp_path)
    port = MockAutoWatchPort([])

    result = ingest_live(port=port, source="slack_mcp", home=home)

    conn = connect(get_db_path(home))
    count = conn.execute("SELECT COUNT(*) FROM watched_channels").fetchone()[0]
    conn.close()
    assert count == 0
    assert result["messages_inserted"] == 0


def test_auto_watch_no_owner_config_skips_discovery(tmp_path):
    """Without owner user_ids in config, auto-watch is skipped gracefully."""
    home = tmp_path / "patina_home"
    home.mkdir()
    (home / "config.yaml").write_text(yaml.dump({}))

    port = MockAutoWatchPort([("C_SHOULD_NOT_APPEAR", "ghost")])
    ingest_live(port=port, source="slack_mcp", home=home)

    conn = connect(get_db_path(home))
    count = conn.execute("SELECT COUNT(*) FROM watched_channels").fetchone()[0]
    conn.close()
    assert count == 0
