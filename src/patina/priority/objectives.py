from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from patina.store import connect, get_db_path, init_db


@dataclass
class Objective:
    id: str
    label: str
    keywords: str
    active: bool
    created_at: str
    updated_at: str


def _make_id(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()[:16]


def add_objective(label: str, keywords: str, *, home: Path | None = None) -> Objective:
    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        obj_id = _make_id(label)
        conn.execute(
            """INSERT INTO objectives (id, label, keywords, active, created_at, updated_at)
               VALUES (?, ?, ?, 1, ?, ?)""",
            (obj_id, label, keywords, now, now),
        )
        conn.commit()
        return Objective(
            id=obj_id,
            label=label,
            keywords=keywords,
            active=True,
            created_at=now,
            updated_at=now,
        )
    finally:
        conn.close()


def list_objectives(*, active_only: bool = True, home: Path | None = None) -> list[Objective]:
    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    try:
        if active_only:
            rows = conn.execute("SELECT * FROM objectives WHERE active = 1").fetchall()
        else:
            rows = conn.execute("SELECT * FROM objectives").fetchall()
        return [
            Objective(
                id=r["id"],
                label=r["label"],
                keywords=r["keywords"],
                active=bool(r["active"]),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]
    finally:
        conn.close()


def remove_objective(obj_id: str, *, home: Path | None = None) -> bool:
    db_path = get_db_path(home)
    conn = connect(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        cur = conn.execute(
            "UPDATE objectives SET active = 0, updated_at = ? WHERE id = ?",
            (now, obj_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_objective(
    obj_id: str,
    *,
    label: str | None = None,
    keywords: str | None = None,
    home: Path | None = None,
) -> bool:
    db_path = get_db_path(home)
    conn = connect(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        updates = []
        params: list = []
        if label is not None:
            updates.append("label = ?")
            params.append(label)
        if keywords is not None:
            updates.append("keywords = ?")
            params.append(keywords)
        if not updates:
            return False
        updates.append("updated_at = ?")
        params.append(now)
        params.append(obj_id)
        cur = conn.execute(
            f"UPDATE objectives SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
