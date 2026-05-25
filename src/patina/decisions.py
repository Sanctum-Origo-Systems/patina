from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime


def record_decision(
    conn: sqlite3.Connection,
    observation_id: str,
    action: str,
    latency_seconds: float | None = None,
) -> None:
    now = datetime.now(UTC).isoformat()
    dec_id = hashlib.sha256(f"dec:{observation_id}:{now}".encode()).hexdigest()[:16]
    conn.execute(
        """INSERT INTO decisions (id, observation_id, action, acted_at, latency_seconds)
           VALUES (?, ?, ?, ?, ?)""",
        (dec_id, observation_id, action, now, latency_seconds),
    )
    conn.commit()


def get_act_on_rate(
    conn: sqlite3.Connection,
    *,
    sender_entity_id: str | None = None,
    source: str | None = None,
) -> float:
    if sender_entity_id:
        row = conn.execute(
            """SELECT
                   COUNT(*) AS total,
                   SUM(CASE WHEN d.action = 'acted' THEN 1 ELSE 0 END) AS acted
               FROM decisions d
               JOIN observations o ON d.observation_id = o.id
               WHERE o.sender_entity_id = ?""",
            (sender_entity_id,),
        ).fetchone()
    elif source:
        row = conn.execute(
            """SELECT
                   COUNT(*) AS total,
                   SUM(CASE WHEN d.action = 'acted' THEN 1 ELSE 0 END) AS acted
               FROM decisions d
               JOIN observations o ON d.observation_id = o.id
               WHERE o.source = ?""",
            (source,),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT
                   COUNT(*) AS total,
                   SUM(CASE WHEN action = 'acted' THEN 1 ELSE 0 END) AS acted
               FROM decisions"""
        ).fetchone()

    total = row["total"]
    if total == 0:
        return 0.5
    return (row["acted"] or 0) / total
