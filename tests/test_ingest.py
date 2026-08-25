from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from patina.ingest import _source_family, ingest_all, ingest_from_export, ingest_live
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
    result = ingest_live(port=port, source="slack_live", home=home)

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


def test_dedup_when_channel_id_differs(tmp_path):
    """Same Slack message ingested with different channel_ids produces one row."""
    home = tmp_path / "dedup_home"

    from patina.ingest import _ingest_messages
    from patina.store import connect, get_db_path, init_db, run_pending_migrations

    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    run_pending_migrations(conn)

    msg_empty_channel = [
        ChatMessage(
            user_id="U001",
            text="The quick brown fox",
            timestamp=1700000100.0,
            channel_id="",
            user_name="Fern",
        ),
    ]
    inserted1, _, _ = _ingest_messages(conn, msg_empty_channel, "slack_mcp")
    assert inserted1 == 1

    msg_populated_channel = [
        ChatMessage(
            user_id="U001",
            text="The quick brown fox",
            timestamp=1700000100.0,
            channel_id="D00000DM001",
            user_name="Fern",
        ),
    ]
    inserted2, skipped2, _ = _ingest_messages(conn, msg_populated_channel, "slack_mcp")
    assert inserted2 == 0
    assert skipped2 == 1

    total = conn.execute("SELECT COUNT(*) as cnt FROM observations").fetchone()
    assert total["cnt"] == 1
    conn.close()


def test_dedup_across_slack_sources(tmp_path):
    """Same message from slack_export and slack_mcp produces one row."""
    home = tmp_path / "dedup_home"

    from patina.ingest import _ingest_messages
    from patina.store import connect, get_db_path, init_db, run_pending_migrations

    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    run_pending_migrations(conn)

    msg = [
        ChatMessage(
            user_id="U001",
            text="The quick brown fox",
            timestamp=1700000100.0,
            channel_id="C001",
            user_name="Fern",
        ),
    ]
    inserted1, _, _ = _ingest_messages(conn, msg, "slack_export")
    assert inserted1 == 1

    inserted2, skipped2, _ = _ingest_messages(conn, msg, "slack_mcp")
    assert inserted2 == 0
    assert skipped2 == 1

    total = conn.execute("SELECT COUNT(*) as cnt FROM observations").fetchone()
    assert total["cnt"] == 1
    conn.close()


def test_channel_id_enrichment_on_conflict(tmp_path):
    """Second ingest enriches an empty channel_id via ON CONFLICT DO UPDATE."""
    home = tmp_path / "enrich_home"

    from patina.ingest import _ingest_messages
    from patina.store import connect, get_db_path, init_db, run_pending_migrations

    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    run_pending_migrations(conn)

    msg_empty = [
        ChatMessage(
            user_id="U001",
            text="The quick brown fox",
            timestamp=1700000100.0,
            channel_id="",
            user_name="Fern",
        ),
    ]
    _ingest_messages(conn, msg_empty, "slack_mcp")

    row = conn.execute("SELECT channel_id FROM observations").fetchone()
    assert row["channel_id"] == ""

    msg_enriched = [
        ChatMessage(
            user_id="U001",
            text="The quick brown fox",
            timestamp=1700000100.0,
            channel_id="D00000DM001",
            user_name="Fern",
        ),
    ]
    _ingest_messages(conn, msg_enriched, "slack_mcp")

    row = conn.execute("SELECT channel_id FROM observations").fetchone()
    assert row["channel_id"] == "D00000DM001"

    total = conn.execute("SELECT COUNT(*) as cnt FROM observations").fetchone()
    assert total["cnt"] == 1
    conn.close()


