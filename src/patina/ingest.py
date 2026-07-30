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
    resolve_entity_id,
    upsert_entity,
)
from patina.models import CalendarEvent, ChatMessage, EmailMessage, Observation
from patina.owner import get_owner_entity_id, get_owner_user_ids, mark_entity_as_owner
from patina.store import connect, get_db_path, init_db, kv_get, kv_set, run_pending_migrations


def _obs_id(source: str, channel_id: str, thread_id: str | None, ts: float) -> str:
    key = f"{source}:{channel_id}:{thread_id or ''}:{ts}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def ingest_from_export(zip_path: Path, *, home: Path | None = None) -> dict:
    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)

    try:
        run_pending_migrations(conn)
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

        owner_id = get_owner_entity_id(conn)
        styles_built = 0
        if owner_id and inserted > 0:
            from patina.style.consolidator import build_all_profiles

            styles_built = build_all_profiles(conn, owner_id)

        return {
            "messages_inserted": inserted,
            "messages_skipped": skipped,
            "entities_created": len(entity_ids_seen),
            "styles_built": styles_built,
            "total_observations": count_observations(conn),
            "total_entities": count_entities(conn),
            "channels_seen": 0,
            "newly_watched": 0,
            "zero_streak": 0,
        }
    finally:
        conn.close()


def _ingest_messages(conn, messages: list[ChatMessage], source: str) -> tuple[int, int, set[str]]:
    inserted = 0
    skipped = 0
    entity_ids_seen: set[str] = set()

    for msg in messages:
        obs_id = _obs_id(source, msg.channel_id, msg.thread_id, msg.timestamp)

        dup = conn.execute(
            "SELECT 1 FROM observations WHERE channel_id = ? AND timestamp = ?",
            (msg.channel_id, msg.timestamp),
        ).fetchone()
        if dup:
            skipped += 1
            continue

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
        existing_id = resolve_entity_id(conn, sender.name, sender.aliases)
        if existing_id:
            sender.id = existing_id
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


def _emails_to_chat_messages(emails: list[EmailMessage]) -> list[ChatMessage]:
    results = []
    for em in emails:
        results.append(
            ChatMessage(
                user_id=em.sender,
                text=em.text,
                timestamp=em.timestamp,
                channel_id=f"email:{em.conversation_id or em.id}",
                thread_id=em.conversation_id,
                user_name=em.sender.split("@")[0] if "@" in em.sender else em.sender,
            )
        )
    return results


def _events_to_chat_messages(events: list[CalendarEvent]) -> list[ChatMessage]:
    results = []
    for ev in events:
        attendee_list = ", ".join(ev.attendees) if ev.attendees else "none"
        text = f"[Meeting: {ev.subject}] Organizer: {ev.organizer}, Attendees: {attendee_list}"
        results.append(
            ChatMessage(
                user_id=ev.organizer,
                text=text,
                timestamp=ev.start,
                channel_id=f"calendar:{ev.id}",
                user_name=ev.organizer,
            )
        )
    return results


