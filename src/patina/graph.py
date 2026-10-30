from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable

from patina.models import Claim, Entity, Observation, Relationship
from patina.owner import normalize_alias
from patina.store import record_alias_provenance

_SLACK_ID_PAT = re.compile(r"^[UW](?=[A-Z0-9]*\d)[A-Z0-9]{8,10}$")
_DN_CN_PAT = re.compile(r"(^|/)CN=")

# --- Identity contract (#444/#447/#511) ---
# Identifier types, strongest first. This is the single source of truth for
# which identifier wins when resolving, deduplicating or splitting entities;
# see docs/features/identity-precedence.md.
IDENTIFIER_PRECEDENCE: tuple[str, ...] = (
    "slack_id",
    "dn",
    "email",
    "handle",
    "display_name",
)

# Machine identifiers that carry no human-readable label.
_OPAQUE_IDENTIFIERS = frozenset({"slack_id", "dn"})

# Display-label preference (lower is better), derived from the precedence:
# readable identifiers in reverse (a full name reads better than a handle or an
# email), then opaque machine IDs strongest first.
_DISPLAY_ORDER: tuple[str, ...] = tuple(
    t for t in reversed(IDENTIFIER_PRECEDENCE) if t not in _OPAQUE_IDENTIFIERS
) + tuple(t for t in IDENTIFIER_PRECEDENCE if t in _OPAQUE_IDENTIFIERS)


def identifier_type(
    name: str,
    *,
    is_display_name: Callable[[str], bool] | None = None,
) -> str | None:
    """Classify *name* as an IDENTIFIER_PRECEDENCE type.

    Returns None for a truncated DN (``/O=`` without ``CN=``), which is never
    an identifier. *is_display_name* can veto the display-name type for
    spaced tokens; vetoed tokens fall through to email or handle.
    """
    upper = name.upper()
    if upper.startswith("/O="):
        return "dn" if _DN_CN_PAT.search(upper) else None
    if "CN=" in upper:
        return "dn"
    if " " in name and (is_display_name is None or is_display_name(name)):
        return "display_name"
    if "@" in name:
        return "email"
    if _SLACK_ID_PAT.match(name):
        return "slack_id"
    return "handle"


def identifier_rank(name: str) -> int:
    """Precedence rank of *name* (0 = strongest); non-identifiers rank last."""
    kind = identifier_type(name)
    if kind is None:
        return len(IDENTIFIER_PRECEDENCE)
    return IDENTIFIER_PRECEDENCE.index(kind)


def _name_type_rank(
    name: str,
    *,
    is_display_name: Callable[[str], bool] | None = None,
) -> int:
    """Display-label rank: full name (0) > handle (1) > email (2) > Slack ID (3) > DN (4).

    A truncated DN is not an identifier, so it never outranks one: it shares
    the last slot with the full DN.
    """
    kind = identifier_type(name, is_display_name=is_display_name)
    if kind is None:
        return len(_DISPLAY_ORDER) - 1
    return _DISPLAY_ORDER.index(kind)


_SLACK_ID_EXTRACT_PAT = re.compile(r"^(?:slack:)?([UW][A-Z0-9]{4,})$", re.IGNORECASE)


def _is_multi_identity(name: str, aliases: list[str]) -> bool:
    """True when tokens contain >1 distinct Slack ID or DN — a known sink."""
    slack_ids: set[str] = set()
    dns: set[str] = set()
    for token in [name] + aliases:
        t = token.strip()
        upper = t.upper()
        m = _SLACK_ID_EXTRACT_PAT.match(t)
        if m and _SLACK_ID_PAT.match(m.group(1).upper()):
            slack_ids.add(m.group(1).upper())
        elif upper.startswith("/O=") or "CN=" in upper:
            dns.add(upper)
    return len(slack_ids) > 1 or len(dns) > 1


def _sole_single_identity_holder(matches: set[str], multi_matches: set[str]) -> str | None:
    """Pick the one alias holder that is not a multi-identity sink.

    A sink never owns a handle (#547, #553). Resolve only when exactly one
    single-identity holder remains, alongside at most one sink (#502 tiebreak).
    """
    candidates = matches - multi_matches
    if len(candidates) == 1 and len(multi_matches) <= 1:
        return next(iter(candidates))
    return None


