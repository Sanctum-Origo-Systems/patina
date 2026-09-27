from __future__ import annotations

from patina.store import connect, run_pending_migrations


def _skip_prior_migrations(conn):
    for name in (
        "fix_datamark_whitespace_v1",
        "rebuild_journal_fts_v1",
        "add_kv_table_v1",
        "deduplicate_observations_v1",
        "deduplicate_observations_v2",
        "rekey_observations_v3",
    ):
        conn.execute(
            "INSERT OR IGNORE INTO migrations (name, applied_at) VALUES (?, datetime('now'))",
            (name,),
        )
    conn.commit()


def _create_old_autonomy_schema(conn):
    conn.execute("DROP TABLE IF EXISTS autonomy_state")
    conn.execute(
        """CREATE TABLE autonomy_state (
               id INTEGER PRIMARY KEY CHECK (id = 1),
               level INTEGER NOT NULL DEFAULT 0,
               frozen_until TEXT,
               last_advanced TEXT
           )"""
    )
    conn.commit()


def test_migration_converts_old_row_to_per_domain(db_path):
    conn = connect(db_path)
    _skip_prior_migrations(conn)
    _create_old_autonomy_schema(conn)
    conn.execute(
        "INSERT INTO autonomy_state (id, level, frozen_until, last_advanced) "
        "VALUES (1, 3, '2099-01-01T00:00:00', '2025-06-15T12:00:00')"
    )
    conn.commit()

    run_pending_migrations(conn)

    rows = conn.execute(
        "SELECT domain, level, frozen_until, last_advanced FROM autonomy_state ORDER BY domain"
    ).fetchall()
    assert len(rows) == 3

    domains = {r["domain"] for r in rows}
    assert domains == {"triage", "draft", "send"}

    for r in rows:
        assert r["level"] == 3
        assert r["frozen_until"] == "2099-01-01T00:00:00"
        assert r["last_advanced"] == "2025-06-15T12:00:00"

    conn.close()


def test_migration_handles_empty_old_table(db_path):
    conn = connect(db_path)
    _skip_prior_migrations(conn)
    _create_old_autonomy_schema(conn)

    run_pending_migrations(conn)

    rows = conn.execute("SELECT domain, level FROM autonomy_state ORDER BY domain").fetchall()
    assert len(rows) == 3
    for r in rows:
        assert r["level"] == 0

    conn.close()


def test_migration_is_idempotent(db_path):
    conn = connect(db_path)
    _skip_prior_migrations(conn)
    _create_old_autonomy_schema(conn)
    conn.execute("INSERT INTO autonomy_state (id, level) VALUES (1, 2)")
    conn.commit()

    run_pending_migrations(conn)
    run_pending_migrations(conn)

    rows = conn.execute("SELECT domain, level FROM autonomy_state").fetchall()
    assert len(rows) == 3
    for r in rows:
        assert r["level"] == 2

    conn.close()


def test_migration_skips_when_already_domain_keyed(db_path):
    conn = connect(db_path)
    _skip_prior_migrations(conn)

    run_pending_migrations(conn)

    cols = {r[1] for r in conn.execute("PRAGMA table_info(autonomy_state)").fetchall()}
    assert "domain" in cols
    assert "id" not in cols

    conn.close()


def test_no_check_constraint_after_migration(db_path):
    conn = connect(db_path)
    _skip_prior_migrations(conn)
    _create_old_autonomy_schema(conn)
    conn.execute("INSERT INTO autonomy_state (id, level) VALUES (1, 0)")
    conn.commit()

    run_pending_migrations(conn)

    conn.execute("INSERT INTO autonomy_state (domain, level) VALUES ('custom', 0)")
    conn.commit()

    row = conn.execute("SELECT level FROM autonomy_state WHERE domain = 'custom'").fetchone()
    assert row is not None

    conn.close()
