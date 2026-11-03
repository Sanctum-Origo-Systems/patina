"""Scratch-store identity gate (#577).

Builds a seed store from the fixtures in tests/fixtures/identity_gate/ and
copies a live store to a scratch path so identity resolution can be replayed
without touching the source. The source store is only ever opened read-only.

Part 1 (#584): fixtures, loader and scratch copy. Replay and report come later.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

import patina.store as store_module
from patina.store import connect, init_db, run_pending_migrations

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "identity_gate"

_SEED_TIMESTAMP = "2025-10-30T00:00:00+00:00"


def load_fixtures(fixtures_dir: Path = FIXTURES_DIR) -> dict:
    """Read the fixture set: ``{"entities": [...], "messages": [...]}``."""
    seed = json.loads((fixtures_dir / "seed.json").read_text())
    messages = json.loads((fixtures_dir / "messages.json").read_text())
    return {"entities": seed["entities"], "messages": messages["messages"]}


def build_seed_store(db_path: Path, fixtures_dir: Path = FIXTURES_DIR) -> Path:
    """Create a store at *db_path* with the real schema and the fixture seed entities."""
    fixtures = load_fixtures(fixtures_dir)
    init_db(db_path)
    conn = connect(db_path)
    try:
        run_pending_migrations(conn)
        for ent in fixtures["entities"]:
            conn.execute(
                "INSERT INTO entities"
                " (id, type, name, aliases, metadata, first_seen, last_seen, is_owner)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ent["id"],
                    ent["type"],
                    ent["name"],
                    json.dumps(ent.get("aliases", [])),
                    json.dumps(ent.get("metadata", {})),
                    _SEED_TIMESTAMP,
                    _SEED_TIMESTAMP,
                    int(ent.get("is_owner", 0)),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scratch_copy(source: Path | None = None, dest_dir: Path | None = None) -> Path:
    """Copy *source* (default ``~/.patina/store.db``) to a scratch path via SQLite's backup API.

    The source is opened read-only. Its SHA-256 is recorded before and after
    the copy; a RuntimeError is raised if it changed.
    """
    source = source if source is not None else store_module.DEFAULT_HOME / "store.db"
    if not source.is_file():
        raise FileNotFoundError(f"Source store not found: {source}")
    if dest_dir is None:
        dest_dir = Path(tempfile.mkdtemp(prefix="patina-identity-gate-"))
    dest = dest_dir / "store.db"

    before = sha256_file(source)
    src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    after = sha256_file(source)

    if after != before:
        raise RuntimeError(f"Source store changed during scratch copy: {source}")
    return dest
