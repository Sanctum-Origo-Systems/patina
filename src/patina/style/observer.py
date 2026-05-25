from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field

from patina.extraction import _make_id


@dataclass
class StyleObservation:
    sender_entity_id: str
    recipient_entity_id: str | None
    text: str
    timestamp: float
    channel_name: str
    metadata: dict = field(default_factory=dict)


_MENTION_RE = re.compile(r"<@([UW][A-Z0-9]+)>")


def _extract_recipient(text: str) -> str | None:
    match = _MENTION_RE.search(text)
    if match:
        return _make_id("person", match.group(1))
    return None


def observe_sent_messages(conn: sqlite3.Connection, user_entity_id: str) -> list[StyleObservation]:
    rows = conn.execute(
        """SELECT o.id, o.text, o.timestamp, o.channel_id, o.metadata
           FROM observations o
           WHERE o.sender_entity_id = ?
           ORDER BY o.timestamp""",
        (user_entity_id,),
    ).fetchall()

    observations: list[StyleObservation] = []
    for row in rows:
        text = row["text"]
        if not text:
            continue

        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        channel_name = meta.get("channel_name", row["channel_id"] or "")
        recipient_uid = _extract_recipient(text)

        observations.append(
            StyleObservation(
                sender_entity_id=user_entity_id,
                recipient_entity_id=recipient_uid,
                text=text,
                timestamp=row["timestamp"],
                channel_name=channel_name,
                metadata=meta,
            )
        )

    return observations
