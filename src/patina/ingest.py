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
from patina.store import connect, get_db_path, init_db, kv_get, kv_set

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

# Every reason ``outlook_relevance`` can drop an email for (``dropped_<reason>`` stats).
RELEVANCE_DROP_REASONS = frozenset({RELEVANCE_BOT_OR_LIST, RELEVANCE_NOT_DIRECT})

# Source-fact key for a sender address resolved by the caller (e.g. from the store)
# when the payload names the sender by display name only.
SENDER_ADDRESS_FACT = "sender_address"


class Relevance(NamedTuple):
    """A keep/drop decision; a dropped ``reason`` maps to the ``dropped_<reason>`` stat."""

    keep: bool
    reason: str


def _identity_keys(value) -> set[str]:
    """Casefolded match keys for a recipient dict or a sender/participant string."""
    from patina.adapters.outlook_mcp import normalize_sender

    raw = [value.get("email"), value.get("name")] if isinstance(value, dict) else [value]
    keys: set[str] = set()
    for v in raw:
        if not isinstance(v, str):
            continue
        for form in (v, normalize_sender(v)):
            form = form.strip().casefold()
            if form:
                keys.add(form)
    return keys


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    return [value] if value else []


def _is_bot_or_list_sender(sender: str) -> bool:
    from patina.maintenance import is_automated_address

    return is_non_person_sender(sender) or ("@" in sender and is_automated_address(sender))


def outlook_sender_address(source_facts: dict) -> str:
    """The sender's email address, or ``""`` when it cannot be resolved.

    In order: ``sender_key`` when it is an address, a caller-resolved
    ``sender_address`` fact, then a To/Cc recipient dict with the sender's
    normalized display name. Live ``email_inbox`` items name the sender by
    display name only and carry no recipient dicts, so for them the address
    has to come from the store (see ``_resolve_sender_addresses``).
    """
    sender = str(source_facts.get("sender_key") or "").strip()
    if "@" in sender:
        return sender
    resolved = source_facts.get(SENDER_ADDRESS_FACT)
    if isinstance(resolved, str) and "@" in resolved:
        return resolved.strip()
    sender_keys = _identity_keys(sender)
    if not sender_keys:
        return ""
    for r in [*_as_list(source_facts.get("to")), *_as_list(source_facts.get("cc"))]:
        if not isinstance(r, dict):
            continue
        email = r.get("email")
        if isinstance(email, str) and "@" in email and sender_keys & _identity_keys(r.get("name")):
            return email.strip()
    return ""


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
    ``recipients``, ``sender_key``, ``item_class``), optionally with a
    caller-resolved ``sender_address``; ``thread_participants`` are the
    thread's senders. Owner identifiers come from ``get_owner_identifiers``
    unless given, and are matched case-insensitively. Objective participants
    are matched on the same normalized forms as thread identities, so
    ``"Müller, Avery (Contractor)"`` matches ``"Müller, Avery"``.

    - ``bot_or_list`` (drop): the sender is a no-reply, notification, mailer or
      list address. Checked first, so it wins over every keep rule.
    - ``direct`` (keep): the Owner is a named To recipient (not reached through a
      distribution list), is named in ``recipients``, or sent/replied in the
      thread.

      Live ``email_inbox`` items send no ``toRecipients``/``ccRecipients``, only
      ``recipients``: display names with no To/Cc split and no list flag. Any
      Owner match in ``recipients`` counts as direct, so an Owner on Cc is kept
      too (no per-message re-fetch for the real To/Cc). Mail that reached the
      Owner only through a list names the list, not the Owner, so it still
      does not match.
    - ``engagement`` (keep): an active objective's participant is on the thread,
      or the domain of the sender's address (``outlook_sender_address``) is one
      of its customer domains. Inactive objectives are ignored.
    - ``not_direct`` (drop): none of the above. A ``subject`` keyword match is
      never a keep signal on its own. When the sender's address could not be
      resolved, the customer-domain rule could not run; ingest stats count
      those drops as ``sender_unresolved``.

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
    recipients = _as_list(source_facts.get("recipients"))
    named = [
        r for r in [*to, *recipients] if not (isinstance(r, dict) and r.get("isDistributionList"))
    ]
    thread_people = [sender, *thread_participants]

    if owner_keys and any(owner_keys & _identity_keys(v) for v in [*named, *thread_people]):
        return Relevance(True, RELEVANCE_DIRECT)

    sender_address = outlook_sender_address(source_facts)
    on_thread: set[str] = set()
    for v in [*thread_people, sender_address, *to, *cc, *recipients]:
        on_thread |= _identity_keys(v)
    sender_domain = sender_address.rsplit("@", 1)[1].casefold() if sender_address else ""

    for obj in objectives:
        if not obj.active:
            continue
        participants: set[str] = set()
        for p in obj.participants:
            participants |= _identity_keys(p)
        domains = {d.strip().casefold() for d in obj.customer_domains}
        if on_thread & participants or (sender_domain and sender_domain in domains):
            return Relevance(True, RELEVANCE_ENGAGEMENT)

    return Relevance(False, RELEVANCE_NOT_DIRECT)


