from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from difflib import SequenceMatcher


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


def _text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def auto_resolve_draft_reply(
    conn: sqlite3.Connection,
    channel_id: str,
    sent_text: str,
) -> str | None:
    from patina.store import get_open_draft_reply_for_channel

    action = get_open_draft_reply_for_channel(conn, channel_id)
    if not action:
        return None

    payload = json.loads(action["payload"]) if action["payload"] else {}
    draft_text = payload.get("draft_text", "")
    if not draft_text:
        return None

    similarity = _text_similarity(sent_text, draft_text)
    outcome = "acted" if similarity >= 0.6 else "edited"
    status = "approved" if outcome == "acted" else "edited"

    now = datetime.now(UTC).isoformat()
    conn.execute(
        """UPDATE action_queue SET status = ?, resolved_at = ?
           WHERE id = ?""",
        (status, now, action["id"]),
    )

    if action["target_observation_id"]:
        record_decision(conn, action["target_observation_id"], outcome)
    else:
        conn.commit()

    return outcome
