from __future__ import annotations

import time

import yaml

from patina.ingest import ingest_live
from patina.models import ChatMessage, DmChannel
from patina.store import connect, get_db_path, init_db, kv_get, run_pending_migrations

OWNER_USER_ID = "U00000OWNER"


def _setup_home(tmp_path):
    home = tmp_path / "patina_home"
    home.mkdir()
    config = {"owner": {"user_ids": [OWNER_USER_ID]}}
    (home / "config.yaml").write_text(yaml.dump(config))
    return home


class MockAutoWatchPort:
    """Mock port that supports list_dms for auto-watch and DM ingestion."""

    def __init__(self, dm_channels: list[DmChannel], channel_messages=None):
        self._dm_channels = dm_channels
        self._channel_messages = channel_messages or {}
        self.list_dms_call_count = 0

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

    def list_dms(self, include_dormant: bool = False) -> list[DmChannel]:
        self.list_dms_call_count += 1
        return self._dm_channels


def test_auto_watch_registers_discovered_channel(tmp_path):
    """After ingest_live, watched_channels has a row for the auto-discovered group DM."""
    home = _setup_home(tmp_path)
    port = MockAutoWatchPort(
        [
            DmChannel(channel_id="C_NEW_MPIM", is_group=True, last_activity_ts=time.time()),
        ]
    )

    ingest_live(port=port, source="slack_mcp", home=home)

    conn = connect(get_db_path(home))
    row = conn.execute(
        "SELECT channel_name, reason FROM watched_channels WHERE channel_id = 'C_NEW_MPIM'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["channel_name"] == "C_NEW_MPIM"
    assert row["reason"] == "auto-detected: user is participant"


def test_auto_watch_no_duplicates_on_second_run(tmp_path):
    """Running ingest_live twice does not produce duplicate rows."""
    home = _setup_home(tmp_path)
    port = MockAutoWatchPort(
        [
            DmChannel(channel_id="C_MPIM01", is_group=True, last_activity_ts=time.time()),
            DmChannel(channel_id="C_MPIM02", is_group=True, last_activity_ts=time.time()),
        ]
    )

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

    port = MockAutoWatchPort(
        [
            DmChannel(channel_id="C_MANUAL", is_group=True, last_activity_ts=time.time()),
        ]
    )
    ingest_live(port=port, source="slack_mcp", home=home)

    conn = connect(db_path)
    row = conn.execute(
        "SELECT reason FROM watched_channels WHERE channel_id = 'C_MANUAL'"
    ).fetchone()
    conn.close()
    assert row["reason"] == "oncall duty"


def test_auto_watch_messages_ingested_same_run(tmp_path):
    """Messages from auto-discovered group DMs are ingested in the same run."""
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
    port = MockAutoWatchPort(
        [DmChannel(channel_id="C_DISC01", is_group=True, last_activity_ts=time.time())],
        channel_messages,
    )

    result = ingest_live(port=port, source="slack_mcp", home=home)

    assert result["messages_inserted"] >= 1
    conn = connect(get_db_path(home))
    row = conn.execute("SELECT text FROM observations WHERE channel_id = 'C_DISC01'").fetchone()
    conn.close()
    assert row is not None
    assert "Hello from discovered channel" in row["text"]


def test_auto_watch_empty_discovery_no_error(tmp_path):
    """If list_dms returns empty, ingest completes without error."""
    home = _setup_home(tmp_path)
    port = MockAutoWatchPort([])

    result = ingest_live(port=port, source="slack_mcp", home=home)

    conn = connect(get_db_path(home))
    count = conn.execute("SELECT COUNT(*) FROM watched_channels").fetchone()[0]
    conn.close()
    assert count == 0
    assert result["messages_inserted"] == 0


def test_auto_watch_non_group_dm_not_watched(tmp_path):
    """Non-group DMs from list_dms are not inserted into watched_channels."""
    home = _setup_home(tmp_path)
    port = MockAutoWatchPort(
        [
            DmChannel(channel_id="C_DIRECT_DM", is_group=False, last_activity_ts=time.time()),
        ]
    )

    ingest_live(port=port, source="slack_mcp", home=home)

    conn = connect(get_db_path(home))
    count = conn.execute("SELECT COUNT(*) FROM watched_channels").fetchone()[0]
    conn.close()
    assert count == 0


def test_list_dms_called_exactly_once(tmp_path):
    """port.list_dms is called exactly once during a full ingest_live() run."""
    home = _setup_home(tmp_path)
    port = MockAutoWatchPort(
        [
            DmChannel(channel_id="C_GRP1", is_group=True, last_activity_ts=time.time()),
            DmChannel(channel_id="C_GRP2", is_group=True, last_activity_ts=time.time()),
            DmChannel(channel_id="C_DM1", is_group=False, last_activity_ts=time.time()),
        ]
    )

    ingest_live(port=port, source="slack_mcp", home=home)

    assert port.list_dms_call_count == 1


def test_discovery_zero_streak_resets_on_group_dms(tmp_path):
    """discovery_zero_streak resets to 0 after ingest_live() finds group DMs."""
    home = _setup_home(tmp_path)
    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    run_pending_migrations(conn)
    from patina.store import kv_set

    kv_set(conn, "discovery_zero_streak", "5")
    conn.commit()
    conn.close()

    port = MockAutoWatchPort(
        [
            DmChannel(channel_id="C_GRP_NEW", is_group=True, last_activity_ts=time.time()),
        ]
    )

    result = ingest_live(port=port, source="slack_mcp", home=home)

    assert result["zero_streak"] == 0
    conn = connect(db_path)
    assert kv_get(conn, "discovery_zero_streak") == "0"
    conn.close()