DROPPED_PREFIX = "dropped_"


def relevance_stat_key(relevance: Relevance) -> str:
    """Stats key for a decision: the keep reason, or ``dropped_<reason>``."""
    return relevance.reason if relevance.keep else f"{DROPPED_PREFIX}{relevance.reason}"


def _outlook_filter_enabled(home: Path | None = None) -> bool:
    """True when ``ingest.outlook_relevance_filter`` is set in config.yaml (off by default)."""
    import yaml

    from patina.store import DEFAULT_HOME

    config_path = (home or DEFAULT_HOME) / "config.yaml"
    if not config_path.exists():
        return False
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        return False
    return bool((config.get("ingest") or {}).get("outlook_relevance_filter", False))


def _active_objectives(conn) -> list[Objective]:
    from patina.priority.objectives import _row_to_objective

    rows = conn.execute("SELECT * FROM objectives WHERE active = 1").fetchall()
    return [_row_to_objective(r) for r in rows]


def _resolve_sender_addresses(conn, emails: list[EmailMessage]) -> dict[str, str]:
    """Map each display-name ``sender_key`` to its sender entity's email alias.

    Read-only. Senders that match no single entity, or whose entity holds no
    email alias, are left out.
    """
    import json

    from patina.adapters.outlook_mcp import normalize_sender
    from patina.graph import resolve_entity_id
    from patina.owner import normalize_alias

    resolved: dict[str, str] = {}
    looked_up: set[str] = set()
    for em in emails:
        sender_key = str(em.source_facts.get("sender_key") or "").strip()
        if not sender_key or "@" in sender_key or sender_key in looked_up:
            continue
        looked_up.add(sender_key)
        name = normalize_sender(sender_key)
        entity_id = resolve_entity_id(conn, name) if name else None
        if entity_id is None:
            continue
        row = conn.execute("SELECT aliases FROM entities WHERE id = ?", (entity_id,)).fetchone()
        for alias in json.loads(row["aliases"] or "[]") if row else []:
            address = normalize_alias(alias).strip() if isinstance(alias, str) else ""
            if "@" in address:
                resolved[sender_key] = address
                break
    return resolved


def _apply_outlook_relevance(
    emails: list[EmailMessage],
    *,
    objectives: list[Objective],
    counts: dict[str, int],
    home: Path | None = None,
    conn=None,
) -> tuple[list[EmailMessage], int]:
    """Return the kept emails and the ``sender_unresolved`` count.

    Every decision is counted in ``counts`` by stats key. With ``conn``, a
    display-name sender's address is looked up in the store and passed to
    ``outlook_relevance`` as ``sender_address`` (the stored source facts are
    not changed). A ``not_direct`` drop whose sender address is still unknown
    counts as ``sender_unresolved``.
    """
    owner_identifiers = get_owner_identifiers(home)
    addresses = _resolve_sender_addresses(conn, emails) if conn is not None else {}
    kept = []
    unresolved = 0
    for em in emails:
        facts = em.source_facts
        address = addresses.get(str(facts.get("sender_key") or "").strip())
        if address:
            facts = {**facts, SENDER_ADDRESS_FACT: address}
        relevance = outlook_relevance(
            facts,
            objectives=objectives,
            thread_participants=em.thread_participants,
            subject=em.subject,
            owner_identifiers=owner_identifiers,
        )
        key = relevance_stat_key(relevance)
        counts[key] = counts.get(key, 0) + 1
        if relevance.keep:
            kept.append(em)
        elif relevance.reason == RELEVANCE_NOT_DIRECT and not outlook_sender_address(facts):
            unresolved += 1
    return kept, unresolved


