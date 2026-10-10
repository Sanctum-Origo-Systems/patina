from __future__ import annotations

import json
import re
import sqlite3

from patina.models import Claim, Entity, Observation, Relationship
from patina.owner import normalize_alias

_SLACK_ID_PAT = re.compile(r"^[UW](?=[A-Z0-9]*\d)[A-Z0-9]{8,10}$")


def _name_type_rank(name: str) -> int:
    """Rank: full name (0) > handle (1) > email (2) > raw Slack ID (3)."""
    if " " in name:
        return 0
    if "@" in name:
        return 2
    if _SLACK_ID_PAT.match(name):
        return 3
    return 1


def normalize_name(name: str) -> str:
    name = name.strip()
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

    # --- Phase 1: Exact name match ---
    row = conn.execute(
        "SELECT id FROM entities WHERE name = ? AND is_owner = 0 LIMIT 1",
        (name,),
    ).fetchone()
    if row:
        return row["id"]

    # --- Phase 2: Normalized name / alias match (ambiguity-safe) ---
    name_clean = normalize_alias(name)
    normalized = normalize_name(name_clean)
    non_owner_rows = None

    if normalized and len(normalized) > 2:
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
            for r in non_owner_rows:
                for alias in json.loads(r["aliases"] or "[]"):
                    clean = normalize_alias(alias)
                    if normalize_name(clean) == normalized:
                        alias_matches.add(r["id"])
                        break
            if len(alias_matches) == 1:
                return alias_matches.pop()

    # --- Phase 3: Slack ID lookup (tiebreaker for ambiguous name/alias) ---
    if aliases:
        if non_owner_rows is None:
            non_owner_rows = conn.execute(
                "SELECT id, name, aliases FROM entities WHERE is_owner = 0"
            ).fetchall()
        for alias in aliases:
            if not alias:
                continue
            stripped = normalize_alias(alias)
            if not _SLACK_ID_PAT.match(stripped):
                continue
            for r in non_owner_rows:
                for stored_alias in json.loads(r["aliases"] or "[]"):
                    if normalize_alias(stored_alias) == stripped:
                        return r["id"]

    # --- Phase 4: Provided non-Slack-ID aliases (ambiguity-safe) ---
    if aliases:
        if non_owner_rows is None:
            non_owner_rows = conn.execute(
                "SELECT id, name, aliases FROM entities WHERE is_owner = 0"
            ).fetchall()
        for alias in aliases:
            if not alias:
                continue
            stripped = normalize_alias(alias)
            if _SLACK_ID_PAT.match(stripped):
                continue
            matches: set[str] = set()
            for r in non_owner_rows:
                for stored_alias in json.loads(r["aliases"] or "[]"):
                    if normalize_alias(stored_alias) == stripped:
                        matches.add(r["id"])
                        break
            if len(matches) == 1:
                return matches.pop()
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


def upsert_entity(conn: sqlite3.Connection, entity: Entity) -> None:
    existing_id = resolve_entity_id(conn, entity.name, entity.aliases)

    if existing_id and existing_id != entity.id:
        source = conn.execute("SELECT 1 FROM entities WHERE id = ?", (entity.id,)).fetchone()
        if source:
            from patina.maintenance import merge_entities

            merge_entities(conn, keep_id=existing_id, drop_id=entity.id)

        existing = conn.execute(
            "SELECT aliases FROM entities WHERE id = ?", (existing_id,)
        ).fetchone()
        existing_aliases = json.loads(existing["aliases"] or "[]")
        new_aliases = _strip_foreign_slack_ids(conn, entity.aliases, existing_id)
        merged_aliases = list(set(existing_aliases + new_aliases))
        conn.execute(
            "UPDATE entities SET aliases = ?, last_seen = ? WHERE id = ?",
            (json.dumps(merged_aliases), entity.last_seen, existing_id),
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
        name = (
            existing["name"]
            if _name_type_rank(existing["name"]) < _name_type_rank(entity.name)
            else entity.name
        )
        conn.execute(
            "UPDATE entities SET name = ?, aliases = ?, last_seen = ? WHERE id = ?",
            (name, json.dumps(merged_aliases), entity.last_seen, entity.id),
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
