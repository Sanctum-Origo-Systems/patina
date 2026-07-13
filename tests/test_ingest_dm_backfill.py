from __future__ import annotations

import time

from patina.ingest import _obs_id, ingest_live
from patina.models import ChatMessage
from patina.store import connect, get_db_path

DM_TS_RECENT = time.time() - (30 * 86400)
DM_TS_STALE = time.time() - (200 * 86400)
MSG_TS = time.time() - (2 * 86400)


class MockPortWithListDms:
    def __init__(self, dm_channels=None, channel_messages=None):
        self._dm_channels = dm_channels or []
        self._channel_messages = channel_messages or {}
        self.list_dms_calls = 0
        self.list_channel_messages_calls = []

    @property
    def platform(self) -> str:
        return "slack_mcp"

    def list_dm_messages(self, since: float) -> list[ChatMessage]:
        return []

    def list_mentions(self, since: float) -> list[ChatMessage]:
        return []

    def list_channel_messages(self, channel_id: str, since: float) -> list[ChatMessage]:
        self.list_channel_messages_calls.append((channel_id, since))
        return self._channel_messages.get(channel_id, [])

    def get_thread(self, channel_id: str, thread_id: str) -> list[ChatMessage]:
        return []

    def list_dms(self) -> list[dict]:
        self.list_dms_calls += 1
        return self._dm_channels


class MockPortWithoutListDms:
    @property
    def platform(self) -> str:
        return "slack_mcp"

    def list_dm_messages(self, since: float) -> list[ChatMessage]:
        return []

    def list_mentions(self, since: float) -> list[ChatMessage]:
        return []

    def list_channel_messages(self, channel_id: str, since: float) -> list[ChatMessage]:
        return []

    def get_thread(self, channel_id: str, thread_id: str) -> list[ChatMessage]:
        return []


def test_list_dms_called_once(tmp_path):
    home = tmp_path / "patina_home"
    port = MockPortWithListDms(
        dm_channels=[{"channel_id": "D001", "last_activity_ts": DM_TS_RECENT}]
    )
    ingest_live(port=port, source="slack_mcp", home=home)
    assert port.list_dms_calls == 1


def test_list_dms_not_called_without_method(tmp_path):
    home = tmp_path / "patina_home"
    port = MockPortWithoutListDms()
    result = ingest_live(port=port, source="slack_mcp", home=home)
    assert result["messages_inserted"] == 0


def test_recent_dm_channel_fetched(tmp_path):
    home = tmp_path / "patina_home"
    port = MockPortWithListDms(
        dm_channels=[{"channel_id": "D_RECENT", "last_activity_ts": DM_TS_RECENT}]
    )
    ingest_live(port=port, source="slack_mcp", home=home)
    fetched_channels = [ch for ch, _ in port.list_channel_messages_calls]
    assert "D_RECENT" in fetched_channels


def test_stale_dm_channel_skipped(tmp_path):
    home = tmp_path / "patina_home"
    port = MockPortWithListDms(
        dm_channels=[{"channel_id": "D_STALE", "last_activity_ts": DM_TS_STALE}]
    )
    ingest_live(port=port, source="slack_mcp", home=home)
    fetched_channels = [ch for ch, _ in port.list_channel_messages_calls]
    assert "D_STALE" not in fetched_channels


def test_mixed_recent_and_stale(tmp_path):
    home = tmp_path / "patina_home"
    port = MockPortWithListDms(
        dm_channels=[
            {"channel_id": "D_RECENT", "last_activity_ts": DM_TS_RECENT},
            {"channel_id": "D_STALE", "last_activity_ts": DM_TS_STALE},
        ]
    )
    ingest_live(port=port, source="slack_mcp", home=home)
    fetched_channels = [ch for ch, _ in port.list_channel_messages_calls]
    assert "D_RECENT" in fetched_channels
    assert "D_STALE" not in fetched_channels


def test_dm_messages_ingested(tmp_path):
    home = tmp_path / "patina_home"
    dm_msg = ChatMessage(
        user_id="U00000ALICE",
        text="Hello from DM backfill",
        timestamp=MSG_TS,
        channel_id="D_FILL01",
        channel_name="dm-alice",
        user_name="Alice Thornberry",
    )
    port = MockPortWithListDms(
        dm_channels=[{"channel_id": "D_FILL01", "last_activity_ts": DM_TS_RECENT}],
        channel_messages={"D_FILL01": [dm_msg]},
    )
    result = ingest_live(port=port, source="slack_mcp", home=home)
    assert result["messages_inserted"] >= 1

    conn = connect(get_db_path(home))
    row = conn.execute(
        "SELECT source, channel_id, text FROM observations WHERE channel_id = 'D_FILL01'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["source"] == "slack_mcp"
    assert "Hello from DM backfill" in row["text"]


def test_dm_obs_id_matches_channel_messages_path(tmp_path):
    msg = ChatMessage(
        user_id="U00000BOB01",
        text="Cross-path dedup check",
        timestamp=MSG_TS,
        channel_id="D_DEDUP1",
        user_name="Bertram Holloway",
    )
    expected_id = _obs_id("slack_mcp", msg.channel_id, msg.thread_id, msg.timestamp)

    home = tmp_path / "patina_home"
    port = MockPortWithListDms(
        dm_channels=[{"channel_id": "D_DEDUP1", "last_activity_ts": DM_TS_RECENT}],
        channel_messages={"D_DEDUP1": [msg]},
    )
    ingest_live(port=port, source="slack_mcp", home=home)

    conn = connect(get_db_path(home))
    row = conn.execute("SELECT id FROM observations WHERE channel_id = 'D_DEDUP1'").fetchone()
    conn.close()
    assert row is not None
    assert row["id"] == expected_id


def test_dedup_on_second_run(tmp_path):
    home = tmp_path / "patina_home"
    dm_msg = ChatMessage(
        user_id="U00000CAROL",
        text="Duplicate test message",
        timestamp=MSG_TS,
        channel_id="D_DUP001",
        user_name="Corinne Vass",
    )
    port = MockPortWithListDms(
        dm_channels=[{"channel_id": "D_DUP001", "last_activity_ts": DM_TS_RECENT}],
        channel_messages={"D_DUP001": [dm_msg]},
    )

    result1 = ingest_live(port=port, source="slack_mcp", home=home)
    assert result1["messages_inserted"] >= 1

    result2 = ingest_live(port=port, source="slack_mcp", home=home)
    dm_count = 1
    assert result2["messages_skipped"] >= dm_count


def test_no_port_method_completes_without_error(tmp_path):
    home = tmp_path / "patina_home"

    class PlainPort:
        @property
        def platform(self):
            return "generic"

    port = PlainPort()
    result = ingest_live(port=port, source="generic", home=home)
    assert result["messages_inserted"] == 0
    assert result["messages_skipped"] == 0


def test_empty_dm_list_no_error(tmp_path):
    home = tmp_path / "patina_home"
    port = MockPortWithListDms(dm_channels=[])
    result = ingest_live(port=port, source="slack_mcp", home=home)
    assert result["messages_inserted"] == 0
