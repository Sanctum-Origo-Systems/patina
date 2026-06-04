from __future__ import annotations

import json
import time
from pathlib import Path

from patina.priority.escalation import escalation_tier
from patina.priority.objectives import list_objectives
from patina.priority.scoring import score_item
from patina.store import connect, get_db_path, init_db


def catch_up(*, home: Path | None = None, days: int = 3) -> dict[str, list[dict]]:
    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)

    try:
        now = time.time()
        cutoff = now - (days * 86400)

        rows = conn.execute(
            """SELECT o.id, o.text, o.timestamp, o.sender_entity_id,
                      o.channel_id, o.metadata, o.source,
                      e.name AS sender_name
               FROM observations o
               LEFT JOIN entities e ON o.sender_entity_id = e.id
               LEFT JOIN decisions d ON o.id = d.observation_id
               WHERE d.id IS NULL AND o.timestamp >= ?
                 AND (e.is_owner IS NULL OR e.is_owner = 0)
               ORDER BY o.timestamp DESC""",
            (cutoff,),
        ).fetchall()

        objectives = list_objectives(active_only=True, home=home)

        needs_action: list[dict] = []
        new: list[dict] = []
        waiting: list[dict] = []

        for row in rows:
            staleness = (now - row["timestamp"]) / 86400
            esc = escalation_tier(staleness)

            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            channel_name = meta.get("channel_name", row["channel_id"] or "")

            scored = score_item(
                item_id=row["id"],
                text=row["text"] or "",
                staleness_days=staleness,
                escalation=esc,
                is_commitment=False,
                has_deadline=False,
                sender_tier="unknown",
                objectives=objectives,
                act_on_rate=None,
            )

            item = {
                "id": row["id"],
                "text": row["text"] or "",
                "sender_name": row["sender_name"] or "unknown",
                "channel_name": channel_name,
                "source": row["source"] if "source" in row.keys() else "",
                "permalink": meta.get("permalink", ""),
                "timestamp": row["timestamp"],
                "quadrant": scored.quadrant,
                "urgency": scored.urgency,
                "importance": scored.importance,
                "staleness_days": staleness,
                "escalation": esc,
            }

            if scored.quadrant == "Q1" or esc == "urgent":
                needs_action.append(item)
            elif staleness < 1.0:
                new.append(item)
            else:
                waiting.append(item)

        needs_action.sort(key=lambda x: x["urgency"], reverse=True)
        new.sort(key=lambda x: x["timestamp"], reverse=True)
        waiting.sort(key=lambda x: x["staleness_days"], reverse=True)

        return {
            "needs_action": needs_action,
            "new": new,
            "waiting": waiting,
        }
    finally:
        conn.close()


def priorities(*, home: Path | None = None, days: int = 7) -> dict[str, list[dict]]:
    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)

    try:
        now = time.time()
        cutoff = now - (days * 86400)

        rows = conn.execute(
            """SELECT o.id, o.text, o.timestamp, o.sender_entity_id,
                      o.channel_id, o.metadata, o.source,
                      e.name AS sender_name
               FROM observations o
               LEFT JOIN entities e ON o.sender_entity_id = e.id
               LEFT JOIN decisions d ON o.id = d.observation_id
               WHERE d.id IS NULL AND o.timestamp >= ?
                 AND (e.is_owner IS NULL OR e.is_owner = 0)
               ORDER BY o.timestamp DESC""",
            (cutoff,),
        ).fetchall()

        objectives = list_objectives(active_only=True, home=home)

        result: dict[str, list[dict]] = {"Q1": [], "Q2": [], "Q3": [], "Q4": []}

        for row in rows:
            staleness = (now - row["timestamp"]) / 86400
            esc = escalation_tier(staleness)
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            channel_name = meta.get("channel_name", row["channel_id"] or "")

            scored = score_item(
                item_id=row["id"],
                text=row["text"] or "",
                staleness_days=staleness,
                escalation=esc,
                is_commitment=False,
                has_deadline=False,
                sender_tier="unknown",
                objectives=objectives,
                act_on_rate=None,
            )

            item = {
                "id": row["id"],
                "text": row["text"] or "",
                "sender_name": row["sender_name"] or "unknown",
                "channel_name": channel_name,
                "source": row["source"],
                "permalink": meta.get("permalink", ""),
                "timestamp": row["timestamp"],
                "quadrant": scored.quadrant,
                "urgency": scored.urgency,
                "importance": scored.importance,
                "staleness_days": staleness,
                "escalation": esc,
            }

            result[scored.quadrant].append(item)

        for q in result:
            result[q].sort(key=lambda x: x["urgency"], reverse=True)

        return result
    finally:
        conn.close()
