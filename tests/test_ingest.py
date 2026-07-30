from __future__ import annotations

import json
import zipfile

import pytest

from patina.ingest import ingest_all, ingest_from_export, ingest_live
from patina.models import ChatMessage, DmChannel


@pytest.fixture
def export_zip(tmp_path):
    zip_path = tmp_path / "export.zip"
    users = [
        {"id": "U001", "real_name": "Alice", "name": "alice"},
        {"id": "U002", "real_name": "Bob", "name": "bob"},
    ]
    channels = [{"id": "C001", "name": "general"}]
    messages = [
        {"user": "U001", "text": "Hello <@U002>!", "ts": "1700000100.000"},
        {"user": "U002", "text": "Hey Alice!", "ts": "1700000200.000"},
        {"user": "U001", "text": "Check <#C001|general>", "ts": "1700000300.000"},
    ]

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("users.json", json.dumps(users))
        zf.writestr("channels.json", json.dumps(channels))
        zf.writestr("general/2023-11-15.json", json.dumps(messages))

    return zip_path


def test_creates_observations(export_zip, tmp_path):
    home = tmp_path / "patina_home"
    result = ingest_from_export(export_zip, home=home)
    assert result["messages_inserted"] == 3
    assert result["total_observations"] == 3


def test_creates_entities(export_zip, tmp_path):
    home = tmp_path / "patina_home"
    result = ingest_from_export(export_zip, home=home)
    assert result["entities_created"] >= 2
    assert result["total_entities"] >= 2


def test_idempotent(export_zip, tmp_path):
    home = tmp_path / "patina_home"
    result1 = ingest_from_export(export_zip, home=home)
    result2 = ingest_from_export(export_zip, home=home)
    assert result2["messages_inserted"] == 0
    assert result2["messages_skipped"] == 3
    assert result2["total_observations"] == result1["total_observations"]


def test_links_sender_entity(export_zip, tmp_path):
    home = tmp_path / "patina_home"
    ingest_from_export(export_zip, home=home)

    from patina.store import connect, get_db_path

    conn = connect(get_db_path(home))
    rows = conn.execute(
        "SELECT sender_entity_id FROM observations WHERE sender_entity_id IS NOT NULL"
    ).fetchall()
    assert len(rows) == 3
    conn.close()


def test_returns_correct_counts(export_zip, tmp_path):
    home = tmp_path / "patina_home"
    result = ingest_from_export(export_zip, home=home)
    assert "messages_inserted" in result
    assert "messages_skipped" in result
    assert "entities_created" in result
    assert "total_observations" in result
    assert "total_entities" in result


_FIXED_TS = 1700000100.0


class MockChatPort:
    @property
    def platform(self) -> str:
        return "mock"

    def list_dm_messages(self, since: float) -> list[ChatMessage]:
        return [
            ChatMessage(
                user_id="U001",
                text="Hello from DM",
                timestamp=_FIXED_TS,
                channel_id="D001",
                user_name="Alice",
            ),
        ]

    def list_mentions(self, since: float) -> list[ChatMessage]:
        return [
            ChatMessage(
                user_id="U002",
                text="Hey <@U001>",
                timestamp=_FIXED_TS + 100,
                channel_id="C001",
                user_name="Bob",
            ),
        ]

    def list_channel_messages(self, channel_id, since):
        return []

    def get_thread(self, channel_id, thread_id):
        return []


def test_ingest_live_with_mock_port(tmp_path):
    home = tmp_path / "live_home"
    port = MockChatPort()
    result = ingest_live(port=port, source="mock", home=home)
    assert result["messages_inserted"] == 2
    assert result["entities_created"] >= 2


def test_ingest_live_dedup(tmp_path):
    home = tmp_path / "live_home"
    port = MockChatPort()
    ingest_live(port=port, source="mock", home=home)
    result2 = ingest_live(port=port, source="mock", home=home)
    assert result2["messages_skipped"] == 2


