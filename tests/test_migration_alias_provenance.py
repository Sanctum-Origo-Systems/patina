from __future__ import annotations

import json
import sqlite3

import pytest

from patina.store import connect, record_alias_provenance, run_pending_migrations

_NOW = "2025-01-01T00:00:00+00:00"


def _seed_entity(conn, eid, name, aliases):
    raw = aliases if isinstance(aliases, str) or aliases is None else json.dumps(aliases)
    conn.execute(
        "INSERT INTO entities"
        " (id, type, name, aliases, metadata, first_seen, last_seen, decay_rate, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}', ?, ?, 0.02, 0)",
        (eid, name, raw, _NOW, _NOW),
    )


def _seed_store(conn):
    _seed_entity(conn, "ent-a", "Kai Tanaka", ["kai", "U0KAITANA", "kai.tanaka@example.com"])
    _seed_entity(conn, "ent-b", "Riku Endo", ["riku"])
    _seed_entity(conn, "ent-c", "Yui Sato", [])
    _seed_entity(conn, "ent-d", "Mio Ono", None)
    conn.commit()


def _provenance_rows(conn):
    return conn.execute(
        "SELECT entity_id, alias, adapter, observation_id, action, created_at"
        " FROM entity_alias_provenance ORDER BY entity_id, alias"
    ).fetchall()


def test_table_has_expected_columns(db_path):
    conn = connect(db_path)
    run_pending_migrations(conn)

    cols = [r[1] for r in conn.execute("PRAGMA table_info(entity_alias_provenance)").fetchall()]
    assert cols == ["entity_id", "alias", "adapter", "observation_id", "action", "created_at"]

    row = conn.execute(
        "SELECT 1 FROM migrations WHERE name = 'add_entity_alias_provenance_v1'"
    ).fetchone()
    assert row is not None

    conn.close()


def test_backfill_adds_one_unknown_row_per_existing_alias(db_path):
    conn = connect(db_path)
    _seed_store(conn)

    run_pending_migrations(conn)

    rows = _provenance_rows(conn)
    got = sorted((r["entity_id"], r["alias"]) for r in rows)
    assert got == sorted(
        [
            ("ent-a", "kai"),
            ("ent-a", "U0KAITANA"),
            ("ent-a", "kai.tanaka@example.com"),
            ("ent-b", "riku"),
        ]
    )
    for r in rows:
        assert r["action"] == "added"
        assert r["adapter"] == "unknown"
        assert r["observation_id"] is None
        assert r["created_at"]

    conn.close()


def test_backfill_deduplicates_repeated_alias_within_entity(db_path):
    conn = connect(db_path)
    _seed_entity(conn, "ent-a", "Kai Tanaka", ["kai", "kai"])
    conn.commit()

    run_pending_migrations(conn)

    rows = _provenance_rows(conn)
    assert [(r["entity_id"], r["alias"]) for r in rows] == [("ent-a", "kai")]

    conn.close()


def test_backfill_skips_malformed_aliases(db_path):
    conn = connect(db_path)
    _seed_entity(conn, "ent-a", "Kai Tanaka", "not json")
    _seed_entity(conn, "ent-b", "Riku Endo", '{"x": 1}')
    _seed_entity(conn, "ent-c", "Yui Sato", ["yui"])
    conn.commit()

    run_pending_migrations(conn)

    rows = _provenance_rows(conn)
    assert [(r["entity_id"], r["alias"]) for r in rows] == [("ent-c", "yui")]

    conn.close()


def test_migration_is_idempotent(db_path):
    conn = connect(db_path)
    _seed_store(conn)

    run_pending_migrations(conn)
    first = conn.execute("SELECT COUNT(*) FROM entity_alias_provenance").fetchone()[0]
    run_pending_migrations(conn)
    second = conn.execute("SELECT COUNT(*) FROM entity_alias_provenance").fetchone()[0]

    assert first == 4
    assert second == first

    conn.close()