def test_channel_id_not_overwritten_when_already_set(tmp_path):
    """Enrichment does not overwrite an existing non-empty channel_id."""
    home = tmp_path / "enrich_home"

    from patina.ingest import _ingest_messages
    from patina.store import connect, get_db_path, init_db, run_pending_migrations

    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    run_pending_migrations(conn)

    msg_first = [
        ChatMessage(
            user_id="U001",
            text="The quick brown fox",
            timestamp=1700000100.0,
            channel_id="D_ORIGINAL",
            user_name="Fern",
        ),
    ]
    _ingest_messages(conn, msg_first, "slack_mcp")

    msg_second = [
        ChatMessage(
            user_id="U001",
            text="The quick brown fox",
            timestamp=1700000100.0,
            channel_id="D_DIFFERENT",
            user_name="Fern",
        ),
    ]
    _ingest_messages(conn, msg_second, "slack_mcp")

    row = conn.execute("SELECT channel_id FROM observations").fetchone()
    assert row["channel_id"] == "D_ORIGINAL"
    conn.close()


class TestSourceFamily:
    def test_slack_variants(self):
        assert _source_family("slack") == "slack"
        assert _source_family("slack_mcp") == "slack"
        assert _source_family("slack_export") == "slack"
        assert _source_family("slack_live") == "slack"
        assert _source_family("slack_mention") == "slack"
        assert _source_family("slack_watched") == "slack"

    def test_outlook_variants(self):
        assert _source_family("outlook_mcp_email") == "outlook"
        assert _source_family("outlook_mcp_calendar") == "outlook"

    def test_other_sources_unchanged(self):
        assert _source_family("imap") == "imap"
        assert _source_family("mock") == "mock"


def test_obs_id_outlook_sources_collapse(tmp_path):
    """outlook_mcp_email and outlook_mcp_calendar produce the same obs_id."""
    from patina.ingest import _obs_id

    id_email = _obs_id("outlook_mcp_email", "calendar:ev1", None, 1700000100.0)
    id_cal = _obs_id("outlook_mcp_calendar", "calendar:ev1", None, 1700000100.0)
    assert id_email == id_cal


def test_obs_id_slack_sources_collapse():
    """All slack-family sources with the same ts produce the same obs_id."""
    from patina.ingest import _obs_id

    ids = {
        _obs_id(src, "C001", None, 1700000100.0)
        for src in ("slack", "slack_mcp", "slack_export", "slack_live")
    }
    assert len(ids) == 1


def test_obs_id_null_channel_id_uses_empty_string():
    """_obs_id with channel_id=None produces '' in the key, not 'None'."""
    from patina.ingest import _obs_id

    id_none = _obs_id("outlook_mcp_email", None, None, 1700000100.0)
    id_empty = _obs_id("outlook_mcp_email", "", None, 1700000100.0)
    assert id_none == id_empty


def test_obs_id_populated_channel_id_unchanged():
    """_obs_id with a non-None channel_id is unaffected by the None guard."""
    from patina.ingest import _obs_id

    id_val = _obs_id("outlook_mcp_email", "inbox:123", None, 1700000100.0)
    id_none = _obs_id("outlook_mcp_email", None, None, 1700000100.0)
    assert id_val != id_none


def _dedup_v2_setup(home):
    """Shared setup: init db, run prior migrations, skip v2 so we can insert test data."""
    from patina.store import connect, get_db_path, init_db, run_pending_migrations

    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO migrations (name, applied_at)"
        " VALUES ('deduplicate_observations_v2', datetime('now'))"
    )
    conn.commit()
    run_pending_migrations(conn)
    return conn


def _insert_obs_raw(conn, obs):
    """Insert observation with FK checks off (test helper)."""
    from patina.graph import insert_observation

    conn.execute("PRAGMA foreign_keys=OFF")
    insert_observation(conn, obs)
    conn.execute("PRAGMA foreign_keys=ON")


def _run_dedup_v2(conn):
    """Remove the v2 migration marker and re-run migrations."""
    from patina.store import run_pending_migrations

    conn.execute("DELETE FROM migrations WHERE name = 'deduplicate_observations_v2'")
    conn.commit()
    run_pending_migrations(conn)


