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
