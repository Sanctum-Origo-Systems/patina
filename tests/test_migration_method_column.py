from __future__ import annotations

import json

import pytest

from patina.ingest import _obs_id
from patina.store import connect, run_pending_migrations

_NOW = "2025-01-01T00:00:00+00:00"
_LABELS = ["extraction", "behavioral_extraction", "envoy_migration"]
# Canonical id, so the observation re-key migration leaves it in place.
_OBS_ID = _obs_id("test", "", None, 1.0)


def _legacy_store(db_path):
    """Open a store whose claims and relationships predate the method column."""
    conn = connect(db_path)
    conn.execute("ALTER TABLE claims DROP COLUMN method")
    conn.execute("ALTER TABLE relationships DROP COLUMN method")
    for eid, name in [("ent-a", "Jordan Example"), ("ent-b", "Casey Sample")]:
        conn.execute(
            "INSERT INTO entities (id, type, name, first_seen, last_seen)"
            " VALUES (?, 'person', ?, ?, ?)",
            (eid, name, _NOW, _NOW),
        )
    conn.commit()
    return conn


def _insert_claim(conn, cid, source_ids, obj="The quick brown fox"):
    conn.execute(
        "INSERT INTO claims"
        " (id, subject_id, predicate, object, confidence,"
        "  first_asserted, last_confirmed, decay_rate, source_ids)"
        " VALUES (?, 'ent-a', 'prefers', ?, 0.7, ?, ?, 0.02, ?)",
        (cid, obj, _NOW, _NOW, source_ids),
    )


def _insert_rel(conn, rid, source_ids, predicate="works_with"):
    conn.execute(
        "INSERT INTO relationships"
        " (id, subject_id, predicate, object_id, confidence,"
        "  first_seen, last_confirmed, source_ids)"
        " VALUES (?, 'ent-a', ?, 'ent-b', 0.6, ?, ?, ?)",
        (rid, predicate, _NOW, _NOW, source_ids),
    )


def _insert_obs(conn):
    conn.execute(
        "INSERT INTO observations (id, source, timestamp, text, ingested_at)"
        " VALUES (?, 'test', 1.0, 'The quick brown fox', ?)",
        (_OBS_ID, _NOW),
    )


def _columns(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _snapshot(conn):
    return {
        table: [
            tuple(r)
            for r in conn.execute(f"SELECT id, source_ids, method FROM {table} ORDER BY id")
        ]
        for table in ("claims", "relationships")
    }


@pytest.mark.parametrize("label", _LABELS)
def test_claim_label_moves_to_method(db_path, label):
    conn = _legacy_store(db_path)
    _insert_claim(conn, "claim-1", json.dumps([label]))
    conn.commit()

    run_pending_migrations(conn)

    row = conn.execute("SELECT method, source_ids FROM claims WHERE id = 'claim-1'").fetchone()
    assert row["method"] == label
    assert json.loads(row["source_ids"]) == []
    conn.close()


def test_all_claim_labels_move_in_one_store(db_path):
    conn = _legacy_store(db_path)
    _insert_claim(conn, "claim-x", '["extraction"]')
    _insert_claim(conn, "claim-b", '["behavioral_extraction"]')
    _insert_claim(conn, "claim-e", '["envoy_migration"]')
    conn.commit()

    run_pending_migrations(conn)

    rows = {
        r["id"]: (r["method"], json.loads(r["source_ids"]))
        for r in conn.execute("SELECT id, method, source_ids FROM claims").fetchall()
    }
    assert rows == {
        "claim-x": ("extraction", []),
        "claim-b": ("behavioral_extraction", []),
        "claim-e": ("envoy_migration", []),
    }
    conn.close()


@pytest.mark.parametrize("label", _LABELS)
def test_relationship_label_moves_to_method(db_path, label):
    conn = _legacy_store(db_path)
    _insert_rel(conn, "rel-1", json.dumps([label]))
    conn.commit()

    run_pending_migrations(conn)

    row = conn.execute("SELECT method, source_ids FROM relationships WHERE id = 'rel-1'").fetchone()
    assert row["method"] == label
    assert json.loads(row["source_ids"]) == []
    conn.close()


def test_real_observation_ids_left_unchanged(db_path):
    conn = _legacy_store(db_path)
    _insert_obs(conn)
    real = json.dumps([_OBS_ID])
    _insert_claim(conn, "claim-real", real)
    _insert_rel(conn, "rel-real", real)
    conn.commit()

    run_pending_migrations(conn)

    claim = conn.execute("SELECT method, source_ids FROM claims WHERE id = 'claim-real'").fetchone()
    assert claim["source_ids"] == real
    assert claim["method"] is None
    rel = conn.execute(
        "SELECT method, source_ids FROM relationships WHERE id = 'rel-real'"
    ).fetchone()
    assert rel["source_ids"] == real
    assert rel["method"] is None
    conn.close()


def test_label_mixed_with_observation_id_left_unchanged(db_path):
    conn = _legacy_store(db_path)
    _insert_claim(conn, "claim-mixed", '["extraction", "a1b2c3d4e5f60718"]')
    _insert_claim(conn, "claim-null", None)
    conn.commit()

    run_pending_migrations(conn)

    rows = {
        r["id"]: (r["method"], r["source_ids"])
        for r in conn.execute("SELECT id, method, source_ids FROM claims").fetchall()
    }
    assert rows == {
        "claim-mixed": (None, '["extraction", "a1b2c3d4e5f60718"]'),
        "claim-null": (None, None),
    }
    conn.close()


def test_migration_is_idempotent(db_path):
    conn = _legacy_store(db_path)
    _insert_claim(conn, "claim-x", '["extraction"]')
    _insert_claim(conn, "claim-real", '["a1b2c3d4e5f60718"]')
    _insert_rel(conn, "rel-b", '["behavioral_extraction"]')
    conn.commit()

    run_pending_migrations(conn)
    first = _snapshot(conn)
    run_pending_migrations(conn)
    second = _snapshot(conn)

    assert second == first
    assert first["claims"] == [
        ("claim-real", '["a1b2c3d4e5f60718"]', None),
        ("claim-x", "[]", "extraction"),
    ]
    assert first["relationships"] == [("rel-b", "[]", "behavioral_extraction")]
    conn.close()


def test_rerun_without_marker_does_not_raise(db_path):
    conn = _legacy_store(db_path)
    _insert_claim(conn, "claim-x", '["extraction"]')
    conn.commit()

    run_pending_migrations(conn)
    first = _snapshot(conn)
    conn.execute("DELETE FROM migrations WHERE name = 'add_method_column_v1'")
    conn.commit()
    run_pending_migrations(conn)

    assert _snapshot(conn) == first
    conn.close()


def test_method_column_added_by_migration(db_path):
    conn = _legacy_store(db_path)
    assert "method" not in _columns(conn, "claims")
    assert "method" not in _columns(conn, "relationships")

    run_pending_migrations(conn)

    assert "method" in _columns(conn, "claims")
    assert "method" in _columns(conn, "relationships")
    conn.close()


def test_fresh_store_has_method_column(db_path):
    conn = connect(db_path)
    assert "method" in _columns(conn, "claims")
    assert "method" in _columns(conn, "relationships")
    conn.close()