def test_dedup_v2_merges_cross_family_duplicates(tmp_path):
    """deduplicate_observations_v2 merges rows from different sources in the same family."""
    home = tmp_path / "dedup_v2"
    conn = _dedup_v2_setup(home)

    from patina.ingest import _obs_id
    from patina.models import Observation

    obs1_id = _obs_id("slack_export", "C001", None, 1700000100.0)
    _insert_obs_raw(
        conn,
        Observation(
            id=obs1_id,
            source="slack_export",
            channel_id="C001",
            thread_id=None,
            timestamp=1700000100.0,
            sender_entity_id="e1",
            text="The quick brown fox",
            metadata={"channel_name": "general"},
        ),
    )

    obs2_id = hashlib.sha256(b"force_different_id").hexdigest()[:16]
    _insert_obs_raw(
        conn,
        Observation(
            id=obs2_id,
            source="slack_mcp",
            channel_id="C001",
            thread_id=None,
            timestamp=1700000100.0,
            sender_entity_id="e1",
            text="The quick brown fox",
            metadata={"reactions": [{"name": "thumbsup"}]},
        ),
    )

    total = conn.execute("SELECT COUNT(*) as cnt FROM observations").fetchone()
    assert total["cnt"] == 2

    _run_dedup_v2(conn)

    total = conn.execute("SELECT COUNT(*) as cnt FROM observations").fetchone()
    assert total["cnt"] == 1

    survivor = conn.execute("SELECT * FROM observations").fetchone()
    assert survivor["source"] == "slack_mcp"
    conn.close()


def test_dedup_v2_folds_metadata(tmp_path):
    """Victim metadata keys absent from survivor are folded in."""
    home = tmp_path / "dedup_v2_meta"
    conn = _dedup_v2_setup(home)

    from patina.models import Observation

    survivor_id = hashlib.sha256(b"survivor_row").hexdigest()[:16]
    victim_id = hashlib.sha256(b"victim_row").hexdigest()[:16]

    _insert_obs_raw(
        conn,
        Observation(
            id=survivor_id,
            source="slack_mcp",
            channel_id="C001",
            thread_id=None,
            timestamp=1700000100.0,
            sender_entity_id="e1",
            text="Hello world",
            metadata={"channel_name": "general"},
        ),
    )
    _insert_obs_raw(
        conn,
        Observation(
            id=victim_id,
            source="slack_export",
            channel_id="C001",
            thread_id=None,
            timestamp=1700000100.0,
            sender_entity_id="e1",
            text="Hello world",
            metadata={"is_mention": True, "extra_flag": "yes"},
        ),
    )

    _run_dedup_v2(conn)

    row = conn.execute("SELECT metadata FROM observations").fetchone()
    meta = json.loads(row["metadata"])
    assert meta["channel_name"] == "general"
    assert meta["is_mention"] is True
    assert meta["extra_flag"] == "yes"
    conn.close()