def normalize_name(name: str) -> str:
    name = name.strip().lstrip("@")
    if "@" in name:
        name = name.split("@")[0]
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2:
            name = f"{parts[1]} {parts[0]}"
    return name.lower().strip()


def resolve_entity_id(
    conn: sqlite3.Connection,
    name: str,
    aliases: list[str] | None = None,
) -> str | None:
    if not name or not name.strip():
        return None

    if identifier_type(name.strip()) is None:
        return None

    non_owner_rows = None

    # --- Phase 1: Exact name match (ambiguity-safe) ---
    rows = conn.execute(
        "SELECT id FROM entities WHERE name = ? AND is_owner = 0",
        (name,),
    ).fetchall()

    # --- Phase 2: Slack ID priority lookup (ambiguity-safe) ---
    if aliases:
        incoming_slack_ids = set()
        for alias in aliases:
            if not alias:
                continue
            stripped = normalize_alias(alias)
            if identifier_type(stripped) == "slack_id":
                incoming_slack_ids.add(stripped)

        if incoming_slack_ids:
            non_owner_rows = conn.execute(
                "SELECT id, name, aliases FROM entities WHERE is_owner = 0"
            ).fetchall()

            all_holders: dict[str, list[sqlite3.Row]] = {}
            for slack_id in incoming_slack_ids:
                holders: list[sqlite3.Row] = []
                for r in non_owner_rows:
                    for stored_alias in json.loads(r["aliases"] or "[]"):
                        if normalize_alias(stored_alias) == slack_id:
                            holders.append(r)
                            break
                if holders:
                    all_holders[slack_id] = holders

            if all_holders:
                all_entity_ids = set()
                for holders in all_holders.values():
                    for r in holders:
                        all_entity_ids.add(r["id"])

                if len(all_entity_ids) == 1:
                    return all_entity_ids.pop()

                for slack_id, holders in all_holders.items():
                    holder_ids = {r["id"] for r in holders}
                    if len(holder_ids) > 1:
                        clean: list[sqlite3.Row] = []
                        for r in holders:
                            bare_slack_ids = set()
                            for sa in json.loads(r["aliases"] or "[]"):
                                bare = normalize_alias(sa)
                                if identifier_type(bare) == "slack_id":
                                    bare_slack_ids.add(bare)
                            if len(bare_slack_ids) == 1:
                                clean.append(r)
                        if len(clean) == 1:
                            return clean[0]["id"]
                        return None

    # --- Phase 3: Exact name match ambiguity check ---
    name_clean = normalize_alias(name)
    normalized = normalize_name(name_clean)

    if len(rows) == 1:
        if not (normalized and len(normalized) > 2):
            return rows[0]["id"]
        if non_owner_rows is None:
            non_owner_rows = conn.execute(
                "SELECT id, name, aliases FROM entities WHERE is_owner = 0"
            ).fetchall()
        norm_count = sum(1 for r in non_owner_rows if normalize_name(r["name"]) == normalized)
        if norm_count <= 1:
            return rows[0]["id"]

    # --- Phase 4: Normalized name / alias match (ambiguity-safe) ---
    if normalized and len(normalized) > 2:
        if non_owner_rows is None:
            non_owner_rows = conn.execute(
                "SELECT id, name, aliases FROM entities WHERE is_owner = 0"
            ).fetchall()

        name_matches: set[str] = set()
        for r in non_owner_rows:
            if normalize_name(r["name"]) == normalized:
                name_matches.add(r["id"])
        if len(name_matches) == 1:
            return name_matches.pop()

        if not name_matches:
            alias_matches: set[str] = set()
            multi_matches: set[str] = set()
            for r in non_owner_rows:
                r_aliases = json.loads(r["aliases"] or "[]")
                for alias in r_aliases:
                    clean = normalize_alias(alias)
                    if normalize_name(clean) == normalized:
                        alias_matches.add(r["id"])
                        if _is_multi_identity(r["name"], r_aliases):
                            multi_matches.add(r["id"])
                        break
            holder = _sole_single_identity_holder(alias_matches, multi_matches)
            if holder is not None:
                return holder

    # --- Phase 5: Provided non-Slack-ID aliases, in IDENTIFIER_PRECEDENCE order ---
    if aliases:
        if non_owner_rows is None:
            non_owner_rows = conn.execute(
                "SELECT id, name, aliases FROM entities WHERE is_owner = 0"
            ).fetchall()
        ranked: list[tuple[int, str]] = []
        for alias in aliases:
            if not alias:
                continue
            stripped = normalize_alias(alias)
            kind = identifier_type(stripped)
            # Slack IDs were handled in phase 2; truncated DNs are not identifiers.
            if kind is None or kind == "slack_id":
                continue
            ranked.append((IDENTIFIER_PRECEDENCE.index(kind), stripped))
        ranked.sort(key=lambda item: item[0])
        for rank, stripped in ranked:
            # Only handles get the sink guard; a sink's DNs and absorbed emails
            # still resolve to it until split_dn_sink routes them (#485).
            is_handle = IDENTIFIER_PRECEDENCE[rank] == "handle"
            matches: set[str] = set()
            multi_matches_2: set[str] = set()
            for r in non_owner_rows:
                r_aliases = json.loads(r["aliases"] or "[]")
                for stored_alias in r_aliases:
                    if normalize_alias(stored_alias) == stripped:
                        matches.add(r["id"])
                        if is_handle and _is_multi_identity(r["name"], r_aliases):
                            multi_matches_2.add(r["id"])
                        break
            holder = _sole_single_identity_holder(matches, multi_matches_2)
            if holder is not None:
                return holder
            if matches:
                continue
            norm_alias = normalize_name(stripped)
            if norm_alias and len(norm_alias) > 2:
                name_matches_2: set[str] = set()
                for r in non_owner_rows:
                    if normalize_name(r["name"]) == norm_alias:
                        name_matches_2.add(r["id"])
                if len(name_matches_2) == 1:
                    return name_matches_2.pop()

    return None


