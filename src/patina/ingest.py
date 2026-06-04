from __future__ import annotations

import hashlib
import time
from pathlib import Path

from patina.export_parser import parse_slack_export
from patina.extraction import extract_entities_from_text, extract_sender_entity
from patina.graph import (
    count_entities,
    count_observations,
    insert_observation,
    upsert_entity,
)
from patina.models import ChatMessage, Observation
from patina.owner import get_owner_user_ids, mark_entity_as_owner
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
        owner_ids = set(get_owner_user_ids(home))

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

            if msg.user_id in owner_ids:
                mark_entity_as_owner(conn, sender.id)

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


def _ingest_messages(conn, messages: list[ChatMessage], source: str) -> tuple[int, int, set[str]]:
    inserted = 0
    skipped = 0
    entity_ids_seen: set[str] = set()

    for msg in messages:
        obs_id = _obs_id(source, msg.channel_id, msg.thread_id, msg.timestamp)
        obs = Observation(
            id=obs_id,
            source=source,
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

        sender = extract_sender_entity(msg.user_id, msg.user_name)
        upsert_entity(conn, sender)
        entity_ids_seen.add(sender.id)

        conn.execute(
            "UPDATE observations SET sender_entity_id = ? WHERE id = ?",
            (sender.id, obs_id),
        )
        conn.commit()

        text_entities = extract_entities_from_text(msg.text)
        for ent in text_entities:
            upsert_entity(conn, ent)
            entity_ids_seen.add(ent.id)

    return inserted, skipped, entity_ids_seen


def ingest_live(
    *, port, source: str = "live", home: Path | None = None, lookback_days: int = 3
) -> dict:
    from patina.ports.chat import ChatPort

    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)

    try:
        since = time.time() - (lookback_days * 86400)
        messages: list[ChatMessage] = []

        if isinstance(port, ChatPort):
            messages.extend(port.list_dm_messages(since))
            messages.extend(port.list_mentions(since))

        messages.sort(key=lambda m: m.timestamp)
        inserted, skipped, entity_ids = _ingest_messages(conn, messages, source)

        return {
            "messages_inserted": inserted,
            "messages_skipped": skipped,
            "entities_created": len(entity_ids),
            "total_observations": count_observations(conn),
            "total_entities": count_entities(conn),
        }
    finally:
        conn.close()


def ingest_all(*, home: Path | None = None, lookback_days: int = 3) -> dict:
    totals = {
        "messages_inserted": 0,
        "messages_skipped": 0,
        "entities_created": 0,
        "total_observations": 0,
        "total_entities": 0,
        "adapters_run": 0,
    }

    adapters = _load_adapters(home)
    for source_name, port in adapters:
        result = ingest_live(port=port, source=source_name, home=home, lookback_days=lookback_days)
        totals["messages_inserted"] += result["messages_inserted"]
        totals["messages_skipped"] += result["messages_skipped"]
        totals["entities_created"] += result["entities_created"]
        totals["total_observations"] = result["total_observations"]
        totals["total_entities"] = result["total_entities"]
        totals["adapters_run"] += 1

    return totals


def _load_adapters(home: Path | None = None) -> list[tuple[str, object]]:
    import yaml

    config_path = (home or Path.home() / ".patina") / "config.yaml"
    if not config_path.exists():
        return []

    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        return []

    adapters: list[tuple[str, object]] = []
    chat_adapters = config.get("adapters", {}).get("chat", [])
    for adapter_cfg in chat_adapters:
        provider = adapter_cfg.get("provider")
        if provider == "slack":
            token = adapter_cfg.get("token", "")
            if token:
                from patina.adapters.slack_live import SlackLiveAdapter

                adapters.append(("slack_live", SlackLiveAdapter(token)))

    return adapters
