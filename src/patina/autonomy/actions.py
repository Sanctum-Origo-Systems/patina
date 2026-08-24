from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime

from patina.autonomy.levels import freeze_advancement
from patina.decisions import record_decision


def propose_action(
    conn: sqlite3.Connection,
    *,
    action_type: str,
    target_observation_id: str | None = None,
    target_entity_id: str | None = None,
    payload: dict | None = None,
    confidence: float,
    autonomy_level: int,
) -> str:
    now = datetime.now(UTC).isoformat()
    action_id = hashlib.sha256(
        f"action:{action_type}:{target_observation_id}:{now}".encode()
    ).hexdigest()[:16]

    conn.execute(
        """INSERT INTO action_queue
               (id, action_type, target_observation_id, target_entity_id,
                payload, confidence, status, autonomy_level, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'proposed', ?, ?)""",
        (
            action_id,
            action_type,
            target_observation_id,
            target_entity_id,
            json.dumps(payload or {}),
            confidence,
            autonomy_level,
            now,
        ),
    )
    conn.commit()
    return action_id


def list_pending(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT id, action_type, target_observation_id, target_entity_id,
                  payload, confidence, autonomy_level, created_at
           FROM action_queue WHERE status = 'proposed'
           ORDER BY created_at DESC"""
    ).fetchall()
    return [
        {
            "id": r["id"],
            "action_type": r["action_type"],
            "target_observation_id": r["target_observation_id"],
            "target_entity_id": r["target_entity_id"],
            "payload": json.loads(r["payload"]) if r["payload"] else {},
            "confidence": r["confidence"],
            "autonomy_level": r["autonomy_level"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def approve_action(conn: sqlite3.Connection, action_id: str) -> bool:
    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        """UPDATE action_queue SET status = 'approved', resolved_at = ?
           WHERE id = ? AND status = 'proposed'""",
        (now, action_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        return False

    row = conn.execute(
        "SELECT target_observation_id FROM action_queue WHERE id = ?",
        (action_id,),
    ).fetchone()
    if row and row["target_observation_id"]:
        record_decision(conn, row["target_observation_id"], "acted")
    return True


def reject_action(conn: sqlite3.Connection, action_id: str) -> bool:
    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        """UPDATE action_queue SET status = 'rejected', resolved_at = ?
           WHERE id = ? AND status = 'proposed'""",
        (now, action_id),
    )
    conn.commit()
    if cur.rowcount == 0:
        return False

    row = conn.execute(
        "SELECT target_observation_id FROM action_queue WHERE id = ?",
        (action_id,),
    ).fetchone()
    if row and row["target_observation_id"]:
        record_decision(conn, row["target_observation_id"], "rejected")

    freeze_advancement(conn)
    return True


def execute_action(conn: sqlite3.Connection, action_id: str) -> bool:
    now = datetime.now(UTC).isoformat()
    cur = conn.execute(
        """UPDATE action_queue SET status = 'executed', resolved_at = ?
           WHERE id = ? AND status IN ('approved', 'proposed')""",
        (now, action_id),
    )
    conn.commit()
    return cur.rowcount > 0


def auto_execute_eligible(conn: sqlite3.Connection, current_level: int) -> int:
    rows = conn.execute(
        """SELECT id FROM action_queue
           WHERE status = 'proposed'
             AND autonomy_level <= ?
             AND confidence >= 0.8""",
        (current_level,),
    ).fetchall()

    count = 0
    for row in rows:
        now = datetime.now(UTC).isoformat()
        conn.execute(
            """UPDATE action_queue SET status = 'executed', resolved_at = ?
               WHERE id = ?""",
            (now, row["id"]),
        )
        count += 1

    conn.commit()
    return count
