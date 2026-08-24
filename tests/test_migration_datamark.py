import uuid

from patina.store import connect, run_pending_migrations

DM = ""


def test_migrations_table_created(db_path):
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='migrations'"
    ).fetchall()
    assert len(rows) == 1
    conn.close()


def test_migration_fixes_observations(db_path):
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO observations (id, source, timestamp, text, ingested_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        ("obs1", "test", 1.0, f"security{DM}changes{DM}quickly"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO migrations (name, applied_at) "
        "VALUES ('rekey_observations_v3', datetime('now'))"
    )
    conn.commit()

    run_pending_migrations(conn)

    row = conn.execute("SELECT text FROM observations WHERE id = 'obs1'").fetchone()
    assert row["text"] == "security changes quickly"
    conn.close()


def test_migration_runs_exactly_once(db_path):
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO observations (id, source, timestamp, text, ingested_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        ("obs1", "test", 1.0, f"Moved{DM}to{DM}tomorrow"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO migrations (name, applied_at) "
        "VALUES ('rekey_observations_v3', datetime('now'))"
    )
    conn.commit()

    run_pending_migrations(conn)

    conn.execute(
        "UPDATE observations SET text = ? WHERE id = 'obs1'",
        (f"re-broken{DM}text",),
    )
    conn.commit()

    run_pending_migrations(conn)

    row = conn.execute("SELECT text FROM observations WHERE id = 'obs1'").fetchone()
    assert row["text"] == f"re-broken{DM}text"
    conn.close()


def test_fts_rebuilt_after_migration(db_path):
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO observations (id, source, timestamp, text, ingested_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        ("obs1", "test", 1.0, f"security{DM}changes{DM}quickly"),
    )
    conn.commit()

    run_pending_migrations(conn)

    results = conn.execute(
        "SELECT * FROM observations_fts WHERE observations_fts MATCH '\"security changes\"'"
    ).fetchall()
    assert len(results) == 1
    conn.close()


def test_migration_skips_clean_observations(db_path):
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO observations (id, source, timestamp, text, ingested_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        ("obs1", "test", 1.0, "already clean text"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO migrations (name, applied_at) "
        "VALUES ('rekey_observations_v3', datetime('now'))"
    )
    conn.commit()

    run_pending_migrations(conn)

    row = conn.execute("SELECT text FROM observations WHERE id = 'obs1'").fetchone()
    assert row["text"] == "already clean text"
    conn.close()


def test_migration_logs_affected_count(db_path, capsys):
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO observations (id, source, timestamp, text, ingested_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        ("obs1", "test", 1.0, f"broken{DM}text"),
    )
    conn.execute(
        "INSERT INTO observations (id, source, timestamp, text, ingested_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        ("obs2", "test", 2.0, f"also{DM}broken"),
    )
    conn.commit()

    run_pending_migrations(conn)

    captured = capsys.readouterr()
    assert "fixed 2 observations" in captured.out
    conn.close()


def test_migration_no_log_when_zero_affected(db_path, capsys):
    conn = connect(db_path)
    conn.execute(
        "INSERT INTO observations (id, source, timestamp, text, ingested_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        ("obs1", "test", 1.0, "clean text"),
    )
    conn.commit()

    run_pending_migrations(conn)

    captured = capsys.readouterr()
    assert "fixed" not in captured.out
    conn.close()


def test_migration_flag_recorded(db_path):
    conn = connect(db_path)
    run_pending_migrations(conn)

    row = conn.execute(
        "SELECT name, applied_at FROM migrations WHERE name = 'fix_datamark_whitespace_v1'"
    ).fetchone()
    assert row is not None
    assert row["applied_at"] is not None
    conn.close()


def test_rebuild_journal_fts_indexes_preexisting_entries(db_path):
    conn = connect(db_path)
    entry_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO journal (id, date, body, created_at) VALUES (?, ?, ?, datetime('now'))",
        (entry_id, "2026-05-01", "Reviewed the zephyr proposal and delta roadmap"),
    )
    conn.commit()

    conn.execute("DELETE FROM journal_fts")
    conn.commit()

    results = conn.execute("SELECT * FROM journal_fts WHERE journal_fts MATCH 'zephyr'").fetchall()
    assert len(results) == 0

    run_pending_migrations(conn)

    results = conn.execute("SELECT * FROM journal_fts WHERE journal_fts MATCH 'zephyr'").fetchall()
    assert len(results) == 1

    results = conn.execute(
        "SELECT * FROM journal_fts WHERE journal_fts MATCH 'zephyr delta'"
    ).fetchall()
    assert len(results) == 1
    conn.close()


def test_rebuild_journal_fts_is_idempotent(db_path):
    conn = connect(db_path)
    entry_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO journal (id, date, body, created_at) VALUES (?, ?, ?, datetime('now'))",
        (entry_id, "2026-06-01", "Notes about the vortex integration"),
    )
    conn.commit()

    conn.execute("DELETE FROM journal_fts")
    conn.commit()

    run_pending_migrations(conn)
    run_pending_migrations(conn)

    results = conn.execute("SELECT * FROM journal_fts WHERE journal_fts MATCH 'vortex'").fetchall()
    assert len(results) == 1
    conn.close()


def test_rebuild_journal_fts_flag_recorded(db_path):
    conn = connect(db_path)
    run_pending_migrations(conn)

    row = conn.execute(
        "SELECT name, applied_at FROM migrations WHERE name = 'rebuild_journal_fts_v1'"
    ).fetchone()
    assert row is not None
    assert row["applied_at"] is not None
    conn.close()