def ingest_live(
    *, port, source: str = "live", home: Path | None = None, lookback_days: int = 3
) -> dict:
    from datetime import UTC, datetime, timedelta

    from patina.ports.calendar import CalendarPort
    from patina.ports.chat import ChatPort
    from patina.ports.email import EmailPort

    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)

    try:
        run_pending_migrations(conn)
        since = time.time() - (lookback_days * 86400)
        messages: list[ChatMessage] = []

        if isinstance(port, ChatPort):
            messages.extend(port.list_dm_messages(since))
            messages.extend(port.list_mentions(since))

            if hasattr(port, "list_sent_messages"):
                messages.extend(port.list_sent_messages(since))

            channels_seen = 0
            newly_watched = 0
            if hasattr(port, "list_dms"):
                dm_channels = port.list_dms(include_dormant=True)

                group_dms = [dm for dm in dm_channels if dm.is_group]
                channels_seen = len(group_dms)
                for dm in group_dms:
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO watched_channels"
                        " (channel_id, channel_name, reason, added_at)"
                        " VALUES (?, ?, ?, ?)",
                        (
                            dm.channel_id,
                            dm.channel_id,
                            "auto-detected: user is participant",
                            datetime.now(UTC).isoformat(),
                        ),
                    )
                    newly_watched += cur.rowcount
                conn.commit()

                stale_cutoff = time.time() - (180 * 86400)
                for dm in dm_channels:
                    if dm.last_activity_ts < stale_cutoff:
                        continue
                    messages.extend(port.list_channel_messages(dm.channel_id, since))

            streak = int(kv_get(conn, "discovery_zero_streak") or "0")
            if channels_seen > 0:
                streak = 0
            else:
                streak += 1
            kv_set(conn, "discovery_zero_streak", str(streak))

            watched = conn.execute("SELECT channel_id FROM watched_channels").fetchall()
            for ch in watched:
                messages.extend(port.list_channel_messages(ch["channel_id"], since))

        if isinstance(port, EmailPort):
            emails = port.list_inbox(since)
            messages.extend(_emails_to_chat_messages(emails))

        if isinstance(port, CalendarPort):
            now = datetime.now(UTC)
            start = now - timedelta(days=lookback_days)
            events = port.list_events(start, now)
            messages.extend(_events_to_chat_messages(events))

        messages.sort(key=lambda m: m.timestamp)
        inserted, skipped, entity_ids = _ingest_messages(conn, messages, source)

        zero_streak = int(kv_get(conn, "discovery_zero_streak") or "0")

        return {
            "messages_inserted": inserted,
            "messages_skipped": skipped,
            "entities_created": len(entity_ids),
            "total_observations": count_observations(conn),
            "total_entities": count_entities(conn),
            "channels_seen": channels_seen if isinstance(port, ChatPort) else 0,
            "newly_watched": newly_watched if isinstance(port, ChatPort) else 0,
            "zero_streak": zero_streak,
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
        "channels_seen": 0,
        "newly_watched": 0,
        "zero_streak": 0,
    }

    adapters = _load_adapters(home)
    try:
        for source_name, port in adapters:
            result = ingest_live(
                port=port, source=source_name, home=home, lookback_days=lookback_days
            )
            totals["messages_inserted"] += result["messages_inserted"]
            totals["messages_skipped"] += result["messages_skipped"]
            totals["entities_created"] += result["entities_created"]
            totals["total_observations"] = result["total_observations"]
            totals["total_entities"] = result["total_entities"]
            totals["adapters_run"] += 1
            totals["channels_seen"] += result.get("channels_seen", 0)
            totals["newly_watched"] += result.get("newly_watched", 0)
            totals["zero_streak"] = result.get("zero_streak", 0)
    finally:
        for _, port in adapters:
            if hasattr(port, "close"):
                try:
                    port.close()
                except Exception:
                    pass

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
    adapter_sections = config.get("adapters", {})

    for adapter_cfg in adapter_sections.get("chat", []):
        provider = adapter_cfg.get("provider")
        if provider == "slack":
            token = adapter_cfg.get("token", "")
            if token:
                from patina.adapters.slack_live import SlackLiveAdapter

                adapters.append(("slack_live", SlackLiveAdapter(token)))
        elif provider == "slack_mcp":
            adapters.append(("slack_mcp", _make_mcp_adapter("slack_mcp", adapter_cfg)))

    for adapter_cfg in adapter_sections.get("email", []):
        provider = adapter_cfg.get("provider")
        if provider == "imap":
            from patina.adapters.email_imap import ImapEmailAdapter

            adapters.append(
                (
                    "imap",
                    ImapEmailAdapter(
                        host=adapter_cfg.get("host", ""),
                        port=adapter_cfg.get("port", 993),
                        username=adapter_cfg.get("username", ""),
                        password=adapter_cfg.get("password", ""),
                    ),
                )
            )
        elif provider == "outlook_mcp":
            adapters.append(("outlook_mcp_email", _make_mcp_adapter("outlook_mcp", adapter_cfg)))

    for adapter_cfg in adapter_sections.get("calendar", []):
        provider = adapter_cfg.get("provider")
        if provider == "outlook_mcp":
            adapters.append(("outlook_mcp_calendar", _make_mcp_adapter("outlook_mcp", adapter_cfg)))

    return adapters


def _make_mcp_adapter(provider: str, cfg: dict) -> object:
    from patina.adapters._mcp_client import connect_mcp_sync

    command = cfg.get("command", "")
    if not command:
        raise ValueError(f"MCP adapter '{provider}' requires a 'command' field")

    bridge = connect_mcp_sync(
        command=command,
        args=cfg.get("args"),
        env=cfg.get("env"),
    )

    if provider == "slack_mcp":
        from patina.adapters.slack_mcp import SlackMcpAdapter

        return SlackMcpAdapter(bridge)
    elif provider == "outlook_mcp":
        from patina.adapters.outlook_mcp import OutlookMcpAdapter

        return OutlookMcpAdapter(bridge)
    else:
        bridge.close()
        raise ValueError(f"Unknown MCP provider: {provider}")