def test_backfill_rerun_without_migration_marker_does_not_duplicate(db_path):
    conn = connect(db_path)
    _seed_store(conn)

    run_pending_migrations(conn)
    first = conn.execute("SELECT COUNT(*) FROM entity_alias_provenance").fetchone()[0]

    conn.execute("DELETE FROM migrations WHERE name = 'add_entity_alias_provenance_v1'")
    conn.commit()
    run_pending_migrations(conn)
    second = conn.execute("SELECT COUNT(*) FROM entity_alias_provenance").fetchone()[0]

    assert second == first

    conn.close()


def test_entities_aliases_unchanged(db_path):
    conn = connect(db_path)
    _seed_store(conn)
    before = {
        r["id"]: r["aliases"] for r in conn.execute("SELECT id, aliases FROM entities").fetchall()
    }

    run_pending_migrations(conn)

    after = {
        r["id"]: r["aliases"] for r in conn.execute("SELECT id, aliases FROM entities").fetchall()
    }
    assert after == before
    assert json.loads(after["ent-a"]) == ["kai", "U0KAITANA", "kai.tanaka@example.com"]
    assert after["ent-d"] is None

    conn.close()


def test_legacy_table_rebuilt_to_accept_merge_rows(db_path):
    """#555: a pre-'merge' table keeps its rows and gains the 'merge' action."""
    conn = connect(db_path)
    conn.execute(
        """CREATE TABLE entity_alias_provenance (
               entity_id TEXT NOT NULL,
               alias TEXT NOT NULL,
               adapter TEXT NOT NULL,
               observation_id TEXT,
               action TEXT NOT NULL CHECK(action IN ('added', 'removed')),
               created_at TEXT NOT NULL
           )"""
    )
    for alias, action in [("kai", "added"), ("riku", "added"), ("kai", "removed")]:
        conn.execute(
            "INSERT INTO entity_alias_provenance"
            " (entity_id, alias, adapter, observation_id, action, created_at)"
            " VALUES ('ent-a', ?, 'slack', NULL, ?, ?)",
            (alias, action, _NOW),
        )
    conn.execute(
        "INSERT INTO migrations (name, applied_at)"
        " VALUES ('add_entity_alias_provenance_v1', datetime('now'))"
    )
    conn.commit()

    run_pending_migrations(conn)

    rows = conn.execute(
        "SELECT alias, action FROM entity_alias_provenance ORDER BY created_at, rowid"
    ).fetchall()
    assert [tuple(r) for r in rows] == [("kai", "added"), ("riku", "added"), ("kai", "removed")]
    record_alias_provenance(conn, "ent-a", "kai", adapter="slack", action="merge")
    conn.commit()
    indexes = [r[1] for r in conn.execute("PRAGMA index_list(entity_alias_provenance)")]
    assert "idx_alias_provenance_entity" in indexes

    conn.close()


@pytest.mark.parametrize("action", ["added", "removed", "merge"])
def test_write_helper_accepts_valid_actions(db_path, action):
    conn = connect(db_path)
    run_pending_migrations(conn)

    record_alias_provenance(
        conn, "ent-a", "kai", adapter="slack", action=action, observation_id="obs-1"
    )
    conn.commit()

    row = conn.execute(
        "SELECT entity_id, alias, adapter, observation_id, action, created_at"
        " FROM entity_alias_provenance"
    ).fetchone()
    assert row["entity_id"] == "ent-a"
    assert row["alias"] == "kai"
    assert row["adapter"] == "slack"
    assert row["observation_id"] == "obs-1"
    assert row["action"] == action
    assert row["created_at"]

    conn.close()


@pytest.mark.parametrize("action", ["merged", "", "ADDED", "add"])
def test_write_helper_rejects_other_actions(db_path, action):
    conn = connect(db_path)
    run_pending_migrations(conn)

    with pytest.raises(ValueError, match="action"):
        record_alias_provenance(conn, "ent-a", "kai", adapter="slack", action=action)

    count = conn.execute("SELECT COUNT(*) FROM entity_alias_provenance").fetchone()[0]
    assert count == 0

    conn.close()


def test_table_check_constraint_rejects_other_actions(db_path):
    conn = connect(db_path)
    run_pending_migrations(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO entity_alias_provenance"
            " (entity_id, alias, adapter, observation_id, action, created_at)"
            " VALUES ('ent-a', 'kai', 'slack', NULL, 'merged', ?)",
            (_NOW,),
        )

    conn.close()