def _outlook_relevance_dry_run(
    port,
    source: str,
    *,
    home: Path | None = None,
    lookback_days: int = 3,
    seen: set[tuple[str, str]] | None = None,
) -> dict:
    """Run the Outlook keep/drop decisions and count them; nothing is written.

    The store is only opened read-only (for active objectives), and not at
    all when it does not exist yet. ``seen`` holds ``(source family, email id)``
    keys already counted by an earlier adapter; matching emails are skipped and
    new ones added, so an inbox listed by two adapters is counted once.
    The read-only store also resolves display-name senders to addresses;
    ``not_direct`` drops whose sender stays unresolved are counted in
    ``sender_unresolved``.
    """
    from patina.ports.email import EmailPort
    from patina.store import connect_readonly

    relevance: dict[str, int] = {}
    unresolved = 0
    family = _source_family(source)
    if isinstance(port, EmailPort) and family == "outlook":
        emails = port.list_inbox(time.time() - (lookback_days * 86400))
        if seen is not None:
            fresh = []
            for em in emails:
                if em.id and (family, em.id) in seen:
                    continue
                if em.id:
                    seen.add((family, em.id))
                fresh.append(em)
            emails = fresh
        db_path = get_db_path(home)
        if db_path.exists():
            conn = connect_readonly(db_path)
            try:
                _, unresolved = _apply_outlook_relevance(
                    emails,
                    objectives=_active_objectives(conn),
                    counts=relevance,
                    home=home,
                    conn=conn,
                )
            finally:
                conn.close()
        else:
            _, unresolved = _apply_outlook_relevance(
                emails, objectives=[], counts=relevance, home=home
            )
    return {"relevance": relevance, "sender_unresolved": unresolved}


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
    *,
    port,
    source: str = "live",
    home: Path | None = None,
    lookback_days: int = 3,
    dry_run: bool = False,
) -> dict:
    """Ingest from one live adapter.

    With ``ingest.outlook_relevance_filter`` enabled, Outlook emails go through
    ``outlook_relevance`` before they become observations; dropped emails create
    no observation or entity, and every decision is counted in ``relevance``.
    ``dry_run`` only runs and counts those decisions, writing nothing.
    """
    from datetime import UTC, datetime, timedelta

    from patina.ports.calendar import CalendarPort
    from patina.ports.chat import ChatPort
    from patina.ports.email import EmailPort

    if dry_run:
        return _outlook_relevance_dry_run(port, source, home=home, lookback_days=lookback_days)

    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)

    try:
        since = time.time() - (lookback_days * 86400)
        messages: list[ChatMessage] = []
        skip_reasons: dict[str, int] = {}
        relevance: dict[str, int] = {}
        sender_unresolved = 0

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
            if _source_family(source) == "outlook" and _outlook_filter_enabled(home):
                emails, sender_unresolved = _apply_outlook_relevance(
                    emails,
                    objectives=_active_objectives(conn),
                    counts=relevance,
                    home=home,
                    conn=conn,
                )
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
            "relevance": relevance,
            "sender_unresolved": sender_unresolved,
        }
    finally:
        conn.close()


def _add_counts(totals: dict[str, int], counts: dict[str, int]) -> None:
    for key, count in counts.items():
        totals[key] = totals.get(key, 0) + count


def ingest_all(*, home: Path | None = None, lookback_days: int = 3, dry_run: bool = False) -> dict:
    if dry_run:
        return _dry_run_all(home=home, lookback_days=lookback_days)

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
        "relevance": {},
        "sender_unresolved": 0,
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
            _add_counts(totals["skip_reasons"], result.get("skip_reasons", {}))
            _add_counts(totals["relevance"], result.get("relevance", {}))
            totals["sender_unresolved"] += result.get("sender_unresolved", 0)
    finally:
        _close_adapters(adapters)

    return totals


def _dry_run_all(*, home: Path | None = None, lookback_days: int = 3) -> dict:
    """Count Outlook keep/drop decisions across configured adapters; writes nothing.

    The Outlook email and calendar adapters are both ``outlook_mcp`` EmailPorts
    over the same inbox, so each email is counted once across adapters.
    """
    totals = {"adapters_run": 0, "relevance": {}, "sender_unresolved": 0}
    seen: set[tuple[str, str]] = set()
    adapters = _load_adapters(home)
    try:
        for source_name, port in adapters:
            result = _outlook_relevance_dry_run(
                port, source_name, home=home, lookback_days=lookback_days, seen=seen
            )
            totals["adapters_run"] += 1
            _add_counts(totals["relevance"], result["relevance"])
            totals["sender_unresolved"] += result["sender_unresolved"]
    finally:
        _close_adapters(adapters)

    return totals


def _close_adapters(adapters: list[tuple[str, object]]) -> None:
    for _, port in adapters:
        if hasattr(port, "close"):
            try:
                port.close()
            except Exception:
                pass


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
