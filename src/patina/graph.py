from __future__ import annotations

import json
import sqlite3

from patina.models import Claim, Entity, Observation, Relationship


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

    row = conn.execute(
        "SELECT id FROM entities WHERE name = ? AND is_owner = 0 LIMIT 1",
        (name,),
    ).fetchone()
    if row:
        return row["id"]

    row = conn.execute(
        "SELECT id FROM entities WHERE aliases LIKE ? AND is_owner = 0 LIMIT 1",
        (f"%{name}%",),
    ).fetchone()
    if row:
        return row["id"]

    normalized = normalize_name(name)
    if normalized and len(normalized) > 2:
        rows = conn.execute("SELECT id, name FROM entities WHERE is_owner = 0").fetchall()
        for r in rows:
            if normalize_name(r["name"]) == normalized:
                return r["id"]
        row = conn.execute(
            "SELECT id FROM entities WHERE aliases LIKE ? AND is_owner = 0 LIMIT 1",
            (f"%{normalized}%",),
        ).fetchone()
        if row:
            return row["id"]

    if aliases:
        for alias in aliases:
            if not alias:
                continue
            row = conn.execute(
                "SELECT id FROM entities WHERE aliases LIKE ? AND is_owner = 0 LIMIT 1",
                (f"%{alias}%",),
            ).fetchone()
            if row:
                return row["id"]
            norm_alias = normalize_name(alias)
            if norm_alias and len(norm_alias) > 2:
                row = conn.execute(
                    "SELECT id FROM entities WHERE name = ? AND is_owner = 0 LIMIT 1",
                    (norm_alias,),
                ).fetchone()
                if row:
                    return row["id"]

    return None


def upsert_entity(conn: sqlite3.Connection, entity: Entity) -> None:
    existing_id = resolve_entity_id(conn, entity.name, entity.aliases)

    if existing_id and existing_id != entity.id:
        existing = conn.execute(
            "SELECT aliases FROM entities WHERE id = ?", (existing_id,)
        ).fetchone()
        existing_aliases = json.loads(existing["aliases"] or "[]")
        merged_aliases = list(set(existing_aliases + entity.aliases))
        conn.execute(
            "UPDATE entities SET aliases = ?, last_seen = ? WHERE id = ?",
            (json.dumps(merged_aliases), entity.last_seen, existing_id),
        )
        conn.commit()
        entity.id = existing_id
        return

    conn.execute(
        """INSERT INTO entities
               (id, type, name, aliases, metadata, first_seen, last_seen,
                decay_rate)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               name = excluded.name,
               aliases = excluded.aliases,
               last_seen = excluded.last_seen""",
        (
            entity.id,
            entity.type,
            entity.name,
            json.dumps(entity.aliases),
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
    try:
        conn.execute(
            """INSERT INTO observations
                   (id, source, channel_id, thread_id, timestamp,
                    sender_entity_id, text, metadata, ingested_at, processed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        return True
    except sqlite3.IntegrityError:
        return False


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
