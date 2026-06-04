"""Owner identity resolution.

The owner is the user of the system — not a contact. Their messages are
outbound evidence about others, not inbound signals requiring attention.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from patina.store import DEFAULT_HOME


def get_owner_user_ids(home: Path | None = None) -> list[str]:
    config_path = (home or DEFAULT_HOME) / "config.yaml"
    if not config_path.exists():
        return []

    import yaml

    with open(config_path) as f:
        config = yaml.safe_load(f) or {}

    owner = config.get("owner", {})
    ids = owner.get("user_ids", [])
    return [str(uid) for uid in ids] if ids else []


def get_owner_entity_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT id FROM entities WHERE is_owner = 1 LIMIT 1").fetchone()
    return row["id"] if row else None


def mark_entity_as_owner(conn: sqlite3.Connection, entity_id: str) -> None:
    conn.execute("UPDATE entities SET is_owner = 1 WHERE id = ?", (entity_id,))
    conn.commit()


def is_owner_entity(conn: sqlite3.Connection, entity_id: str) -> bool:
    row = conn.execute("SELECT is_owner FROM entities WHERE id = ?", (entity_id,)).fetchone()
    return bool(row and row["is_owner"])
