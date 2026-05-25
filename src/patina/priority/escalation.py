from __future__ import annotations

import sqlite3
import time

from patina.priority.objectives import list_objectives
from patina.priority.scoring import score_item


def escalation_tier(staleness_days: float) -> str | None:
    if staleness_days >= 7:
        return "urgent"
    if staleness_days >= 3:
        return "gentle"
    return None


def detect_urgency_shifts(
    conn: sqlite3.Connection,
    *,
    since_days: int = 1,
    home=None,
) -> list[dict]:
    cutoff = time.time() - (since_days * 86400)
    rows = conn.execute(
        """SELECT o.id, o.text, o.timestamp, o.sender_entity_id,
                  e.name AS sender_name
           FROM observations o
           LEFT JOIN entities e ON o.sender_entity_id = e.id
           LEFT JOIN decisions d ON o.id = d.observation_id
           WHERE d.id IS NULL AND o.timestamp < ?""",
        (cutoff,),
    ).fetchall()

    objectives = list_objectives(active_only=True, home=home)
    now = time.time()
    shifts: list[dict] = []

    for row in rows:
        staleness = (now - row["timestamp"]) / 86400
        prev_staleness = staleness - since_days

        if prev_staleness < 0:
            continue

        prev_esc = escalation_tier(prev_staleness)
        curr_esc = escalation_tier(staleness)

        prev_score = score_item(
            item_id=row["id"],
            text=row["text"] or "",
            staleness_days=prev_staleness,
            escalation=prev_esc,
            is_commitment=False,
            has_deadline=False,
            sender_tier="unknown",
            objectives=objectives,
            act_on_rate=None,
        )
        curr_score = score_item(
            item_id=row["id"],
            text=row["text"] or "",
            staleness_days=staleness,
            escalation=curr_esc,
            is_commitment=False,
            has_deadline=False,
            sender_tier="unknown",
            objectives=objectives,
            act_on_rate=None,
        )

        if prev_score.quadrant == "Q3" and curr_score.quadrant == "Q1":
            shifts.append(
                {
                    "item_id": row["id"],
                    "text": row["text"],
                    "sender": row["sender_name"],
                    "previous_quadrant": "Q3",
                    "new_quadrant": "Q1",
                    "reason": f"staleness {prev_staleness:.1f}d -> {staleness:.1f}d",
                }
            )

    return shifts
