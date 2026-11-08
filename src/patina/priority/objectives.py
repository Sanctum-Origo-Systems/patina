from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass, field
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
    participants: list[str] = field(default_factory=list)
    customer_domains: list[str] = field(default_factory=list)


def _make_id(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()[:16]


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


def normalize_participants(values: Iterable[str] | None) -> list[str]:
    """Trim, lowercase email addresses, drop empties, de-duplicate in order."""
    cleaned = []
    for v in values or []:
        v = v.strip()
        cleaned.append(v.lower() if "@" in v else v)
    return _dedupe(cleaned)


def normalize_customer_domains(values: Iterable[str] | None) -> list[str]:
    """Trim, lowercase, drop empties, de-duplicate in order."""
    return _dedupe(v.strip().lower() for v in values or [])


def _load_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [str(v) for v in json.loads(raw)]


def _row_to_objective(r: sqlite3.Row) -> Objective:
    return Objective(
        id=r["id"],
        label=r["label"],
        keywords=r["keywords"],
        active=bool(r["active"]),
        created_at=r["created_at"],
        updated_at=r["updated_at"],
        participants=_load_list(r["participants"]),
        customer_domains=_load_list(r["customer_domains"]),
    )


def _resolve_id(conn: sqlite3.Connection, obj_id: str) -> str | None:
    """Resolve a full ID or a unique ID prefix (as printed by list) to a full ID."""
    rows = conn.execute("SELECT id FROM objectives WHERE id LIKE ?", (obj_id + "%",)).fetchall()
    ids = [r["id"] for r in rows]
    if obj_id in ids:
        return obj_id
    return ids[0] if len(ids) == 1 else None


def add_objective(
    label: str,
    keywords: str,
    *,
    participants: Iterable[str] | None = None,
    customer_domains: Iterable[str] | None = None,
    home: Path | None = None,
) -> Objective:
    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    try:
        now = datetime.now(UTC).isoformat()
        obj_id = _make_id(label)
        parts = normalize_participants(participants)
        domains = normalize_customer_domains(customer_domains)
        conn.execute(
            """INSERT INTO objectives
                   (id, label, keywords, active, created_at, updated_at,
                    participants, customer_domains)
               VALUES (?, ?, ?, 1, ?, ?, ?, ?)""",
            (obj_id, label, keywords, now, now, json.dumps(parts), json.dumps(domains)),
        )
        conn.commit()
        return Objective(
            id=obj_id,
            label=label,
            keywords=keywords,
            active=True,
            created_at=now,
            updated_at=now,
            participants=parts,
            customer_domains=domains,
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
        return [_row_to_objective(r) for r in rows]
    finally:
        conn.close()


def get_objective(obj_id: str, *, home: Path | None = None) -> Objective | None:
    """Fetch one objective by full ID or unique ID prefix."""
    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    try:
        full_id = _resolve_id(conn, obj_id)
        if full_id is None:
            return None
        row = conn.execute("SELECT * FROM objectives WHERE id = ?", (full_id,)).fetchone()
        return _row_to_objective(row)
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
    participants: Iterable[str] | None = None,
    customer_domains: Iterable[str] | None = None,
    home: Path | None = None,
) -> bool:
    """Update the given fields; None leaves a field unchanged, a list replaces it."""
    db_path = get_db_path(home)
    init_db(db_path)
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
        if participants is not None:
            updates.append("participants = ?")
            params.append(json.dumps(normalize_participants(participants)))
        if customer_domains is not None:
            updates.append("customer_domains = ?")
            params.append(json.dumps(normalize_customer_domains(customer_domains)))
        if not updates:
            return False
        full_id = _resolve_id(conn, obj_id)
        if full_id is None:
            return False
        updates.append("updated_at = ?")
        params.append(now)
        params.append(full_id)
        cur = conn.execute(
            f"UPDATE objectives SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
