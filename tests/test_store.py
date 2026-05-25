from __future__ import annotations

from patina.store import connect, get_db_path, init_db


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
    assert row["version"] == 1
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