def _strip_foreign_slack_ids(
    conn: sqlite3.Connection,
    aliases: list[str],
    target_id: str,
) -> list[str]:
    """Remove Slack ID aliases already held by a different entity."""
    result = []
    for alias in aliases:
        stripped = normalize_alias(alias)
        if not _SLACK_ID_PAT.match(stripped):
            result.append(alias)
            continue
        row = conn.execute(
            "SELECT id FROM entities WHERE id != ? AND is_owner = 0"
            " AND (aliases LIKE ? OR aliases LIKE ?)",
            (target_id, f'%"{stripped}"%', f'%"slack:{stripped}"%'),
        ).fetchone()
        if row is None:
            result.append(alias)
    return result


def record_added_aliases(
    conn: sqlite3.Connection,
    entity_id: str,
    before: list[str],
    after: list[str],
    *,
    adapter: str | None,
    observation_id: str | None,
) -> None:
    """Record an 'added' provenance row for each alias in after but not in before.

    Writes nothing when adapter is None, since the alias source is unknown.
    Does not commit; the caller owns the transaction.
    """
    if adapter is None:
        return
    present = set(before)
    for alias in dict.fromkeys(after):
        if alias in present:
            continue
        record_alias_provenance(
            conn,
            entity_id,
            alias,
            adapter=adapter,
            action="added",
            observation_id=observation_id,
        )


_STRONG_IDENTIFIERS = frozenset({"slack_id", "dn", "email"})


def _strong_identifiers(tokens: list[str]) -> set[str]:
    """Slack IDs, DNs and emails among *tokens*, prefix-stripped."""
    result: set[str] = set()
    for token in tokens:
        if not token:
            continue
        stripped = normalize_alias(token)
        if identifier_type(stripped) in _STRONG_IDENTIFIERS:
            result.add(stripped)
    return result