class MockChatPortWithOwner:
    """Chat port that simulates both owner and non-owner messages in a DM."""

    @property
    def platform(self) -> str:
        return "mock"

    def list_dm_messages(self, since: float) -> list[ChatMessage]:
        return [
            ChatMessage(
                user_id="U001",
                text="Message from other party",
                timestamp=_FIXED_TS,
                channel_id="D001",
                user_name="Alice",
            ),
        ]

    def list_mentions(self, since: float) -> list[ChatMessage]:
        return []

    def list_sent_messages(self, since: float) -> list[ChatMessage]:
        return [
            ChatMessage(
                user_id="U_OWNER",
                text="Reply from owner",
                timestamp=_FIXED_TS + 50,
                channel_id="D001",
                user_name="Jasper",
            ),
            ChatMessage(
                user_id="U_OWNER",
                text="Follow-up from owner",
                timestamp=_FIXED_TS + 80,
                channel_id="D001",
                user_name="Jasper",
            ),
        ]

    def list_channel_messages(self, channel_id, since):
        return []

    def get_thread(self, channel_id, thread_id):
        return []


def test_ingest_live_owner_messages_persist(tmp_path):
    home = tmp_path / "live_home"
    port = MockChatPortWithOwner()
    result = ingest_live(port=port, source="mock", home=home)
    assert result["messages_inserted"] == 3

    from patina.store import connect, get_db_path

    conn = connect(get_db_path(home))
    rows = conn.execute(
        "SELECT text, sender_entity_id FROM observations ORDER BY timestamp"
    ).fetchall()
    assert len(rows) == 3
    assert rows[0]["text"] == "Message from other party"
    assert rows[1]["text"] == "Reply from owner"
    assert rows[2]["text"] == "Follow-up from owner"
    conn.close()


def test_ingest_live_owner_messages_correct_attribution(tmp_path):
    home = tmp_path / "live_home"
    port = MockChatPortWithOwner()
    ingest_live(port=port, source="mock", home=home)

    from patina.store import connect, get_db_path

    conn = connect(get_db_path(home))
    owner_obs = conn.execute(
        "SELECT o.sender_entity_id, e.name FROM observations o "
        "JOIN entities e ON o.sender_entity_id = e.id "
        "WHERE o.text = 'Reply from owner'"
    ).fetchone()
    assert owner_obs is not None
    assert owner_obs["name"] == "Jasper"

    other_obs = conn.execute(
        "SELECT o.sender_entity_id, e.name FROM observations o "
        "JOIN entities e ON o.sender_entity_id = e.id "
        "WHERE o.text = 'Message from other party'"
    ).fetchone()
    assert other_obs is not None
    assert other_obs["name"] == "Alice"
    assert owner_obs["sender_entity_id"] != other_obs["sender_entity_id"]
    conn.close()


def test_ingest_live_cross_source_dedup(tmp_path):
    """Owner message already present from export backfill is not duplicated."""
    home = tmp_path / "live_home"

    from patina.ingest import _ingest_messages
    from patina.store import connect, get_db_path, init_db, run_pending_migrations

    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    run_pending_migrations(conn)

    export_msgs = [
        ChatMessage(
            user_id="U_OWNER",
            text="Reply from owner",
            timestamp=_FIXED_TS + 50,
            channel_id="D001",
            user_name="Jasper",
        ),
    ]
    inserted, _, _ = _ingest_messages(conn, export_msgs, "slack_export")
    assert inserted == 1
    conn.close()

    port = MockChatPortWithOwner()
    result = ingest_live(port=port, source="mock", home=home)

    assert result["messages_inserted"] == 2
    assert result["messages_skipped"] == 1

    conn = connect(db_path)
    total = conn.execute("SELECT COUNT(*) as cnt FROM observations").fetchone()
    assert total["cnt"] == 3
    conn.close()


