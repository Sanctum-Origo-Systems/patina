import json

import pytest

from patina.graph import insert_observation
from patina.ingest import _obs_id
from patina.models import Observation
from patina.store import connect, init_db, run_pending_migrations


def _insert_obs(
    conn,
    obs_id,
    source="slack",
    channel_id=None,
    thread_id=None,
    timestamp=1.0,
    sender_entity_id=None,
    text="hello",
):
    conn.execute(
        """INSERT INTO observations
           (id, source, channel_id, thread_id, timestamp,
            sender_entity_id, text, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (obs_id, source, channel_id, thread_id, timestamp, sender_entity_id, text),
    )


def _insert_entity(conn, entity_id, name="Zara"):
    conn.execute(
        "INSERT INTO entities (id, type, name, first_seen, last_seen) "
        "VALUES (?, 'person', ?, datetime('now'), datetime('now'))",
        (entity_id, name),
    )


def test_dedup_removes_duplicate_observations(db_path):
    conn = connect(db_path)
    _insert_obs(conn, "obs-a", channel_id="", text="test message")
    _insert_obs(conn, "obs-b", channel_id="C123", text="test message")
    conn.commit()

    run_pending_migrations(conn)

    count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert count == 1
    row = conn.execute("SELECT id, channel_id FROM observations").fetchone()
    assert row["id"] == _obs_id("slack", "", None, 1.0)
    assert row["channel_id"] == "C123"
    conn.close()


def test_dedup_prefers_most_complete_metadata(db_path):
    conn = connect(db_path)
    _insert_obs(conn, "obs-1", channel_id="", thread_id="", text="test")
    _insert_obs(conn, "obs-2", channel_id="C1", thread_id="", text="test")
    _insert_obs(conn, "obs-3", channel_id="C1", thread_id="T1", text="test")
    conn.commit()

    run_pending_migrations(conn)

    count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert count == 1
    row = conn.execute("SELECT id, channel_id, thread_id FROM observations").fetchone()
    assert row["id"] == _obs_id("slack", "", None, 1.0)
    assert row["channel_id"] == "C1"
    assert row["thread_id"] == "T1"
    conn.close()


def test_dedup_repoints_decisions(db_path):
    conn = connect(db_path)
    _insert_obs(conn, "obs-victim", channel_id="", text="test")
    _insert_obs(conn, "obs-survivor", channel_id="C1", text="test")
    conn.execute(
        "INSERT INTO decisions (id, observation_id, action, acted_at) "
        "VALUES ('dec1', 'obs-victim', 'reply', datetime('now'))"
    )
    conn.commit()

    run_pending_migrations(conn)

    expected = _obs_id("slack", "", None, 1.0)
    row = conn.execute("SELECT observation_id FROM decisions WHERE id = 'dec1'").fetchone()
    assert row["observation_id"] == expected
    conn.close()


def test_dedup_repoints_action_queue(db_path):
    conn = connect(db_path)
    _insert_obs(conn, "obs-victim", channel_id="", text="test")
    _insert_obs(conn, "obs-survivor", channel_id="C1", text="test")
    conn.execute(
        """INSERT INTO action_queue
           (id, action_type, target_observation_id, confidence,
            status, autonomy_level, created_at)
           VALUES ('act1', 'reply', 'obs-victim', 0.9,
                   'proposed', 1, datetime('now'))"""
    )
    conn.commit()

    run_pending_migrations(conn)

    expected = _obs_id("slack", "", None, 1.0)
    row = conn.execute(
        "SELECT target_observation_id FROM action_queue WHERE id = 'act1'"
    ).fetchone()
    assert row["target_observation_id"] == expected
    conn.close()


def test_dedup_repoints_claims_source_ids(db_path):
    conn = connect(db_path)
    _insert_entity(conn, "e1")
    _insert_obs(conn, "obs-victim", channel_id="", text="test")
    _insert_obs(conn, "obs-survivor", channel_id="C1", text="test")
    conn.execute(
        "INSERT INTO claims "
        "(id, subject_id, predicate, object, first_asserted, last_confirmed, source_ids) "
        "VALUES ('c1', 'e1', 'likes', 'tea', datetime('now'), datetime('now'), ?)",
        (json.dumps(["obs-victim", "other-id"]),),
    )
    conn.commit()

    run_pending_migrations(conn)

    expected = _obs_id("slack", "", None, 1.0)
    row = conn.execute("SELECT source_ids FROM claims WHERE id = 'c1'").fetchone()
    sids = json.loads(row["source_ids"])
    assert "obs-victim" not in sids
    assert expected in sids
    assert "other-id" in sids
    conn.close()


def test_dedup_repoints_relationships_source_ids(db_path):
    conn = connect(db_path)
    _insert_entity(conn, "e1")
    _insert_entity(conn, "e2", name="Kai")
    _insert_obs(conn, "obs-victim", channel_id="", text="test")
    _insert_obs(conn, "obs-survivor", channel_id="C1", text="test")
    conn.execute(
        "INSERT INTO relationships "
        "(id, subject_id, predicate, object_id, first_seen, last_confirmed, source_ids) "
        "VALUES ('r1', 'e1', 'knows', 'e2', datetime('now'), datetime('now'), ?)",
        (json.dumps(["obs-victim"]),),
    )
    conn.commit()

    run_pending_migrations(conn)

    expected = _obs_id("slack", "", None, 1.0)
    row = conn.execute("SELECT source_ids FROM relationships WHERE id = 'r1'").fetchone()
    sids = json.loads(row["source_ids"])
    assert sids == [expected]
    conn.close()


def test_dedup_deduplicates_source_ids_array(db_path):
    conn = connect(db_path)
    _insert_entity(conn, "e1")
    _insert_obs(conn, "obs-victim", channel_id="", text="test")
    _insert_obs(conn, "obs-survivor", channel_id="C1", text="test")
    conn.execute(
        "INSERT INTO claims "
        "(id, subject_id, predicate, object, first_asserted, last_confirmed, source_ids) "
        "VALUES ('c1', 'e1', 'likes', 'tea', datetime('now'), datetime('now'), ?)",
        (json.dumps(["obs-victim", "obs-survivor"]),),
    )
    conn.commit()

    run_pending_migrations(conn)

    expected = _obs_id("slack", "", None, 1.0)
    row = conn.execute("SELECT source_ids FROM claims WHERE id = 'c1'").fetchone()
    sids = json.loads(row["source_ids"])
    assert sids == [expected]
    conn.close()


def test_dedup_fts_consistent_after_migration(db_path):
    conn = connect(db_path)
    _insert_obs(conn, "obs-a", channel_id="", text="unique alpha message")
    _insert_obs(conn, "obs-b", channel_id="C1", text="unique alpha message")
    _insert_obs(conn, "obs-c", channel_id="C2", text="different beta content", timestamp=2.0)
    conn.commit()

    run_pending_migrations(conn)

    results = conn.execute(
        "SELECT * FROM observations_fts WHERE observations_fts MATCH 'alpha'"
    ).fetchall()
    assert len(results) == 1

    results = conn.execute(
        "SELECT * FROM observations_fts WHERE observations_fts MATCH 'beta'"
    ).fetchall()
    assert len(results) == 1
    conn.close()


def test_dedup_is_idempotent(db_path):
    conn = connect(db_path)
    _insert_obs(conn, "obs-a", channel_id="", text="test")
    _insert_obs(conn, "obs-b", channel_id="C1", text="test")
    conn.commit()

    run_pending_migrations(conn)
    count_first = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    run_pending_migrations(conn)
    count_second = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    assert count_first == count_second == 1
    conn.close()


def test_dedup_noop_when_no_duplicates(db_path):
    conn = connect(db_path)
    _insert_obs(conn, "obs-1", source="slack", text="message one", timestamp=1.0)
    _insert_obs(conn, "obs-2", source="slack", text="message two", timestamp=2.0)
    _insert_obs(conn, "obs-3", source="email", text="message one", timestamp=1.0)
    conn.commit()

    run_pending_migrations(conn)

    count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert count == 3
    conn.close()


def test_dedup_multiple_groups(db_path):
    conn = connect(db_path)
    _insert_obs(conn, "g1-a", channel_id="", text="group one", timestamp=1.0)
    _insert_obs(conn, "g1-b", channel_id="C1", text="group one", timestamp=1.0)
    _insert_obs(conn, "g2-a", channel_id="", text="group two", timestamp=2.0)
    _insert_obs(conn, "g2-b", channel_id="C2", thread_id="T1", text="group two", timestamp=2.0)
    conn.commit()

    run_pending_migrations(conn)

    count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert count == 2
    ids = {r["id"] for r in conn.execute("SELECT id FROM observations").fetchall()}
    assert ids == {_obs_id("slack", "", None, 1.0), _obs_id("slack", "", None, 2.0)}
    conn.close()


def test_dedup_distinct_count_equals_total(db_path):
    conn = connect(db_path)
    _insert_obs(conn, "obs-a", channel_id="", text="test", timestamp=1.0)
    _insert_obs(conn, "obs-b", channel_id="C1", text="test", timestamp=1.0)
    _insert_obs(conn, "obs-c", channel_id="", text="other", timestamp=2.0)
    _insert_obs(conn, "obs-d", channel_id="C2", text="other", timestamp=2.0)
    conn.commit()

    run_pending_migrations(conn)

    total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    distinct = conn.execute(
        """SELECT COUNT(*) FROM (
            SELECT DISTINCT source, timestamp, sender_entity_id, text
            FROM observations
        )"""
    ).fetchone()[0]
    assert total == distinct
    conn.close()


def test_dedup_logs_removed_count(db_path, capsys):
    conn = connect(db_path)
    _insert_obs(conn, "obs-a", channel_id="", text="test")
    _insert_obs(conn, "obs-b", channel_id="C1", text="test")
    conn.commit()

    run_pending_migrations(conn)

    captured = capsys.readouterr()
    assert "removed 1 duplicate" in captured.out
    conn.close()


def test_dedup_no_log_when_no_duplicates(db_path, capsys):
    conn = connect(db_path)
    _insert_obs(conn, "obs-1", text="unique")
    conn.commit()

    run_pending_migrations(conn)

    captured = capsys.readouterr()
    assert "deduplicate" not in captured.out
    conn.close()


def test_dedup_flag_recorded(db_path):
    conn = connect(db_path)
    run_pending_migrations(conn)

    row = conn.execute(
        "SELECT name, applied_at FROM migrations WHERE name = 'deduplicate_observations_v1'"
    ).fetchone()
    assert row is not None
    assert row["applied_at"] is not None
    conn.close()


def test_dedup_different_sender_not_grouped(db_path):
    conn = connect(db_path)
    _insert_entity(conn, "e1")
    _insert_entity(conn, "e2", name="Kai")
    _insert_obs(conn, "obs-1", sender_entity_id="e1", text="same text", timestamp=1.0)
    _insert_obs(conn, "obs-2", sender_entity_id="e2", text="same text", timestamp=2.0)
    conn.commit()

    run_pending_migrations(conn)

    count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert count == 2
    conn.close()


def test_dedup_null_text_grouped(db_path):
    conn = connect(db_path)
    _insert_obs(conn, "obs-a", channel_id="", text=None)
    _insert_obs(conn, "obs-b", channel_id="C1", text=None)
    conn.commit()

    run_pending_migrations(conn)

    count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert count == 1
    row = conn.execute("SELECT id, channel_id FROM observations").fetchone()
    assert row["id"] == _obs_id("slack", "", None, 1.0)
    assert row["channel_id"] == "C1"
    conn.close()


def test_dedup_fts_no_orphaned_entries(db_path):
    conn = connect(db_path)
    _insert_obs(conn, "obs-a", channel_id="", text="orphan check alpha")
    _insert_obs(conn, "obs-b", channel_id="C1", text="orphan check alpha")
    conn.commit()

    run_pending_migrations(conn)

    obs_ids = {r["id"] for r in conn.execute("SELECT id FROM observations").fetchall()}
    fts_rowids = {r[0] for r in conn.execute("SELECT rowid FROM observations_fts").fetchall()}
    placeholders = ",".join("?" for _ in obs_ids)
    real_rowids = {
        r[0]
        for r in conn.execute(
            f"SELECT rowid FROM observations WHERE id IN ({placeholders})",
            list(obs_ids),
        ).fetchall()
    }
    assert fts_rowids == real_rowids
    conn.close()


def test_dedup_aborts_on_live_store_without_backup(tmp_path, monkeypatch):
    live_home = tmp_path / ".patina"
    live_home.mkdir()
    monkeypatch.setattr("patina.store.DEFAULT_HOME", live_home)
    monkeypatch.delenv("PATINA_DEDUP_ALLOW_LIVE", raising=False)

    db_path = live_home / "store.db"
    init_db(db_path)
    conn = connect(db_path)
    _insert_obs(conn, "obs-a", channel_id="", text="test")
    _insert_obs(conn, "obs-b", channel_id="C1", text="test")
    conn.commit()

    with pytest.raises(RuntimeError, match="without a backup"):
        run_pending_migrations(conn)
    conn.close()


def test_dedup_proceeds_on_live_store_with_backup_file(tmp_path, monkeypatch):
    live_home = tmp_path / ".patina"
    live_home.mkdir()
    monkeypatch.setattr("patina.store.DEFAULT_HOME", live_home)
    monkeypatch.delenv("PATINA_DEDUP_ALLOW_LIVE", raising=False)

    db_path = live_home / "store.db"
    init_db(db_path)
    (live_home / "store.db.bak").write_bytes(db_path.read_bytes())

    conn = connect(db_path)
    _insert_obs(conn, "obs-a", channel_id="", text="test")
    _insert_obs(conn, "obs-b", channel_id="C1", text="test")
    conn.commit()

    run_pending_migrations(conn)

    count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert count == 1
    conn.close()


def test_dedup_proceeds_on_live_store_with_env_override(tmp_path, monkeypatch):
    live_home = tmp_path / ".patina"
    live_home.mkdir()
    monkeypatch.setattr("patina.store.DEFAULT_HOME", live_home)
    monkeypatch.setenv("PATINA_DEDUP_ALLOW_LIVE", "1")

    db_path = live_home / "store.db"
    init_db(db_path)
    conn = connect(db_path)
    _insert_obs(conn, "obs-a", channel_id="", text="test")
    _insert_obs(conn, "obs-b", channel_id="C1", text="test")
    conn.commit()

    run_pending_migrations(conn)

    count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert count == 1
    conn.close()


# --- helpers for v3 tests ---


def _skip_earlier_migrations(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for name in [
        "fix_datamark_whitespace_v1",
        "rebuild_journal_fts_v1",
        "add_kv_table_v1",
        "deduplicate_observations_v1",
        "deduplicate_observations_v2",
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO migrations (name, applied_at) VALUES (?, datetime('now'))",
            (name,),
        )
    conn.commit()


# --- v3 re-key migration tests ---


def test_v3_rekeys_observation_id(db_path):
    conn = connect(db_path)
    _skip_earlier_migrations(conn)

    _insert_obs(conn, "old-scheme-id", source="slack_live", channel_id="C123", timestamp=1000000.0)
    conn.commit()

    run_pending_migrations(conn)

    expected = _obs_id("slack_live", "C123", None, 1000000.0)
    row = conn.execute("SELECT id FROM observations").fetchone()
    assert row["id"] == expected
    conn.close()


def test_v3_dedup_collapses_same_target(db_path):
    conn = connect(db_path)
    _skip_earlier_migrations(conn)

    _insert_obs(
        conn,
        "old-id-1",
        source="slack_live",
        channel_id="C123",
        timestamp=1000000.0,
        text="hello world",
    )
    _insert_obs(
        conn,
        "old-id-2",
        source="slack_mcp",
        channel_id="",
        timestamp=1000000.0,
        text="hello world",
    )
    conn.commit()

    run_pending_migrations(conn)

    count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert count == 1
    expected = _obs_id("slack_live", "C123", None, 1000000.0)
    row = conn.execute("SELECT id FROM observations").fetchone()
    assert row["id"] == expected
    conn.close()


def test_v3_dedup_uses_source_preference(db_path):
    conn = connect(db_path)
    _skip_earlier_migrations(conn)

    _insert_obs(
        conn,
        "id-live",
        source="slack_live",
        channel_id="C1",
        timestamp=2000000.0,
        text="hi",
    )
    _insert_obs(
        conn,
        "id-mcp",
        source="slack_mcp",
        channel_id="",
        timestamp=2000000.0,
        text="hi",
    )
    conn.commit()

    run_pending_migrations(conn)

    row = conn.execute("SELECT source FROM observations").fetchone()
    assert row["source"] == "slack_mcp"
    conn.close()


def test_v3_repoints_decisions(db_path):
    conn = connect(db_path)
    _skip_earlier_migrations(conn)

    _insert_obs(conn, "old-obs", source="slack_live", channel_id="C1", timestamp=3000000.0)
    conn.execute(
        "INSERT INTO decisions (id, observation_id, action, acted_at) "
        "VALUES ('dec1', 'old-obs', 'reply', datetime('now'))"
    )
    conn.commit()

    run_pending_migrations(conn)

    expected = _obs_id("slack_live", "C1", None, 3000000.0)
    row = conn.execute("SELECT observation_id FROM decisions WHERE id = 'dec1'").fetchone()
    assert row["observation_id"] == expected
    conn.close()


def test_v3_repoints_action_queue(db_path):
    conn = connect(db_path)
    _skip_earlier_migrations(conn)

    _insert_obs(conn, "old-obs", source="slack_live", channel_id="C1", timestamp=4000000.0)
    conn.execute(
        """INSERT INTO action_queue
           (id, action_type, target_observation_id, confidence,
            status, autonomy_level, created_at)
           VALUES ('act1', 'reply', 'old-obs', 0.9,
                   'proposed', 1, datetime('now'))"""
    )
    conn.commit()

    run_pending_migrations(conn)

    expected = _obs_id("slack_live", "C1", None, 4000000.0)
    row = conn.execute(
        "SELECT target_observation_id FROM action_queue WHERE id = 'act1'"
    ).fetchone()
    assert row["target_observation_id"] == expected
    conn.close()


def test_v3_repoints_claims_source_ids(db_path):
    conn = connect(db_path)
    _skip_earlier_migrations(conn)

    _insert_entity(conn, "e1")
    _insert_obs(conn, "old-obs", source="slack_live", channel_id="C1", timestamp=5000000.0)
    conn.execute(
        "INSERT INTO claims "
        "(id, subject_id, predicate, object, first_asserted, last_confirmed, source_ids) "
        "VALUES ('c1', 'e1', 'likes', 'tea', datetime('now'), datetime('now'), ?)",
        (json.dumps(["old-obs", "other-id"]),),
    )
    conn.commit()

    run_pending_migrations(conn)

    expected = _obs_id("slack_live", "C1", None, 5000000.0)
    row = conn.execute("SELECT source_ids FROM claims WHERE id = 'c1'").fetchone()
    sids = json.loads(row["source_ids"])
    assert expected in sids
    assert "old-obs" not in sids
    assert "other-id" in sids
    conn.close()


def test_v3_repoints_relationships_source_ids(db_path):
    conn = connect(db_path)
    _skip_earlier_migrations(conn)

    _insert_entity(conn, "e1")
    _insert_entity(conn, "e2", name="Kai")
    _insert_obs(conn, "old-obs", source="slack_live", channel_id="C1", timestamp=6000000.0)
    conn.execute(
        "INSERT INTO relationships "
        "(id, subject_id, predicate, object_id, first_seen, last_confirmed, source_ids) "
        "VALUES ('r1', 'e1', 'knows', 'e2', datetime('now'), datetime('now'), ?)",
        (json.dumps(["old-obs"]),),
    )
    conn.commit()

    run_pending_migrations(conn)

    expected = _obs_id("slack_live", "C1", None, 6000000.0)
    row = conn.execute("SELECT source_ids FROM relationships WHERE id = 'r1'").fetchone()
    sids = json.loads(row["source_ids"])
    assert sids == [expected]
    conn.close()


def test_v3_merges_metadata(db_path):
    conn = connect(db_path)
    _skip_earlier_migrations(conn)

    conn.execute(
        """INSERT INTO observations
           (id, source, channel_id, thread_id, timestamp, text, metadata, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (
            "id-mcp",
            "slack_mcp",
            "",
            None,
            7000000.0,
            "msg",
            json.dumps({"channel_name": "general"}),
        ),
    )
    conn.execute(
        """INSERT INTO observations
           (id, source, channel_id, thread_id, timestamp, text, metadata, ingested_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (
            "id-live",
            "slack_live",
            "C1",
            None,
            7000000.0,
            "msg",
            json.dumps({"reactions": ["thumbsup"]}),
        ),
    )
    conn.commit()

    run_pending_migrations(conn)

    row = conn.execute("SELECT metadata FROM observations").fetchone()
    meta = json.loads(row["metadata"])
    assert "channel_name" in meta
    assert "reactions" in meta
    conn.close()


def test_v3_fts_consistent(db_path):
    conn = connect(db_path)
    _skip_earlier_migrations(conn)

    _insert_obs(
        conn,
        "old-a",
        source="slack_live",
        channel_id="C1",
        timestamp=8000000.0,
        text="unique foxtrot message",
    )
    _insert_obs(
        conn,
        "old-b",
        source="slack_mcp",
        channel_id="",
        timestamp=8000000.0,
        text="unique foxtrot message",
    )
    _insert_obs(
        conn,
        "old-c",
        source="slack_live",
        channel_id="C2",
        timestamp=9000000.0,
        text="different golf content",
    )
    conn.commit()

    run_pending_migrations(conn)

    results = conn.execute(
        "SELECT * FROM observations_fts WHERE observations_fts MATCH 'foxtrot'"
    ).fetchall()
    assert len(results) == 1

    results = conn.execute(
        "SELECT * FROM observations_fts WHERE observations_fts MATCH 'golf'"
    ).fetchall()
    assert len(results) == 1
    conn.close()


def test_v3_idempotent(db_path):
    conn = connect(db_path)
    _skip_earlier_migrations(conn)

    _insert_obs(conn, "old-id", source="slack_live", channel_id="C1", timestamp=10000000.0)
    conn.commit()

    run_pending_migrations(conn)
    count_first = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    id_first = conn.execute("SELECT id FROM observations").fetchone()["id"]

    run_pending_migrations(conn)
    count_second = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    id_second = conn.execute("SELECT id FROM observations").fetchone()["id"]

    assert count_first == count_second == 1
    assert id_first == id_second
    conn.close()


def test_v3_noop_when_ids_already_correct(db_path):
    conn = connect(db_path)
    _skip_earlier_migrations(conn)

    correct_id = _obs_id("slack_live", "C1", None, 11000000.0)
    _insert_obs(
        conn,
        correct_id,
        source="slack_live",
        channel_id="C1",
        timestamp=11000000.0,
        text="already correct",
    )
    conn.commit()

    run_pending_migrations(conn)

    row = conn.execute("SELECT id FROM observations").fetchone()
    assert row["id"] == correct_id
    conn.close()


def test_v3_reingest_no_duplicate(db_path):
    conn = connect(db_path)
    _skip_earlier_migrations(conn)

    _insert_obs(
        conn,
        "old-scheme-id",
        source="slack_live",
        channel_id="C999",
        timestamp=12000000.0,
        text="the quick brown fox",
    )
    conn.commit()

    run_pending_migrations(conn)

    new_id = _obs_id("slack_live", "C999", None, 12000000.0)
    row = conn.execute("SELECT id FROM observations").fetchone()
    assert row["id"] == new_id

    obs = Observation(
        id=new_id,
        source="slack_live",
        channel_id="C999",
        thread_id=None,
        timestamp=12000000.0,
        sender_entity_id=None,
        text="the quick brown fox",
        metadata={},
    )
    was_new = insert_observation(conn, obs)
    assert not was_new

    count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert count == 1
    conn.close()


def test_v3_logs_rekey_count(db_path, capsys):
    conn = connect(db_path)
    _skip_earlier_migrations(conn)

    _insert_obs(conn, "old-1", source="slack_live", channel_id="C1", timestamp=13000000.0)
    _insert_obs(conn, "old-2", source="slack_mcp", channel_id="", timestamp=13000000.0)
    conn.commit()

    run_pending_migrations(conn)

    captured = capsys.readouterr()
    assert "rekey_observations_v3" in captured.out
    assert "re-keyed" in captured.out
    conn.close()


def test_v3_outlook_rekey(db_path):
    conn = connect(db_path)
    _skip_earlier_migrations(conn)

    _insert_obs(
        conn,
        "old-outlook-id",
        source="outlook_mcp_email",
        channel_id="email:conv123",
        thread_id="conv123",
        timestamp=14000000.0,
        text="meeting notes",
    )
    conn.commit()

    run_pending_migrations(conn)

    expected = _obs_id("outlook_mcp_email", "email:conv123", "conv123", 14000000.0)
    row = conn.execute("SELECT id FROM observations").fetchone()
    assert row["id"] == expected
    conn.close()


def test_v3_flag_recorded(db_path):
    conn = connect(db_path)
    run_pending_migrations(conn)

    row = conn.execute(
        "SELECT name, applied_at FROM migrations WHERE name = 'rekey_observations_v3'"
    ).fetchone()
    assert row is not None
    assert row["applied_at"] is not None
    conn.close()


# --- entity merge: six-table rewire coverage (#449) ---


def _seed_reference_rows(conn, entity_id):
    """Insert rows so every entity FK column in the six tables references *entity_id*."""
    conn.execute(
        "INSERT INTO observations"
        " (id, source, channel_id, timestamp, sender_entity_id, text, ingested_at)"
        " VALUES (?, 'slack', 'C001', 1.0, ?, 'msg', datetime('now'))",
        (f"obs-{entity_id}", entity_id),
    )
    conn.execute(
        "INSERT INTO claims"
        " (id, subject_id, predicate, object, confidence,"
        "  first_asserted, last_confirmed, decay_rate)"
        " VALUES (?, ?, 'role', 'engineer', 0.5,"
        "  datetime('now'), datetime('now'), 0.02)",
        (f"clm-{entity_id}", entity_id),
    )
    _insert_entity(conn, f"{entity_id}-peer", name="Ren Takeda")
    conn.execute(
        "INSERT INTO relationships"
        " (id, subject_id, predicate, object_id, confidence,"
        "  first_seen, last_confirmed)"
        " VALUES (?, ?, 'works_with', ?, 0.5,"
        "  datetime('now'), datetime('now'))",
        (f"rel-subj-{entity_id}", entity_id, f"{entity_id}-peer"),
    )
    conn.execute(
        "INSERT INTO relationships"
        " (id, subject_id, predicate, object_id, confidence,"
        "  first_seen, last_confirmed)"
        " VALUES (?, ?, 'mentors', ?, 0.5,"
        "  datetime('now'), datetime('now'))",
        (f"rel-obj-{entity_id}", f"{entity_id}-peer", entity_id),
    )
    conn.execute(
        "INSERT INTO predictions"
        " (id, entity_id, prediction_type, prediction, confidence, created_at)"
        " VALUES (?, ?, 'behaviour', 'will reply', 0.8, datetime('now'))",
        (f"pred-{entity_id}", entity_id),
    )
    conn.execute(
        "INSERT INTO style_exemplars"
        " (id, sender_entity_id, recipient_entity_id, text, source, timestamp)"
        " VALUES (?, ?, ?, 'hello', 'slack', 1.0)",
        (f"se-send-{entity_id}", entity_id, f"{entity_id}-peer"),
    )
    conn.execute(
        "INSERT INTO style_exemplars"
        " (id, sender_entity_id, recipient_entity_id, text, source, timestamp)"
        " VALUES (?, ?, ?, 'hi', 'slack', 2.0)",
        (f"se-recv-{entity_id}", f"{entity_id}-peer", entity_id),
    )
    conn.execute(
        "INSERT INTO action_queue"
        " (id, action_type, target_entity_id, confidence,"
        "  status, autonomy_level, created_at)"
        " VALUES (?, 'nudge', ?, 0.7, 'proposed', 1, datetime('now'))",
        (f"aq-{entity_id}", entity_id),
    )
    conn.commit()


_SIX_TABLES = {
    "observations": ("sender_entity_id",),
    "claims": ("subject_id",),
    "relationships": ("subject_id", "object_id"),
    "predictions": ("entity_id",),
    "style_exemplars": ("sender_entity_id", "recipient_entity_id"),
    "action_queue": ("target_entity_id",),
}


def test_merge_rewires_all_six_tables(clean_merge):
    """After merge, zero rows reference the retired entity in any table (#449)."""
    from patina.maintenance import merge_entities

    conn = clean_merge["conn"]
    keep_id = clean_merge["entity_id"]
    drop_id = "cm-drop"

    _insert_entity(conn, drop_id, name="H. Kimura")
    _seed_reference_rows(conn, drop_id)

    merge_entities(conn, keep_id, drop_id)

    for table, columns in _SIX_TABLES.items():
        for col in columns:
            count = conn.execute(
                f"SELECT COUNT(*) AS c FROM {table} WHERE {col} = ?",  # noqa: S608
                (drop_id,),
            ).fetchone()["c"]
            assert count == 0, f"{table}.{col} still references retired entity"


def test_merge_rewires_surviving_entity_inherits_references(clean_merge):
    """After merge, the surviving entity owns every reference row (#449)."""
    from patina.maintenance import merge_entities

    conn = clean_merge["conn"]
    keep_id = clean_merge["entity_id"]
    drop_id = "cm-drop2"

    _insert_entity(conn, drop_id, name="Kimura H.")
    _seed_reference_rows(conn, drop_id)

    merge_entities(conn, keep_id, drop_id)

    for table, columns in _SIX_TABLES.items():
        for col in columns:
            count = conn.execute(
                f"SELECT COUNT(*) AS c FROM {table} WHERE {col} = ?",  # noqa: S608
                (keep_id,),
            ).fetchone()["c"]
            assert count >= 1, f"{table}.{col} missing for surviving entity"


# --- split_dn_sink: channel-peer DN backfill tests (#480) ---

_DN_PREFIX = "/o=TestOrg/ou=Exchange/cn=Recipients"
_DN_TANAKA = f"{_DN_PREFIX}/cn=abcdef01-2345-6789-abcd-ef0123456789-JTANAKA"
_DN_MIYAKE = f"{_DN_PREFIX}/cn=12345678-2345-6789-abcd-ef0123456789-MMIYAKE"


def _setup_dn_sink_entities(conn, sink_aliases, persons):
    _ENT_SQL = (
        "INSERT INTO entities"
        " (id, type, name, aliases, metadata,"
        "  first_seen, last_seen, decay_rate, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}',"
        "  datetime('now'), datetime('now'), 0.02, 0)"
    )
    conn.execute(_ENT_SQL, ("dn-sink", "DN Sink", json.dumps(sink_aliases)))
    for pid, pname, palias_list in persons:
        conn.execute(_ENT_SQL, (pid, pname, json.dumps(palias_list)))


def _insert_obs_meta(conn, obs_id, source, channel_id, entity_id, metadata, timestamp=1.0):
    conn.execute(
        "INSERT INTO observations"
        " (id, source, channel_id, timestamp, sender_entity_id, text, metadata, ingested_at)"
        " VALUES (?, ?, ?, ?, ?, 'msg', ?, datetime('now'))",
        (obs_id, source, channel_id, timestamp, entity_id, json.dumps(metadata)),
    )


def test_split_dn_sink_production_shaped_fixture(db_path):
    """split_dn_sink dry-run with production-shaped metadata (channel_name + reactions only)."""
    from patina.maintenance import split_dn_sink

    conn = connect(db_path)
    _setup_dn_sink_entities(
        conn,
        sink_aliases=[_DN_TANAKA],
        persons=[("person-jt", "Jun Tanaka", ["JTANAKA"])],
    )
    src = "outlook_mcp_email"
    meta = {"channel_name": "general", "reactions": []}
    _insert_obs_meta(conn, "obs-p1", src, "email:conv1", "dn-sink", meta, timestamp=1.0)
    _insert_obs_meta(conn, "obs-p2", src, "email:conv1", "dn-sink", meta, timestamp=2.0)
    conn.commit()

    result = split_dn_sink(conn, "dn-sink", dry_run=True)

    assert result["routable_observations"] is not None
    assert result["unroutable_by_source"] is not None
    assert result["unroutable_by_source"]["outlook_mcp_email"] == 2
    conn.close()


def test_split_dn_sink_two_sender_no_cross_contamination(db_path):
    """Two-sender channel: after backfill, no observation gets the wrong sender's DN."""
    from patina.maintenance import split_dn_sink

    conn = connect(db_path)
    _setup_dn_sink_entities(
        conn,
        sink_aliases=[_DN_TANAKA, _DN_MIYAKE],
        persons=[
            ("person-jt", "Jun Tanaka", ["JTANAKA"]),
            ("person-mm", "Mei Miyake", ["MMIYAKE"]),
        ],
    )
    src, ch = "outlook_mcp_email", "email:conv-shared"
    _insert_obs_meta(conn, "obs-a", src, ch, "dn-sink", {"sender_dn": _DN_TANAKA}, 1.0)
    _insert_obs_meta(conn, "obs-b", src, ch, "dn-sink", {"sender_dn": _DN_MIYAKE}, 2.0)
    _insert_obs_meta(conn, "obs-c", src, ch, "dn-sink", {}, 3.0)
    conn.commit()

    split_dn_sink(conn, "dn-sink", dry_run=False)

    meta_a = json.loads(
        conn.execute("SELECT metadata FROM observations WHERE id = 'obs-a'").fetchone()["metadata"]
    )
    meta_b = json.loads(
        conn.execute("SELECT metadata FROM observations WHERE id = 'obs-b'").fetchone()["metadata"]
    )
    meta_c = json.loads(
        conn.execute("SELECT metadata FROM observations WHERE id = 'obs-c'").fetchone()["metadata"]
    )
    assert meta_a.get("sender_dn") != _DN_MIYAKE
    assert meta_b.get("sender_dn") != _DN_TANAKA
    assert meta_c.get("sender_dn", "") not in (_DN_TANAKA, _DN_MIYAKE)
    conn.close()


def test_split_dn_sink_mixed_dn_channel_zero_backfill(db_path):
    """Mixed-DN channel: observations without sender_dn get zero backfill updates."""
    from patina.maintenance import split_dn_sink

    conn = connect(db_path)
    _setup_dn_sink_entities(
        conn,
        sink_aliases=[_DN_TANAKA, _DN_MIYAKE],
        persons=[
            ("person-jt", "Jun Tanaka", ["JTANAKA"]),
            ("person-mm", "Mei Miyake", ["MMIYAKE"]),
        ],
    )
    src, ch = "outlook_mcp_email", "email:conv-mixed"
    _insert_obs_meta(conn, "obs-m1", src, ch, "dn-sink", {"sender_dn": _DN_TANAKA}, 1.0)
    _insert_obs_meta(conn, "obs-m2", src, ch, "dn-sink", {"sender_dn": _DN_MIYAKE}, 2.0)
    _insert_obs_meta(conn, "obs-m3", src, ch, "dn-sink", {}, 3.0)
    conn.commit()

    split_dn_sink(conn, "dn-sink", dry_run=False)

    meta = json.loads(
        conn.execute("SELECT metadata FROM observations WHERE id = 'obs-m3'").fetchone()["metadata"]
    )
    assert not meta.get("sender_dn")
    conn.close()


def test_split_dn_sink_uniform_dn_channel_all_backfilled(db_path):
    """Uniform-DN channel: all observations without sender_dn get backfilled."""
    from patina.maintenance import split_dn_sink

    conn = connect(db_path)
    _setup_dn_sink_entities(
        conn,
        sink_aliases=[_DN_TANAKA],
        persons=[("person-jt", "Jun Tanaka", ["JTANAKA"])],
    )
    src, ch = "outlook_mcp_email", "email:conv-uniform"
    _insert_obs_meta(conn, "obs-u1", src, ch, "dn-sink", {"sender_dn": _DN_TANAKA}, 1.0)
    _insert_obs_meta(conn, "obs-u2", src, ch, "dn-sink", {"sender_dn": _DN_TANAKA}, 2.0)
    _insert_obs_meta(conn, "obs-u3", src, ch, "dn-sink", {}, 3.0)
    _insert_obs_meta(conn, "obs-u4", src, ch, "dn-sink", {}, 4.0)
    conn.commit()

    split_dn_sink(conn, "dn-sink", dry_run=False)

    for obs_id in ("obs-u3", "obs-u4"):
        meta = json.loads(
            conn.execute("SELECT metadata FROM observations WHERE id = ?", (obs_id,)).fetchone()[
                "metadata"
            ]
        )
        assert meta.get("sender_dn") == _DN_TANAKA
    conn.close()


# --- Alias provenance for merge / split_dn_sink / repair (#509) ---


def _seed_provenance_entity(conn, entity_id, name, aliases):
    """Insert a person entity and one 'added' provenance row per alias."""
    from patina.store import record_alias_provenance

    conn.execute(
        "INSERT INTO entities"
        " (id, type, name, aliases, metadata,"
        "  first_seen, last_seen, decay_rate, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}', datetime('now'), datetime('now'), 0.02, 0)",
        (entity_id, name, json.dumps(aliases)),
    )
    for alias in aliases:
        record_alias_provenance(conn, entity_id, alias, adapter="slack", action="added")


def _provenance_count(conn):
    return conn.execute("SELECT COUNT(*) FROM entity_alias_provenance").fetchone()[0]


def _provenance_rows(conn, entity_id=None, action=None):
    sql = "SELECT entity_id, alias, adapter, action FROM entity_alias_provenance WHERE 1 = 1"
    params: list = []
    if entity_id is not None:
        sql += " AND entity_id = ?"
        params.append(entity_id)
    if action is not None:
        sql += " AND action = ?"
        params.append(action)
    return [dict(r) for r in conn.execute(sql + " ORDER BY rowid", params).fetchall()]


def _latest_action(conn, entity_id, alias):
    row = conn.execute(
        "SELECT action FROM entity_alias_provenance WHERE entity_id = ? AND alias = ?"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (entity_id, alias),
    ).fetchone()
    return row["action"] if row else None


def _entity_aliases(conn, entity_id):
    row = conn.execute("SELECT aliases FROM entities WHERE id = ?", (entity_id,)).fetchone()
    return json.loads(row["aliases"] or "[]")


def test_merge_moves_provenance_rows_to_survivor(db_path):
    """Merge re-points every provenance row at the survivor; row count is unchanged."""
    from patina.maintenance import merge_entities

    conn = connect(db_path)
    _seed_provenance_entity(conn, "pv-keep", "Kai Moreno", ["kmoreno"])
    _seed_provenance_entity(conn, "pv-drop", "K. Moreno", ["K. Moreno", "kai.moreno@example.com"])
    conn.commit()
    before = _provenance_count(conn)

    merge_entities(conn, "pv-keep", "pv-drop")

    rows = _provenance_rows(conn)
    assert rows
    assert all(r["entity_id"] == "pv-keep" for r in rows)
    assert _provenance_rows(conn, entity_id="pv-drop") == []
    assert _provenance_count(conn) == before
    conn.close()


def test_merge_records_added_and_removed_provenance(db_path):
    """Aliases the survivor gains have a live 'added' row; aliases lost have 'removed'."""
    from patina.maintenance import merge_entities

    conn = connect(db_path)
    _seed_provenance_entity(conn, "pv-keep", "Kai Moreno", ["kmoreno"])
    _seed_provenance_entity(conn, "pv-drop", "Kai M.", ["slack:U0EXAMPLE9"])
    conn.commit()
    pre_merge = set(_entity_aliases(conn, "pv-keep")) | set(_entity_aliases(conn, "pv-drop"))

    merge_entities(conn, "pv-keep", "pv-drop")

    post_merge = set(_entity_aliases(conn, "pv-keep"))
    gained = post_merge - {"kmoreno"}
    assert gained == {"Kai M.", "slack:U0EXAMPLE9"}
    for alias in gained:
        assert _latest_action(conn, "pv-keep", alias) == "added", alias

    # The drop name had no provenance row; the merge itself records it.
    name_rows = [r for r in _provenance_rows(conn, "pv-keep") if r["alias"] == "Kai M."]
    assert name_rows == [
        {"entity_id": "pv-keep", "alias": "Kai M.", "adapter": "maintenance", "action": "added"}
    ]

    for alias in pre_merge - post_merge:
        assert _latest_action(conn, "pv-keep", alias) == "removed", alias
    for alias in post_merge:
        assert _latest_action(conn, "pv-keep", alias) != "removed", alias
    conn.close()


_REPAIR_SINK_ALIASES = [
    "user_q",
    "slack:user_q",
    "U0EXAMPLE1",
    "slack:U0EXAMPLE1",
    "U0EXAMPLE2",
    "slack:U0EXAMPLE2",
    "/O=EXAMPLEORG/OU=X",
]


def test_repair_multi_identity_names_records_removed_provenance(db_path):
    """Each alias stripped by repair gets a 'removed' row on that entity."""
    from patina.maintenance import repair_multi_identity_names

    conn = connect(db_path)
    _seed_provenance_entity(conn, "pv-sink", "user_q", _REPAIR_SINK_ALIASES)
    conn.commit()

    result = repair_multi_identity_names(conn, dry_run=False)

    assert result["repaired"] == 1
    remaining = _entity_aliases(conn, "pv-sink")
    stripped = [a for a in _REPAIR_SINK_ALIASES if a not in remaining]
    assert stripped == ["user_q", "slack:user_q"]
    removed = _provenance_rows(conn, action="removed")
    assert [(r["entity_id"], r["alias"]) for r in removed] == [
        ("pv-sink", "user_q"),
        ("pv-sink", "slack:user_q"),
    ]
    conn.close()


def test_repair_multi_identity_names_dry_run_writes_no_provenance(db_path):
    """Dry-run repair leaves provenance rows and entities.aliases untouched."""
    from patina.maintenance import repair_multi_identity_names

    conn = connect(db_path)
    _seed_provenance_entity(conn, "pv-sink", "user_q", _REPAIR_SINK_ALIASES)
    conn.commit()
    count_before = _provenance_count(conn)
    aliases_before = conn.execute("SELECT id, aliases FROM entities ORDER BY id").fetchall()

    result = repair_multi_identity_names(conn, dry_run=True)

    assert result["repaired"] == 1
    assert _provenance_count(conn) == count_before
    aliases_after = conn.execute("SELECT id, aliases FROM entities ORDER BY id").fetchall()
    assert [tuple(r) for r in aliases_after] == [tuple(r) for r in aliases_before]
    conn.close()


def test_split_dn_sink_records_removed_and_added_provenance(db_path):
    """Split writes 'removed' on the sink and 'added' on the target for each routed DN."""
    from patina.maintenance import split_dn_sink

    conn = connect(db_path)
    _setup_dn_sink_entities(
        conn,
        sink_aliases=[_DN_TANAKA, "sinkhandle"],
        persons=[("person-jt", "Jun Tanaka", ["JTANAKA"])],
    )
    _insert_obs_meta(
        conn, "obs-pv1", "outlook_mcp_email", "email:pv", "dn-sink", {"sender_dn": _DN_TANAKA}
    )
    conn.commit()

    result = split_dn_sink(conn, "dn-sink", dry_run=False)

    assert result["observations_routed"] == 1
    assert _entity_aliases(conn, "dn-sink") == ["sinkhandle"]
    assert _entity_aliases(conn, "person-jt") == ["JTANAKA", _DN_TANAKA]
    removed = _provenance_rows(conn, action="removed")
    assert [(r["entity_id"], r["alias"]) for r in removed] == [("dn-sink", _DN_TANAKA)]
    added = _provenance_rows(conn, action="added")
    assert [(r["entity_id"], r["alias"]) for r in added] == [("person-jt", _DN_TANAKA)]
    conn.close()


def test_split_dn_sink_dry_run_writes_no_provenance(db_path):
    """Dry-run split adds no provenance rows."""
    from patina.maintenance import split_dn_sink
    from patina.store import record_alias_provenance

    conn = connect(db_path)
    _setup_dn_sink_entities(
        conn,
        sink_aliases=[_DN_TANAKA],
        persons=[("person-jt", "Jun Tanaka", ["JTANAKA"])],
    )
    _insert_obs_meta(
        conn, "obs-pv2", "outlook_mcp_email", "email:pv", "dn-sink", {"sender_dn": _DN_TANAKA}
    )
    record_alias_provenance(conn, "dn-sink", _DN_TANAKA, adapter="outlook", action="added")
    conn.commit()
    before = _provenance_count(conn)

    result = split_dn_sink(conn, "dn-sink", dry_run=True)

    assert result["routable_observations"] == 1
    assert _provenance_count(conn) == before
    conn.close()