def _ingest_merge_allowed(
    conn: sqlite3.Connection,
    keep_id: str,
    drop: sqlite3.Row,
    incoming_aliases: list[str],
) -> bool:
    """True when ingest may fold the stored *drop* entity into *keep_id* (#555).

    Only an ID match qualifies: *keep_id* must hold an incoming Slack ID, DN or
    email that *drop* does not. The merge is refused when the two together
    would hold more than one Slack ID or DN, so a sink is never merged away and
    no person gains a sink's identities.
    """
    keep = conn.execute("SELECT name, aliases FROM entities WHERE id = ?", (keep_id,)).fetchone()
    keep_tokens = [keep["name"], *json.loads(keep["aliases"] or "[]")]
    drop_tokens = [drop["name"], *json.loads(drop["aliases"] or "[]")]
    incoming = _strong_identifiers(incoming_aliases)
    if not (incoming & _strong_identifiers(keep_tokens)) - _strong_identifiers(drop_tokens):
        return False
    return not _is_multi_identity(keep_tokens[0], keep_tokens[1:] + drop_tokens)


def _merge_on_ingest(
    conn: sqlite3.Connection,
    *,
    keep_id: str,
    drop_id: str,
    drop: sqlite3.Row,
    adapter: str | None,
    observation_id: str | None,
) -> None:
    """Merge *drop_id* into *keep_id*, recording a 'merge' row per dropped token.

    merge_entities moves the dropped entity's provenance to the survivor, so
    the 'merge' rows under *drop_id* are what keeps the two apart; the
    observation they cite is the one now sent by *keep_id*.
    """
    from patina.maintenance import merge_entities

    merge_entities(conn, keep_id=keep_id, drop_id=drop_id)
    for token in dict.fromkeys([drop["name"], *json.loads(drop["aliases"] or "[]")]):
        record_alias_provenance(
            conn,
            drop_id,
            token,
            adapter=adapter or "unknown",
            action="merge",
            observation_id=observation_id,
        )


