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


def _infer_dm_recipient(
    conn: sqlite3.Connection, channel_id: str, sender_entity_id: str
) -> str | None:
    row = conn.execute(
        """SELECT DISTINCT sender_entity_id
           FROM observations
           WHERE channel_id = ? AND sender_entity_id != ? AND sender_entity_id IS NOT NULL
           LIMIT 1""",
        (channel_id, sender_entity_id),
    ).fetchone()
    return row["sender_entity_id"] if row else None


def _is_dm_channel(channel_id: str | None, channel_name: str) -> bool:
    if not channel_id:
        return False
    if channel_id.startswith("D"):
        return True
    if channel_name.startswith("dm-") or channel_name.startswith("dm_"):
        return True
    return False


def observe_sent_messages(conn: sqlite3.Connection, user_entity_id: str) -> list[StyleObservation]:
    rows = conn.execute(
        """SELECT o.id, o.text, o.timestamp, o.channel_id, o.metadata
           FROM observations o
           WHERE o.sender_entity_id = ?
           ORDER BY o.timestamp""",
        (user_entity_id,),
    ).fetchall()

    dm_recipient_cache: dict[str, str | None] = {}

    observations: list[StyleObservation] = []
    for row in rows:
        text = row["text"]
        if not text:
            continue

        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        channel_name = meta.get("channel_name", row["channel_id"] or "")
        channel_id = row["channel_id"] or ""

        recipient_uid = _extract_recipient(text)

        if not recipient_uid and _is_dm_channel(channel_id, channel_name):
            if channel_id not in dm_recipient_cache:
                dm_recipient_cache[channel_id] = _infer_dm_recipient(
                    conn, channel_id, user_entity_id
                )
            recipient_uid = dm_recipient_cache[channel_id]

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