def test_dedup_v2_repoints_foreign_keys(tmp_path):
    """Foreign keys in decisions and action_queue are repointed to the survivor."""
    home = tmp_path / "dedup_v2_fk"
    conn = _dedup_v2_setup(home)

    from patina.models import Observation

    survivor_id = hashlib.sha256(b"survivor_fk").hexdigest()[:16]
    victim_id = hashlib.sha256(b"victim_fk").hexdigest()[:16]

    _insert_obs_raw(
        conn,
        Observation(
            id=survivor_id,
            source="slack_mcp",
            channel_id="C001",
            thread_id=None,
            timestamp=1700000100.0,
            sender_entity_id="e1",
            text="FK test",
            metadata={},
        ),
    )
    _insert_obs_raw(
        conn,
        Observation(
            id=victim_id,
            source="slack_export",
            channel_id="C001",
            thread_id=None,
            timestamp=1700000100.0,
            sender_entity_id="e1",
            text="FK test",
            metadata={},
        ),
    )

    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO decisions (id, observation_id, action, acted_at)"
        " VALUES (?, ?, ?, datetime('now'))",
        ("d1", victim_id, "reply"),
    )
    conn.execute(
        "INSERT INTO action_queue"
        " (id, action_type, target_observation_id,"
        " confidence, autonomy_level, created_at)"
        " VALUES (?, ?, ?, ?, ?, datetime('now'))",
        ("a1", "draft_reply", victim_id, 0.9, 1),
    )
    conn.execute(
        "INSERT INTO claims"
        " (id, subject_id, predicate, object,"
        " first_asserted, last_confirmed, source_ids)"
        " VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), ?)",
        ("cl1", "e1", "likes", "coffee", json.dumps([victim_id, "other_id"])),
    )
    conn.execute(
        "INSERT INTO relationships"
        " (id, subject_id, predicate, object_id,"
        " first_seen, last_confirmed, source_ids)"
        " VALUES (?, ?, ?, ?, datetime('now'), datetime('now'), ?)",
        ("r1", "e1", "knows", "e2", json.dumps([victim_id])),
    )
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()

    _run_dedup_v2(conn)

    dec = conn.execute("SELECT observation_id FROM decisions WHERE id = 'd1'").fetchone()
    assert dec["observation_id"] == survivor_id

    aq = conn.execute("SELECT target_observation_id FROM action_queue WHERE id = 'a1'").fetchone()
    assert aq["target_observation_id"] == survivor_id

    cl = conn.execute("SELECT source_ids FROM claims WHERE id = 'cl1'").fetchone()
    assert json.loads(cl["source_ids"]) == [survivor_id, "other_id"]

    rel = conn.execute("SELECT source_ids FROM relationships WHERE id = 'r1'").fetchone()
    assert json.loads(rel["source_ids"]) == [survivor_id]

    conn.close()


def test_dedup_v2_rebuilds_fts(tmp_path):
    """FTS index is rebuilt after dedup and search still works."""
    home = tmp_path / "dedup_v2_fts"
    conn = _dedup_v2_setup(home)

    from patina.models import Observation

    survivor_id = hashlib.sha256(b"survivor_fts").hexdigest()[:16]
    victim_id = hashlib.sha256(b"victim_fts").hexdigest()[:16]

    _insert_obs_raw(
        conn,
        Observation(
            id=survivor_id,
            source="slack_mcp",
            channel_id="C001",
            thread_id=None,
            timestamp=1700000100.0,
            sender_entity_id="e1",
            text="Searchable content here",
            metadata={},
        ),
    )
    _insert_obs_raw(
        conn,
        Observation(
            id=victim_id,
            source="slack_export",
            channel_id="C001",
            thread_id=None,
            timestamp=1700000100.0,
            sender_entity_id="e1",
            text="Searchable content here",
            metadata={},
        ),
    )

    _run_dedup_v2(conn)

    fts_rows = conn.execute(
        "SELECT * FROM observations_fts WHERE observations_fts MATCH 'searchable'"
    ).fetchall()
    assert len(fts_rows) == 1
    conn.close()


def test_dedup_v2_idempotent(tmp_path):
    """Running deduplicate_observations_v2 twice produces the same result."""
    home = tmp_path / "dedup_v2_idem"
    conn = _dedup_v2_setup(home)

    from patina.models import Observation

    id1 = hashlib.sha256(b"idem_survivor").hexdigest()[:16]
    id2 = hashlib.sha256(b"idem_victim").hexdigest()[:16]

    _insert_obs_raw(
        conn,
        Observation(
            id=id1,
            source="slack_mcp",
            channel_id="C001",
            thread_id=None,
            timestamp=1700000100.0,
            sender_entity_id="e1",
            text="Idempotent test",
            metadata={"a": 1},
        ),
    )
    _insert_obs_raw(
        conn,
        Observation(
            id=id2,
            source="slack_export",
            channel_id="C001",
            thread_id=None,
            timestamp=1700000100.0,
            sender_entity_id="e1",
            text="Idempotent test",
            metadata={"b": 2},
        ),
    )

    _run_dedup_v2(conn)

    count_after_first = conn.execute("SELECT COUNT(*) as cnt FROM observations").fetchone()["cnt"]
    assert count_after_first == 1

    meta_after_first = json.loads(
        conn.execute("SELECT metadata FROM observations").fetchone()["metadata"]
    )

    _run_dedup_v2(conn)

    count_after_second = conn.execute("SELECT COUNT(*) as cnt FROM observations").fetchone()["cnt"]
    assert count_after_second == count_after_first

    meta_after_second = json.loads(
        conn.execute("SELECT metadata FROM observations").fetchone()["metadata"]
    )
    assert meta_after_second == meta_after_first
    conn.close()


