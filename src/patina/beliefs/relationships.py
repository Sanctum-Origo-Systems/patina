from __future__ import annotations

import sqlite3
import time


def compute_interaction_stats(conn: sqlite3.Connection, entity_id: str) -> dict:
    rows = conn.execute(
        """SELECT timestamp FROM observations
           WHERE sender_entity_id = ?
              OR text LIKE '%' || ? || '%'
           ORDER BY timestamp""",
        (entity_id, entity_id),
    ).fetchall()

    if not rows:
        return {
            "message_count": 0,
            "last_interaction": None,
            "first_interaction": None,
            "avg_messages_per_week": 0.0,
            "days_since_last": None,
        }

    timestamps = [r["timestamp"] for r in rows]
    first = timestamps[0]
    last = timestamps[-1]
    now = time.time()

    span_weeks = max((last - first) / (7 * 86400), 1.0)
    avg_per_week = len(timestamps) / span_weeks

    return {
        "message_count": len(timestamps),
        "last_interaction": last,
        "first_interaction": first,
        "avg_messages_per_week": round(avg_per_week, 2),
        "days_since_last": round((now - last) / 86400, 1),
    }


def compute_trust_level(conn: sqlite3.Connection, entity_id: str) -> float:
    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN d.action = 'acted' THEN 1 ELSE 0 END) AS acted
           FROM decisions d
           JOIN observations o ON d.observation_id = o.id
           WHERE o.sender_entity_id = ?""",
        (entity_id,),
    ).fetchone()

    if row["total"] == 0:
        return 0.5

    return round((row["acted"] or 0) / row["total"], 3)


def _classify_activity(avg_per_week: float, days_since_last: float | None) -> str:
    if days_since_last is None:
        return "dormant"
    if days_since_last > 60:
        return "dormant"
    if avg_per_week < 1.0 or days_since_last > 7:
        return "low-frequency"
    return "active"


def get_relationship_map(conn: sqlite3.Connection, *, top_n: int = 20) -> list[dict]:
    entities = conn.execute(
        "SELECT id, name FROM entities WHERE type = 'person' AND is_owner = 0"
    ).fetchall()

    results: list[dict] = []
    for ent in entities:
        stats = compute_interaction_stats(conn, ent["id"])
        if stats["message_count"] == 0:
            continue

        trust = compute_trust_level(conn, ent["id"])
        activity = _classify_activity(stats["avg_messages_per_week"], stats["days_since_last"])

        results.append(
            {
                "entity_id": ent["id"],
                "name": ent["name"],
                "trust_level": trust,
                "activity_status": activity,
                "avg_per_week": stats["avg_messages_per_week"],
                "days_since_last": stats["days_since_last"],
                "message_count": stats["message_count"],
            }
        )

    results.sort(key=lambda x: x["trust_level"], reverse=True)
    return results[:top_n]