def upsert_entity(
    conn: sqlite3.Connection,
    entity: Entity,
    *,
    adapter: str | None = None,
    observation_id: str | None = None,
) -> None:
    # IDs outrank names: no name-only re-resolve may override this match (#555).
    existing_id = resolve_entity_id(conn, entity.name, entity.aliases)

    if existing_id and existing_id != entity.id:
        source = conn.execute(
            "SELECT name, aliases FROM entities WHERE id = ?", (entity.id,)
        ).fetchone()
        if source:
            if _ingest_merge_allowed(conn, existing_id, source, entity.aliases):
                _merge_on_ingest(
                    conn,
                    keep_id=existing_id,
                    drop_id=entity.id,
                    drop=source,
                    adapter=adapter,
                    observation_id=observation_id,
                )
            else:
                # Leave the conflict to dedup's preview/confirm review.
                existing_id = entity.id

    if existing_id and existing_id != entity.id:
        existing = conn.execute(
            "SELECT name, aliases FROM entities WHERE id = ?", (existing_id,)
        ).fetchone()
        existing_aliases = json.loads(existing["aliases"] or "[]")
        new_aliases = _strip_foreign_slack_ids(conn, entity.aliases, existing_id)
        merged_aliases = list(set(existing_aliases + new_aliases))
        name = existing["name"]
        # A sink keeps its name and never collects the incoming name (#547).
        if not _is_multi_identity(name, merged_aliases):
            if _name_type_rank(entity.name) < _name_type_rank(name):
                new_aliases = new_aliases + [name]
                name = entity.name
            elif entity.name != name:
                new_aliases = new_aliases + _strip_foreign_slack_ids(
                    conn, [entity.name], existing_id
                )
            merged_aliases = list(set(existing_aliases + new_aliases))
        conn.execute(
            "UPDATE entities SET name = ?, aliases = ?, last_seen = ? WHERE id = ?",
            (name, json.dumps(merged_aliases), entity.last_seen, existing_id),
        )
        record_added_aliases(
            conn,
            existing_id,
            existing_aliases,
            new_aliases,
            adapter=adapter,
            observation_id=observation_id,
        )
        conn.commit()
        entity.id = existing_id
        return

    existing = conn.execute(
        "SELECT name, aliases FROM entities WHERE id = ?", (entity.id,)
    ).fetchone()

    if existing:
        existing_aliases = json.loads(existing["aliases"] or "[]")
        new_aliases = _strip_foreign_slack_ids(conn, entity.aliases, entity.id)
        merged_aliases = list(set(existing_aliases + new_aliases))
        if _is_multi_identity(existing["name"], merged_aliases):
            name = existing["name"]
        elif _name_type_rank(existing["name"]) < _name_type_rank(entity.name):
            name = existing["name"]
        else:
            name = entity.name
        conn.execute(
            "UPDATE entities SET name = ?, aliases = ?, last_seen = ? WHERE id = ?",
            (name, json.dumps(merged_aliases), entity.last_seen, entity.id),
        )
        record_added_aliases(
            conn,
            entity.id,
            existing_aliases,
            new_aliases,
            adapter=adapter,
            observation_id=observation_id,
        )
    else:
        safe_aliases = _strip_foreign_slack_ids(conn, entity.aliases, entity.id)
        conn.execute(
            """INSERT INTO entities
                   (id, type, name, aliases, metadata, first_seen, last_seen,
                    decay_rate)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entity.id,
                entity.type,
                entity.name,
                json.dumps(safe_aliases),
                json.dumps(entity.metadata),
                entity.first_seen,
                entity.last_seen,
                entity.decay_rate,
            ),
        )
        record_added_aliases(
            conn,
            entity.id,
            [],
            safe_aliases,
            adapter=adapter,
            observation_id=observation_id,
        )
    conn.commit()


def upsert_relationship(conn: sqlite3.Connection, rel: Relationship) -> None:
    conn.execute(
        """INSERT INTO relationships
               (id, subject_id, predicate, object_id, confidence,
                first_seen, last_confirmed, source_ids)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               confidence = MAX(relationships.confidence, excluded.confidence),
               last_confirmed = excluded.last_confirmed""",
        (
            rel.id,
            rel.subject_id,
            rel.predicate,
            rel.object_id,
            rel.confidence,
            rel.first_seen,
            rel.last_confirmed,
            json.dumps(rel.source_ids),
        ),
    )
    conn.commit()


def insert_claim(conn: sqlite3.Connection, claim: Claim) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO claims
               (id, subject_id, predicate, object, confidence,
                first_asserted, last_confirmed, decay_rate, source_ids)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            claim.id,
            claim.subject_id,
            claim.predicate,
            claim.object,
            claim.confidence,
            claim.first_asserted,
            claim.last_confirmed,
            claim.decay_rate,
            json.dumps(claim.source_ids),
        ),
    )
    conn.commit()


def insert_observation(conn: sqlite3.Connection, obs: Observation) -> bool:
    existing = conn.execute("SELECT 1 FROM observations WHERE id = ?", (obs.id,)).fetchone()

    conn.execute(
        """INSERT INTO observations
               (id, source, channel_id, thread_id, timestamp,
                sender_entity_id, text, metadata, ingested_at, processed)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               channel_id = CASE
                   WHEN observations.channel_id IS NULL OR observations.channel_id = ''
                   THEN excluded.channel_id
                   ELSE observations.channel_id
               END,
               thread_id = CASE
                   WHEN observations.thread_id IS NULL OR observations.thread_id = ''
                   THEN excluded.thread_id
                   ELSE observations.thread_id
               END""",
        (
            obs.id,
            obs.source,
            obs.channel_id,
            obs.thread_id,
            obs.timestamp,
            obs.sender_entity_id,
            obs.text,
            json.dumps(obs.metadata),
            obs.ingested_at,
            obs.processed,
        ),
    )
    conn.commit()
    return existing is None


def get_entity(conn: sqlite3.Connection, entity_id: str) -> Entity | None:
    row = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if row is None:
        return None
    return Entity(
        id=row["id"],
        type=row["type"],
        name=row["name"],
        aliases=json.loads(row["aliases"]) if row["aliases"] else [],
        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        decay_rate=row["decay_rate"],
    )


def count_entities(conn: sqlite3.Connection, entity_type: str | None = None) -> int:
    if entity_type:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM entities WHERE type = ?", (entity_type,)
        ).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) AS c FROM entities").fetchone()
    return row["c"]


def count_observations(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS c FROM observations").fetchone()
    return row["c"]