def test_dedup_v2_survivor_preference_outlook(tmp_path):
    """outlook_mcp_calendar is preferred over outlook_mcp_email."""
    home = tmp_path / "dedup_v2_outlook"
    conn = _dedup_v2_setup(home)

    from patina.models import Observation

    id_email = hashlib.sha256(b"outlook_email").hexdigest()[:16]
    id_cal = hashlib.sha256(b"outlook_cal").hexdigest()[:16]

    _insert_obs_raw(
        conn,
        Observation(
            id=id_email,
            source="outlook_mcp_email",
            channel_id="email:conv1",
            thread_id=None,
            timestamp=1700000100.0,
            sender_entity_id="e1",
            text="[Meeting: Standup] Organizer: Fern, Attendees: Gale",
            metadata={"subject": "Standup"},
        ),
    )
    _insert_obs_raw(
        conn,
        Observation(
            id=id_cal,
            source="outlook_mcp_calendar",
            channel_id="email:conv1",
            thread_id=None,
            timestamp=1700000100.0,
            sender_entity_id="e1",
            text="[Meeting: Standup] Organizer: Fern, Attendees: Gale",
            metadata={"attendees": ["Fern", "Gale"], "duration_minutes": 30},
        ),
    )

    _run_dedup_v2(conn)

    total = conn.execute("SELECT COUNT(*) as cnt FROM observations").fetchone()
    assert total["cnt"] == 1

    survivor = conn.execute("SELECT * FROM observations").fetchone()
    assert survivor["source"] == "outlook_mcp_calendar"

    meta = json.loads(survivor["metadata"])
    assert meta["attendees"] == ["Fern", "Gale"]
    assert meta["duration_minutes"] == 30
    assert meta["subject"] == "Standup"
    conn.close()


def _setup_draft_reply(home, draft_text="Sure, I will review it today!"):
    from patina.autonomy.actions import propose_action
    from patina.extraction import extract_sender_entity
    from patina.graph import insert_observation, upsert_entity
    from patina.models import Observation
    from patina.owner import mark_entity_as_owner
    from patina.store import connect, get_db_path, init_db, run_pending_migrations

    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    run_pending_migrations(conn)

    recipient = extract_sender_entity("U001", "Wren")
    upsert_entity(conn, recipient)

    obs = Observation(
        id="obs_from_recipient",
        source="mock",
        channel_id="D001",
        thread_id=None,
        timestamp=_FIXED_TS,
        sender_entity_id=recipient.id,
        text="Hey, can you review this?",
        metadata={},
    )
    insert_observation(conn, obs)

    owner = extract_sender_entity("U_OWNER", "Jasper")
    upsert_entity(conn, owner)
    mark_entity_as_owner(conn, owner.id)

    propose_action(
        conn,
        action_type="draft_reply",
        target_observation_id="obs_from_recipient",
        target_entity_id=recipient.id,
        payload={"context": "review request", "draft_text": draft_text},
        confidence=0.5,
        autonomy_level=1,
    )

    conn.close()
    return db_path


