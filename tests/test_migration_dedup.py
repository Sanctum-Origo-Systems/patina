import json

import pytest

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
    assert row["id"] == "obs-b"
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
    row = conn.execute("SELECT id FROM observations").fetchone()
    assert row["id"] == "obs-3"
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

    row = conn.execute("SELECT observation_id FROM decisions WHERE id = 'dec1'").fetchone()
    assert row["observation_id"] == "obs-survivor"
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

    row = conn.execute(
        "SELECT target_observation_id FROM action_queue WHERE id = 'act1'"
    ).fetchone()
    assert row["target_observation_id"] == "obs-survivor"
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

    row = conn.execute("SELECT source_ids FROM claims WHERE id = 'c1'").fetchone()
    sids = json.loads(row["source_ids"])
    assert "obs-victim" not in sids
    assert "obs-survivor" in sids
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

    row = conn.execute("SELECT source_ids FROM relationships WHERE id = 'r1'").fetchone()
    sids = json.loads(row["source_ids"])
    assert sids == ["obs-survivor"]
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

    row = conn.execute("SELECT source_ids FROM claims WHERE id = 'c1'").fetchone()
    sids = json.loads(row["source_ids"])
    assert sids == ["obs-survivor"]
    conn.close()


def test_dedup_fts_consistent_after_migration(db_path):
    conn = connect(db_path)
    _insert_obs(conn, "obs-a", channel_id="", text="unique alpha message")
    _insert_obs(conn, "obs-b", channel_id="C1", text="unique alpha message")
    _insert_obs(conn, "obs-c", channel_id="C2", text="different beta content")
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
    assert ids == {"g1-b", "g2-b"}
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
    _insert_obs(conn, "obs-1", sender_entity_id="e1", text="same text")
    _insert_obs(conn, "obs-2", sender_entity_id="e2", text="same text")
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
    row = conn.execute("SELECT id FROM observations").fetchone()
    assert row["id"] == "obs-b"
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
