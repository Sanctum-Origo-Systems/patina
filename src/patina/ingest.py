from __future__ import annotations

import hashlib
import time
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from patina.decisions import auto_resolve_draft_reply
from patina.export_parser import parse_slack_export
from patina.extraction import (
    extract_entities_from_text,
    extract_sender_entity,
    is_non_person_sender,
)
from patina.graph import (
    count_entities,
    count_observations,
    insert_observation,
    upsert_entity,
)
from patina.models import CalendarEvent, ChatMessage, EmailMessage, Observation
from patina.owner import (
    get_owner_entity_id,
    get_owner_identifiers,
    get_owner_user_ids,
    is_owner_entity,
    mark_entity_as_owner,
    owner_match_keys,
)
from patina.store import connect, get_db_path, init_db, kv_get, kv_set, run_pending_migrations

if TYPE_CHECKING:
    from patina.priority.objectives import Objective


def _source_family(source: str) -> str:
    if "slack" in source:
        return "slack"
    if "outlook" in source:
        return "outlook"
    return source


def _obs_id(source: str, channel_id: str, thread_id: str | None, ts: float) -> str:
    family = _source_family(source)
    if family == "slack":
        key = f"slack:{ts}"
    else:
        key = f"{family}:{channel_id or ''}:{thread_id or ''}:{ts}"
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
        non_person_skipped = 0
        entity_ids_seen: set[str] = set()
        family = _source_family("slack_export")

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
            if is_non_person_sender(msg.user_id, sender_name):
                non_person_skipped += 1
            else:
                sender = extract_sender_entity(msg.user_id, sender_name, conn=conn)
                upsert_entity(conn, sender, adapter=family, observation_id=obs_id)
                entity_ids_seen.add(sender.id)

                if msg.user_id in owner_ids:
                    mark_entity_as_owner(conn, sender.id)

                conn.execute(
                    "UPDATE observations SET sender_entity_id = ? WHERE id = ?",
                    (sender.id, obs_id),
                )
                conn.commit()

            text_entities = extract_entities_from_text(msg.text)
            owner_entity_id_export = get_owner_entity_id(conn)
            for ent in text_entities:
                if ent.type == "person" and owner_entity_id_export:
                    mention_tokens = {ent.name} | set(ent.aliases or [])
                    if owner_ids & mention_tokens:
                        entity_ids_seen.add(owner_entity_id_export)
                        continue
                if ent.type == "person" and ent.name in users:
                    ent.name = users[ent.name]
                elif ent.type == "person":
                    resolved = users.get(ent.aliases[0]) if ent.aliases else None
                    if resolved:
                        ent.name = resolved
                upsert_entity(conn, ent, adapter=family, observation_id=obs_id)
                entity_ids_seen.add(ent.id)

        owner_id = get_owner_entity_id(conn)
        styles_built = 0
        if owner_id and inserted > 0:
            from patina.style.consolidator import build_all_profiles

            styles_built = build_all_profiles(conn, owner_id)

        return {
            "messages_inserted": inserted,
            "messages_skipped": skipped,
            "non_person_skipped": non_person_skipped,
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


def _ingest_messages(
    conn,
    messages: list[ChatMessage],
    source: str,
    *,
    home: Path | None = None,
) -> tuple[int, int, int, set[str]]:
    inserted = 0
    skipped = 0
    non_person_skipped = 0
    entity_ids_seen: set[str] = set()
    family = _source_family(source)

    owner_identifiers = get_owner_identifiers(home)
    owner_entity_id = get_owner_entity_id(conn)

    for msg in messages:
        obs_id = _obs_id(source, msg.channel_id, msg.thread_id, msg.timestamp)

        meta = {
            "channel_name": msg.channel_name,
            "reactions": msg.reactions,
        }
        if msg.sender_dn:
            meta["sender_dn"] = msg.sender_dn
        if msg.sender_slack_id:
            meta["sender_slack_id"] = msg.sender_slack_id
        elif family == "slack" and msg.user_id:
            meta["sender_slack_id"] = msg.user_id
        if msg.organizer_dn:
            meta["organizer_dn"] = msg.organizer_dn
        if msg.source_facts:
            meta["source"] = dict(msg.source_facts)

        obs = Observation(
            id=obs_id,
            source=source,
            channel_id=msg.channel_id,
            thread_id=msg.thread_id,
            timestamp=msg.timestamp,
            sender_entity_id=None,
            text=msg.text,
            metadata=meta,
        )

        if not insert_observation(conn, obs):
            skipped += 1
            continue
        inserted += 1

        if is_non_person_sender(msg.user_id, msg.user_name):
            non_person_skipped += 1

        sender_tokens = {msg.user_id}
        if msg.user_name:
            sender_tokens.add(msg.user_name)
        is_owner_match = bool(owner_identifiers & sender_tokens)

        if is_owner_match and owner_entity_id:
            sender_id = owner_entity_id
        else:
            sender = extract_sender_entity(
                msg.user_id, msg.user_name, source_family=family, conn=conn
            )
            upsert_entity(conn, sender, adapter=family, observation_id=obs_id)
            sender_id = sender.id

            if is_owner_match:
                mark_entity_as_owner(conn, sender_id)
                owner_entity_id = sender_id

        entity_ids_seen.add(sender_id)

        conn.execute(
            "UPDATE observations SET sender_entity_id = ? WHERE id = ?",
            (sender_id, obs_id),
        )
        conn.commit()

        if is_owner_entity(conn, sender_id):
            auto_resolve_draft_reply(conn, msg.channel_id, msg.text)

        text_entities = extract_entities_from_text(msg.text)
        for ent in text_entities:
            if ent.type == "person" and owner_entity_id:
                mention_tokens = {ent.name} | set(ent.aliases or [])
                if owner_identifiers & mention_tokens:
                    entity_ids_seen.add(owner_entity_id)
                    continue
            upsert_entity(conn, ent, adapter=family, observation_id=obs_id)
            entity_ids_seen.add(ent.id)

    return inserted, skipped, non_person_skipped, entity_ids_seen


MISSING_TIMESTAMP = "missing_timestamp"


def _emails_to_chat_messages(
    emails: list[EmailMessage], skip_reasons: dict[str, int] | None = None
) -> list[ChatMessage]:
    """Convert emails to chat messages, dropping any without a received time.

    Undated emails are never stored (no ``timestamp = 0.0`` rows); each one
    is counted under ``skip_reasons["missing_timestamp"]`` when given.
    """
    results = []
    for em in emails:
        if not em.timestamp:
            if skip_reasons is not None:
                skip_reasons[MISSING_TIMESTAMP] = skip_reasons.get(MISSING_TIMESTAMP, 0) + 1
            continue
        if em.sender_name:
            user_name = em.sender_name
        elif "@" not in em.sender:
            user_name = em.sender
        else:
            user_name = None
        results.append(
            ChatMessage(
                user_id=em.sender,
                text=em.text,
                timestamp=em.timestamp,
                channel_id=f"email:{em.conversation_id or em.id}",
                thread_id=em.conversation_id,
                user_name=user_name,
                sender_dn=em.sender_dn,
                source_facts=em.source_facts,
            )
        )
    return results


RELEVANCE_DIRECT = "direct"
RELEVANCE_ENGAGEMENT = "engagement"
RELEVANCE_BOT_OR_LIST = "bot_or_list"
RELEVANCE_NOT_DIRECT = "not_direct"


class Relevance(NamedTuple):
    """A keep/drop decision; a dropped ``reason`` maps to the ``dropped_<reason>`` stat."""

    keep: bool
    reason: str


def _identity_keys(value) -> set[str]:
    """Casefolded match keys for a recipient dict or a sender/participant string."""
    from patina.adapters.outlook_mcp import _normalize_sender

    raw = [value.get("email"), value.get("name")] if isinstance(value, dict) else [value]
    keys: set[str] = set()
    for v in raw:
        if not isinstance(v, str):
            continue
        for form in (v, _normalize_sender(v)):
            form = form.strip().casefold()
            if form:
                keys.add(form)
    return keys


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    return [value] if value else []


def _is_bot_or_list_sender(sender: str) -> bool:
    from patina.maintenance import _is_automated_address

    return is_non_person_sender(sender) or ("@" in sender and _is_automated_address(sender))


def outlook_relevance(
    source_facts: dict,
    *,
    objectives: Iterable[Objective] = (),
    thread_participants: Iterable[str] = (),
    subject: str = "",
    owner_identifiers: set[str] | None = None,
    home: Path | None = None,
) -> Relevance:
    """Decide deterministically whether an Outlook email is relevant enough to keep.

    ``source_facts`` is the email's ``metadata["source"]`` dict (``to``, ``cc``,
    ``sender_key``, ``item_class``); ``thread_participants`` are the thread's
    senders. Owner identifiers come from ``get_owner_identifiers`` unless given,
    and are matched case-insensitively.

    - ``bot_or_list`` (drop): the sender is a no-reply, notification, mailer or
      list address. Checked first, so it wins over every keep rule.
    - ``direct`` (keep): the Owner is a named To recipient (not reached through a
      distribution list) or sent/replied in the thread.
    - ``engagement`` (keep): an active objective's participant is on the thread,
      or the sender's domain is one of its customer domains. Inactive objectives
      are ignored.
    - ``not_direct`` (drop): none of the above. A ``subject`` keyword match is
      never a keep signal on its own.

    Pure: reads the config only, writes nothing.
    """
    sender = str(source_facts.get("sender_key") or "").strip()
    if sender and _is_bot_or_list_sender(sender):
        return Relevance(False, RELEVANCE_BOT_OR_LIST)

    if owner_identifiers is None:
        owner_identifiers = get_owner_identifiers(home)
    owner_keys = owner_match_keys(owner_identifiers)

    to = _as_list(source_facts.get("to"))
    cc = _as_list(source_facts.get("cc"))
    named_to = [r for r in to if not (isinstance(r, dict) and r.get("isDistributionList"))]
    thread_people = [sender, *thread_participants]

    if owner_keys and any(owner_keys & _identity_keys(v) for v in [*named_to, *thread_people]):
        return Relevance(True, RELEVANCE_DIRECT)

    on_thread: set[str] = set()
    for v in [*thread_people, *to, *cc]:
        on_thread |= _identity_keys(v)
    sender_domain = sender.rsplit("@", 1)[1].casefold() if "@" in sender else ""

    for obj in objectives:
        if not obj.active:
            continue
        participants = {p.strip().casefold() for p in obj.participants}
        domains = {d.strip().casefold() for d in obj.customer_domains}
        if on_thread & participants or (sender_domain and sender_domain in domains):
            return Relevance(True, RELEVANCE_ENGAGEMENT)

    return Relevance(False, RELEVANCE_NOT_DIRECT)


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
                organizer_dn=ev.organizer_dn or ev.organizer or None,
                source_facts=ev.source_facts,
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
        skip_reasons: dict[str, int] = {}

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
            messages.extend(_emails_to_chat_messages(emails, skip_reasons))

        if isinstance(port, CalendarPort):
            now = datetime.now(UTC)
            start = now - timedelta(days=lookback_days)
            events = port.list_events(start, now)
            messages.extend(_events_to_chat_messages(events))

        messages.sort(key=lambda m: m.timestamp)
        inserted, skipped, non_person_skipped, entity_ids = _ingest_messages(
            conn, messages, source, home=home
        )

        zero_streak = int(kv_get(conn, "discovery_zero_streak") or "0")

        return {
            "messages_inserted": inserted,
            "messages_skipped": skipped,
            "non_person_skipped": non_person_skipped,
            "entities_created": len(entity_ids),
            "total_observations": count_observations(conn),
            "total_entities": count_entities(conn),
            "channels_seen": channels_seen if isinstance(port, ChatPort) else 0,
            "newly_watched": newly_watched if isinstance(port, ChatPort) else 0,
            "zero_streak": zero_streak,
            "skip_reasons": skip_reasons,
        }
    finally:
        conn.close()


def ingest_all(*, home: Path | None = None, lookback_days: int = 3) -> dict:
    totals = {
        "messages_inserted": 0,
        "messages_skipped": 0,
        "non_person_skipped": 0,
        "entities_created": 0,
        "total_observations": 0,
        "total_entities": 0,
        "adapters_run": 0,
        "channels_seen": 0,
        "newly_watched": 0,
        "zero_streak": 0,
        "skip_reasons": {},
    }

    adapters = _load_adapters(home)
    try:
        for source_name, port in adapters:
            result = ingest_live(
                port=port, source=source_name, home=home, lookback_days=lookback_days
            )
            totals["messages_inserted"] += result["messages_inserted"]
            totals["messages_skipped"] += result["messages_skipped"]
            totals["non_person_skipped"] += result.get("non_person_skipped", 0)
            totals["entities_created"] += result["entities_created"]
            totals["total_observations"] = result["total_observations"]
            totals["total_entities"] = result["total_entities"]
            totals["adapters_run"] += 1
            totals["channels_seen"] += result.get("channels_seen", 0)
            totals["newly_watched"] += result.get("newly_watched", 0)
            totals["zero_streak"] = result.get("zero_streak", 0)
            for reason, count in result.get("skip_reasons", {}).items():
                totals["skip_reasons"][reason] = totals["skip_reasons"].get(reason, 0) + count
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