class MockOwnerReplyPort:
    def __init__(self, reply_text, channel_id="D001"):
        self._reply_text = reply_text
        self._channel_id = channel_id

    @property
    def platform(self):
        return "mock"

    def list_dm_messages(self, since):
        return []

    def list_mentions(self, since):
        return []

    def list_sent_messages(self, since):
        return [
            ChatMessage(
                user_id="U_OWNER",
                text=self._reply_text,
                timestamp=_FIXED_TS + 100,
                channel_id=self._channel_id,
                user_name="Jasper",
            ),
        ]

    def list_channel_messages(self, channel_id, since):
        return []

    def get_thread(self, channel_id, thread_id):
        return []


def test_auto_resolve_draft_reply_acted(tmp_path):
    home = tmp_path / "resolve_home"
    db_path = _setup_draft_reply(home)

    port = MockOwnerReplyPort("Sure, I will review it today!")
    ingest_live(port=port, source="mock", home=home)

    from patina.store import connect

    conn = connect(db_path)
    action = conn.execute(
        "SELECT status FROM action_queue WHERE action_type = 'draft_reply'"
    ).fetchone()
    assert action["status"] == "approved"

    decision = conn.execute(
        "SELECT action FROM decisions WHERE observation_id = 'obs_from_recipient'"
    ).fetchone()
    assert decision is not None
    assert decision["action"] == "acted"
    conn.close()


def test_auto_resolve_draft_reply_edited(tmp_path):
    home = tmp_path / "resolve_home"
    db_path = _setup_draft_reply(home)

    port = MockOwnerReplyPort("I am too busy this week, let us discuss next Monday instead")
    ingest_live(port=port, source="mock", home=home)

    from patina.store import connect

    conn = connect(db_path)
    action = conn.execute(
        "SELECT status FROM action_queue WHERE action_type = 'draft_reply'"
    ).fetchone()
    assert action["status"] == "edited"

    decision = conn.execute(
        "SELECT action FROM decisions WHERE observation_id = 'obs_from_recipient'"
    ).fetchone()
    assert decision is not None
    assert decision["action"] == "edited"
    conn.close()


def test_auto_resolve_no_matching_action(tmp_path):
    """Owner sends message to a different channel — existing proposed action unchanged."""
    home = tmp_path / "resolve_home"
    db_path = _setup_draft_reply(home)

    port = MockOwnerReplyPort("Random message", channel_id="D999")
    ingest_live(port=port, source="mock", home=home)

    from patina.store import connect

    conn = connect(db_path)
    action = conn.execute(
        "SELECT status FROM action_queue WHERE action_type = 'draft_reply'"
    ).fetchone()
    assert action["status"] == "proposed"

    decisions_count = conn.execute("SELECT COUNT(*) as cnt FROM decisions").fetchone()
    assert decisions_count["cnt"] == 0
    conn.close()


def test_auto_resolve_false_positive_guard(tmp_path):
    """Owner sends message to channel with no proposed action — no decision created."""
    home = tmp_path / "resolve_home"

    from patina.extraction import extract_sender_entity
    from patina.graph import upsert_entity
    from patina.owner import mark_entity_as_owner
    from patina.store import connect, get_db_path, init_db, run_pending_migrations

    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    run_pending_migrations(conn)

    owner = extract_sender_entity("U_OWNER", "Jasper")
    upsert_entity(conn, owner)
    mark_entity_as_owner(conn, owner.id)
    conn.close()

    port = MockOwnerReplyPort("Hello world")
    ingest_live(port=port, source="mock", home=home)

    conn = connect(db_path)
    decisions_count = conn.execute("SELECT COUNT(*) as cnt FROM decisions").fetchone()
    assert decisions_count["cnt"] == 0
    conn.close()


def test_auto_resolve_act_on_rate(tmp_path):
    """After acted resolution, act_on_rate reflects the resolved decision."""
    home = tmp_path / "resolve_home"
    db_path = _setup_draft_reply(home)

    port = MockOwnerReplyPort("Sure, I will review it today!")
    ingest_live(port=port, source="mock", home=home)

    from patina.decisions import get_act_on_rate
    from patina.store import connect

    conn = connect(db_path)
    rate = get_act_on_rate(conn)
    assert rate == 1.0
    conn.close()