def test_ingest_live_owner_messages_searchable(tmp_path):
    """Owner messages are findable via direct query after live ingest."""
    home = tmp_path / "live_home"
    port = MockChatPortWithOwner()
    ingest_live(port=port, source="mock", home=home)

    from patina.store import connect, get_db_path

    conn = connect(get_db_path(home))
    rows = conn.execute("SELECT * FROM observations WHERE text LIKE '%owner%'").fetchall()
    assert len(rows) == 2
    texts = {r["text"] for r in rows}
    assert "Reply from owner" in texts
    assert "Follow-up from owner" in texts
    conn.close()


class MockChatPortWithDiscovery:
    """Chat port that returns configurable DM channels for auto-watch discovery."""

    def __init__(self, dm_channels: list | None = None):
        self._dm_channels = dm_channels or []

    @property
    def platform(self) -> str:
        return "mock"

    def list_dm_messages(self, since: float) -> list[ChatMessage]:
        return []

    def list_mentions(self, since: float) -> list[ChatMessage]:
        return []

    def list_channel_messages(self, channel_id, since):
        return []

    def get_thread(self, channel_id, thread_id):
        return []

    def list_dms(self, include_dormant=False) -> list:
        return self._dm_channels


def _setup_owner(home):
    """Write a minimal config with owner user_ids."""
    import yaml

    home.mkdir(parents=True, exist_ok=True)
    config_path = home / "config.yaml"
    config_path.write_text(yaml.dump({"owner": {"user_ids": ["U_OWNER"]}}))


def test_zero_streak_increments_on_empty_discovery(tmp_path):
    home = tmp_path / "live_home"
    _setup_owner(home)
    port = MockChatPortWithDiscovery(dm_channels=[])

    r1 = ingest_live(port=port, source="mock", home=home)
    assert r1["zero_streak"] == 1
    assert r1["channels_seen"] == 0

    r2 = ingest_live(port=port, source="mock", home=home)
    assert r2["zero_streak"] == 2

    r3 = ingest_live(port=port, source="mock", home=home)
    assert r3["zero_streak"] == 3


def test_zero_streak_resets_on_nonempty_discovery(tmp_path):
    home = tmp_path / "live_home"
    _setup_owner(home)

    empty_port = MockChatPortWithDiscovery(dm_channels=[])
    ingest_live(port=empty_port, source="mock", home=home)
    ingest_live(port=empty_port, source="mock", home=home)

    port_with_channels = MockChatPortWithDiscovery(
        dm_channels=[
            DmChannel(channel_id="C100", is_group=True),
            DmChannel(channel_id="C101", is_group=True),
        ]
    )
    result = ingest_live(port=port_with_channels, source="mock", home=home)
    assert result["zero_streak"] == 0
    assert result["channels_seen"] == 2
    assert result["newly_watched"] == 2


def test_zero_streak_persisted_in_store(tmp_path):
    home = tmp_path / "live_home"
    _setup_owner(home)

    from patina.store import connect, get_db_path, kv_get

    empty_port = MockChatPortWithDiscovery(dm_channels=[])
    ingest_live(port=empty_port, source="mock", home=home)
    ingest_live(port=empty_port, source="mock", home=home)

    conn = connect(get_db_path(home))
    assert kv_get(conn, "discovery_zero_streak") == "2"
    conn.close()

    port_with_channels = MockChatPortWithDiscovery(
        dm_channels=[DmChannel(channel_id="C200", is_group=True)]
    )
    ingest_live(port=port_with_channels, source="mock", home=home)

    conn = connect(get_db_path(home))
    assert kv_get(conn, "discovery_zero_streak") == "0"
    conn.close()


def test_ingest_live_return_dict_has_new_keys(tmp_path):
    home = tmp_path / "live_home"
    port = MockChatPort()
    result = ingest_live(port=port, source="mock", home=home)
    assert "channels_seen" in result
    assert "newly_watched" in result
    assert "zero_streak" in result


def test_ingest_all_no_adapters(tmp_path):
    result = ingest_all(home=tmp_path)
    assert result["adapters_run"] == 0
    assert result["messages_inserted"] == 0
