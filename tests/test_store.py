from __future__ import annotations

from patina.store import (
    connect,
    get_db_path,
    get_recent_extraction_runs,
    init_db,
    record_extraction_run,
    run_pending_migrations,
)


def test_get_db_path_creates_dir(tmp_path):
    home = tmp_path / "new_home"
    path = get_db_path(home)
    assert path.parent.exists()
    assert path.name == "store.db"


def test_init_db_creates_all_tables(db_path):
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r["name"] for r in rows}
    expected = {
        "entities",
        "relationships",
        "claims",
        "observations",
        "decisions",
        "objectives",
        "predictions",
        "style_exemplars",
        "style_profiles",
        "action_queue",
        "journal",
        "anti_patterns",
        "conversations",
        "schema_version",
    }
    assert expected.issubset(names)
    conn.close()


def test_init_db_idempotent(db_path):
    init_db(db_path)
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r["name"] for r in rows}
    assert "entities" in names
    conn.close()


def test_schema_version_set(db_path):
    conn = connect(db_path)
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    assert row["version"] == 4
    conn.close()


def test_fts_tables_created(db_path):
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_fts%'"
    ).fetchall()
    names = {r["name"] for r in rows}
    assert "observations_fts" in names
    assert "journal_fts" in names
    assert "claims_fts" in names
    conn.close()


def test_migration_creates_extraction_runs_table(db_path):
    conn = connect(db_path)
    for name in (
        "fix_datamark_whitespace_v1",
        "rebuild_journal_fts_v1",
        "add_kv_table_v1",
        "deduplicate_observations_v1",
        "deduplicate_observations_v2",
        "rekey_observations_v3",
        "domain_keyed_autonomy_state_v1",
    ):
        conn.execute(
            "INSERT INTO migrations (name, applied_at) VALUES (?, datetime('now'))", (name,)
        )
    conn.commit()

    run_pending_migrations(conn)
    run_pending_migrations(conn)

    cols = [r[1] for r in conn.execute("PRAGMA table_info(extraction_runs)").fetchall()]
    assert cols == [
        "id",
        "started_at",
        "finished_at",
        "model",
        "observations_processed",
        "claims_extracted",
        "skipped_unresolved",
        "alias_collisions",
        "empty_skipped",
        "errors",
        "by_source_json",
    ]
    applied = conn.execute(
        "SELECT COUNT(*) FROM migrations WHERE name = 'add_extraction_runs_table_v1'"
    ).fetchone()[0]
    assert applied == 1
    conn.close()


def test_get_recent_extraction_runs_newest_first(db_path):
    conn = connect(db_path)
    stats = {
        "observations_processed": 0,
        "claims_extracted": 0,
        "skipped_unresolved": 0,
        "alias_collisions": 0,
        "empty_skipped": 0,
        "errors": 0,
    }
    for i in range(3):
        record_extraction_run(
            conn,
            started_at=f"2026-10-2{i}T00:00:00+00:00",
            finished_at=f"2026-10-2{i}T00:01:00+00:00",
            model="sonnet",
            stats=stats | {"observations_processed": i},
            by_source={},
        )

    runs = get_recent_extraction_runs(conn, 2)
    assert [r["observations_processed"] for r in runs] == [2, 1]
    conn.close()
