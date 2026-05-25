from __future__ import annotations

import hashlib
from pathlib import Path

from patina.export_parser import parse_slack_export
from patina.extraction import extract_entities_from_text, extract_sender_entity
from patina.graph import (
    count_entities,
    count_observations,
    insert_observation,
    upsert_entity,
)
from patina.models import Observation
from patina.store import connect, get_db_path, init_db


def _obs_id(source: str, channel_id: str, thread_id: str | None, ts: float) -> str:
    key = f"{source}:{channel_id}:{thread_id or ''}:{ts}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def ingest_from_export(zip_path: Path, *, home: Path | None = None) -> dict:
    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)

    try:
        messages, users, channels = parse_slack_export(zip_path)

        inserted = 0
        skipped = 0
        entity_ids_seen: set[str] = set()

        for msg in messages:
            obs_id = _obs_id("slack_export", msg.channel_id, msg.thread_id, msg.timestamp)
            obs = Observation(
                id=obs_id,
                source="slack_export",
                channel_id=msg.channel_id,
                thread_id=msg.thread_id,
                timestamp=msg.timestamp,
                sender_entity_id=None,
                text=msg.text,
                metadata={
                    "channel_name": msg.channel_name,
                    "reactions": msg.reactions,
                },
            )

            if not insert_observation(conn, obs):
                skipped += 1
                continue
            inserted += 1

            sender_name = users.get(msg.user_id, msg.user_name)
            sender = extract_sender_entity(msg.user_id, sender_name)
            upsert_entity(conn, sender)
            entity_ids_seen.add(sender.id)

            conn.execute(
                "UPDATE observations SET sender_entity_id = ? WHERE id = ?",
                (sender.id, obs_id),
            )
            conn.commit()

            text_entities = extract_entities_from_text(msg.text)
            for ent in text_entities:
                if ent.type == "person" and ent.name in users:
                    ent.name = users[ent.name]
                elif ent.type == "person":
                    resolved = users.get(ent.aliases[0]) if ent.aliases else None
                    if resolved:
                        ent.name = resolved
                upsert_entity(conn, ent)
                entity_ids_seen.add(ent.id)

        return {
            "messages_inserted": inserted,
            "messages_skipped": skipped,
            "entities_created": len(entity_ids_seen),
            "total_observations": count_observations(conn),
            "total_entities": count_entities(conn),
        }
    finally:
        conn.close()
