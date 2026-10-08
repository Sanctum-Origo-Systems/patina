"""Extract beliefs (claims + relationships) from unprocessed observations using Claude.

Sends batches of observations to Claude CLI for analysis,
writes extracted claims and relationships to the belief graph.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from patina.maintenance import is_plausible_person_name as _is_plausible_person_name
from patina.store import connect, get_db_path, init_db

EXTRACTION_PROMPT = """\
Analyze these messages and extract structured beliefs about people and their relationships.

For each message, identify:
1. ENTITIES: real people only — individuals with names. Do NOT extract meeting titles, \
system names, team names, project names, or concepts as entities. \
Only extract if the entity is a human being with a personal name.
2. CLAIMS: factual assertions about a person (e.g., "X is VP of Engineering", \
"X is based in Chicago")
3. RELATIONSHIPS: connections between people (e.g., "X reports_to Y", \
"X collaborates_with Y")
4. BEHAVIORAL: communication patterns, commitments made, urgency signals

Output JSON with this exact structure:
{
  "entities": [
    {"name": "display name", "aliases": ["alias1", "alias2"], "type": "person"}
  ],
  "claims": [
    {"subject": "name", \
"predicate": "role|expertise|location|team|org|title", \
"object": "value", "confidence": 0.5-1.0}
  ],
  "relationships": [
    {"subject": "name", \
"predicate": "reports_to|collaborates_with|manages|works_with", \
"object": "other_name", "confidence": 0.5-1.0}
  ],
  "behavioral": [
    {"subject": "name", \
"predicate": "communication_style|response_pattern|commitment|urgency", \
"object": "description", "confidence": 0.5-1.0}
  ]
}

Rules:
- Always extract the sender as an entity if they have a real name
- Only extract claims that are stated or strongly implied, not speculated
- Confidence: 0.9+ for explicit statements, 0.7 for implied, 0.5 for inferred
- For behavioral: note if someone consistently makes commitments, escalates urgency, \
or has a distinct communication style
- Skip bot messages and messages with no extractable information \
(return empty lists for all keys)

Messages to analyze:
"""


def _id(prefix: str, key: str) -> str:
    return hashlib.sha256(f"{prefix}:{key}".encode()).hexdigest()[:16]


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _call_claude(prompt: str, model: str = "sonnet") -> str:
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", model, "--no-session-persistence", prompt],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            print(f"  [WARN] claude returned exit code {result.returncode}: {result.stderr[:200]}")
            return ""
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print("  [WARN] claude call timed out")
        return ""
    except FileNotFoundError:
        print("  [ERROR] 'claude' not found in PATH. Is Claude Code installed?")
        return ""


def _parse_extraction(response: str) -> dict:
    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [line for line in lines if not line.startswith("```")]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
    return {"claims": [], "relationships": []}


def _resolve_entity_id(
    conn,
    name: str,
    *,
    owner_entity_id: str | None = None,
    owner_match_names: set[str] | None = None,
) -> str | None:
    from patina.graph import normalize_name, resolve_entity_id

    if not name or not name.strip():
        return None
    name = name.strip()

    if owner_entity_id and owner_match_names:
        if name.lower() in owner_match_names or normalize_name(name) in owner_match_names:
            return owner_entity_id

    return resolve_entity_id(conn, name)


def _resolve_single_token_name(
    conn,
    token: str,
    batch_names: set[str],
    *,
    owner_entity_id: str | None = None,
    owner_match_names: set[str] | None = None,
) -> str | None:
    from patina.graph import normalize_name

    token_lower = token.strip().lower()
    if not token_lower:
        return None

    if owner_entity_id and owner_match_names:
        if token_lower in owner_match_names:
            return owner_entity_id

    rows = conn.execute("SELECT id, name FROM entities WHERE is_owner = 0").fetchall()

    candidates = []
    for r in rows:
        norm = normalize_name(r["name"])
        parts = norm.split()
        if not parts:
            continue
        if parts[0] == token_lower:
            if r["name"].lower() in batch_names or norm in batch_names:
                candidates.append(r["id"])

    if len(candidates) == 1:
        return candidates[0]
    return None


def _resolve_entity_in_batch(
    conn,
    name: str,
    batch_names: set[str],
    *,
    owner_entity_id: str | None = None,
    owner_match_names: set[str] | None = None,
) -> str | None:
    if not name or not name.strip():
        return None
    name = name.strip()
    if _is_single_token_name(name):
        return _resolve_single_token_name(
            conn,
            name,
            batch_names,
            owner_entity_id=owner_entity_id,
            owner_match_names=owner_match_names,
        )
    return _resolve_entity_id(
        conn,
        name,
        owner_entity_id=owner_entity_id,
        owner_match_names=owner_match_names,
    )


def _is_normalized_name_variant(alias: str, name: str) -> bool:
    from patina.graph import normalize_name

    norm_alias = normalize_name(alias)
    norm_name = normalize_name(name)
    if not norm_alias or not norm_name:
        return False
    if norm_alias == norm_name:
        return True
    name_parts = set(norm_name.split())
    alias_parts = set(norm_alias.split())
    if alias_parts and alias_parts <= name_parts:
        return True
    return False


def _is_handle_or_email(alias: str) -> bool:
    return "@" in alias or alias.startswith("#")


def _is_single_token_name(name: str) -> bool:
    name = name.strip()
    if not name:
        return False
    return " " not in name and "-" not in name and "," not in name


def _alias_collides_with_other_entity(conn, alias: str, target_entity_id: str) -> bool:
    from patina.graph import normalize_name
    from patina.owner import normalize_alias

    norm = normalize_name(normalize_alias(alias))
    rows = conn.execute(
        "SELECT id, name, aliases FROM entities WHERE id != ?",
        (target_entity_id,),
    ).fetchall()
    for r in rows:
        if normalize_name(r["name"]) == norm:
            return True
        for stored in json.loads(r["aliases"] or "[]"):
            if normalize_name(normalize_alias(stored)) == norm:
                return True
    return False


def _filter_aliases(
    conn,
    aliases: list[str],
    entity_name: str,
    entity_id: str,
) -> tuple[list[str], int]:
    collisions = 0
    accepted = []
    for alias in aliases:
        alias = alias.strip()
        if not alias:
            continue
        if _is_handle_or_email(alias):
            if _alias_collides_with_other_entity(conn, alias, entity_id):
                collisions += 1
            else:
                accepted.append(alias)
            continue
        if " " not in alias and "-" not in alias and "," not in alias:
            collisions += 1
            continue
        if _alias_collides_with_other_entity(conn, alias, entity_id):
            collisions += 1
            continue
        if _is_normalized_name_variant(alias, entity_name):
            accepted.append(alias)
        else:
            collisions += 1
    return accepted, collisions


def _upsert_entity(
    conn,
    name: str,
    aliases: list[str] | None = None,
    *,
    owner_entity_id: str | None = None,
    owner_match_names: set[str] | None = None,
) -> tuple[str, int]:
    from patina.graph import normalize_name, resolve_entity_id

    name = name.strip()
    if not _is_plausible_person_name(name):
        return "", 0

    if owner_entity_id and owner_match_names:
        incoming = {name.lower(), normalize_name(name)}
        if aliases:
            for a in aliases:
                incoming.add(a.lower())
                incoming.add(normalize_name(a))
        incoming.discard("")
        if incoming & owner_match_names:
            return owner_entity_id, 0

    if aliases and owner_match_names:
        aliases = [
            a
            for a in aliases
            if a.lower() not in owner_match_names and normalize_name(a) not in owner_match_names
        ]

    existing_id = resolve_entity_id(conn, name, aliases)
    if existing_id:
        collisions = 0
        if aliases:
            aliases, collisions = _filter_aliases(conn, aliases, name, existing_id)
            if aliases:
                existing = conn.execute(
                    "SELECT aliases FROM entities WHERE id = ?",
                    (existing_id,),
                ).fetchone()
                if existing:
                    existing_aliases = json.loads(existing["aliases"] or "[]")
                    merged = list(set(existing_aliases + aliases))
                    conn.execute(
                        "UPDATE entities SET aliases = ? WHERE id = ?",
                        (json.dumps(merged), existing_id),
                    )
        return existing_id, collisions

    if _is_single_token_name(name):
        token_lower = name.strip().lower()
        rows = conn.execute("SELECT id, name FROM entities WHERE is_owner = 0").fetchall()
        candidates = []
        for r in rows:
            parts = normalize_name(r["name"]).split()
            if parts and parts[0] == token_lower:
                candidates.append(r["id"])
        if len(candidates) == 1:
            return candidates[0], 0
        return "", 0

    collisions = 0
    if aliases:
        entity_id = _id("person", name)
        aliases, collisions = _filter_aliases(conn, aliases, name, entity_id)
    else:
        entity_id = _id("person", name)

    now = _iso_now()
    conn.execute(
        """INSERT OR IGNORE INTO entities
           (id, type, name, aliases, metadata, first_seen, last_seen,
            decay_rate, is_owner)
           VALUES (?, 'person', ?, ?, '{}', ?, ?, 0.02, 0)""",
        (entity_id, name, json.dumps(aliases or []), now, now),
    )
    return entity_id, collisions


def extract_beliefs(
    *,
    batch_size: int = 10,
    limit: int = 500,
    model: str = "sonnet",
    dry_run: bool = False,
    home: Path | None = None,
) -> dict:
    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)

    stats = {
        "observations_processed": 0,
        "claims_extracted": 0,
        "relationships_extracted": 0,
        "batches_sent": 0,
        "errors": 0,
        "skipped_unresolved": 0,
        "alias_collisions": 0,
    }

    try:
        from patina.graph import normalize_name as _normalize_name
        from patina.owner import get_owner_entity_id, get_owner_identifiers, normalize_alias

        owner_entity_id = get_owner_entity_id(conn)
        owner_match_names: set[str] = set()
        if owner_entity_id:
            for ident in get_owner_identifiers(home):
                owner_match_names.add(ident.lower())
                normalized = _normalize_name(ident)
                if normalized:
                    owner_match_names.add(normalized)
            row = conn.execute(
                "SELECT name, aliases FROM entities WHERE id = ?",
                (owner_entity_id,),
            ).fetchone()
            if row:
                owner_match_names.add(row["name"].lower())
                normalized = _normalize_name(row["name"])
                if normalized:
                    owner_match_names.add(normalized)
                for alias in json.loads(row["aliases"] or "[]"):
                    clean = normalize_alias(alias)
                    owner_match_names.add(clean.lower())
                    normalized = _normalize_name(clean)
                    if normalized:
                        owner_match_names.add(normalized)
            owner_match_names.discard("")

        rows = conn.execute(
            """SELECT o.id, o.text, o.sender_entity_id, o.source, o.timestamp,
                      e.name AS sender_name
               FROM observations o
               LEFT JOIN entities e ON o.sender_entity_id = e.id
               WHERE o.processed = 0 AND o.text IS NOT NULL AND o.text != ''
               ORDER BY o.timestamp ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()

        if not rows:
            print("No unprocessed observations found.")
            return stats

        print(f"Processing {len(rows)} observations in batches of {batch_size}...")
        print(f"Model: {model}")
        print()

        now = _iso_now()

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(rows) + batch_size - 1) // batch_size

            print(
                f"  Batch {batch_num}/{total_batches} ({len(batch)} messages)...",
                end=" ",
                flush=True,
            )

            messages_text = ""
            for row in batch:
                sender = row["sender_name"] or "unknown"
                text = row["text"][:500]
                messages_text += f"\n[{sender}]: {text}\n"

            prompt = EXTRACTION_PROMPT + messages_text

            if dry_run:
                print("[DRY RUN - skipped]")
                stats["observations_processed"] += len(batch)
                continue

            response = _call_claude(prompt, model=model)
            if not response:
                print("[no response]")
                stats["errors"] += 1
                continue

            stats["batches_sent"] += 1

            extracted = _parse_extraction(response)
            entities = extracted.get("entities", [])
            claims = extracted.get("claims", [])
            relationships = extracted.get("relationships", [])
            behavioral = extracted.get("behavioral", [])

            for ent in entities:
                name = ent.get("name", "").strip()
                if name and len(name) > 1 and ent.get("type") == "person":
                    _, collisions = _upsert_entity(
                        conn,
                        name,
                        ent.get("aliases", []),
                        owner_entity_id=owner_entity_id,
                        owner_match_names=owner_match_names,
                    )
                    stats["alias_collisions"] += collisions

            batch_names: set[str] = set()
            for row in batch:
                sender = row["sender_name"]
                if sender:
                    batch_names.add(sender.lower())
                    norm = _normalize_name(sender)
                    if norm:
                        batch_names.add(norm)
            for ent in entities:
                ent_name = ent.get("name", "").strip()
                if ent_name:
                    batch_names.add(ent_name.lower())
                    norm = _normalize_name(ent_name)
                    if norm:
                        batch_names.add(norm)

            for claim in claims:
                subject_name = claim.get("subject", "")
                subject_id = _resolve_entity_in_batch(
                    conn,
                    subject_name,
                    batch_names,
                    owner_entity_id=owner_entity_id,
                    owner_match_names=owner_match_names,
                )
                if not subject_id:
                    stats["skipped_unresolved"] += 1
                    continue
                claim_id = _id(
                    "claim",
                    f"{subject_id}:{claim['predicate']}:{claim['object']}",
                )
                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO claims
                           (id, subject_id, predicate, object, confidence,
                            first_asserted, last_confirmed, decay_rate,
                            source_ids)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 0.02,
                                   '["extraction"]')""",
                        (
                            claim_id,
                            subject_id,
                            claim["predicate"],
                            claim["object"],
                            claim.get("confidence", 0.7),
                            now,
                            now,
                        ),
                    )
                    stats["claims_extracted"] += 1
                except Exception as e:
                    print(f"\n    [WARN] Failed to insert claim: {e}")

            for rel in relationships:
                subject_id = _resolve_entity_in_batch(
                    conn,
                    rel.get("subject", ""),
                    batch_names,
                    owner_entity_id=owner_entity_id,
                    owner_match_names=owner_match_names,
                )
                object_id = _resolve_entity_in_batch(
                    conn,
                    rel.get("object", ""),
                    batch_names,
                    owner_entity_id=owner_entity_id,
                    owner_match_names=owner_match_names,
                )
                if not subject_id or not object_id:
                    stats["skipped_unresolved"] += 1
                    continue
                rel_id = _id(
                    "rel",
                    f"{subject_id}:{rel['predicate']}:{object_id}",
                )
                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO relationships
                           (id, subject_id, predicate, object_id, confidence,
                            first_seen, last_confirmed, source_ids)
                           VALUES (?, ?, ?, ?, ?, ?, ?,
                                   '["extraction"]')""",
                        (
                            rel_id,
                            subject_id,
                            rel["predicate"],
                            object_id,
                            rel.get("confidence", 0.7),
                            now,
                            now,
                        ),
                    )
                    stats["relationships_extracted"] += 1
                except Exception as e:
                    print(f"\n    [WARN] Failed to insert relationship: {e}")

            for beh in behavioral:
                subject_name = beh.get("subject", "")
                subject_id = _resolve_entity_in_batch(
                    conn,
                    subject_name,
                    batch_names,
                    owner_entity_id=owner_entity_id,
                    owner_match_names=owner_match_names,
                )
                if not subject_id:
                    stats["skipped_unresolved"] += 1
                    continue
                predicate = f"behavioral:{beh.get('predicate', 'pattern')}"
                claim_id = _id(
                    "claim",
                    f"{subject_id}:{predicate}:{beh.get('object', '')}",
                )
                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO claims
                           (id, subject_id, predicate, object, confidence,
                            first_asserted, last_confirmed, decay_rate,
                            source_ids)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 0.05,
                                   '["behavioral_extraction"]')""",
                        (
                            claim_id,
                            subject_id,
                            predicate,
                            beh.get("object", ""),
                            beh.get("confidence", 0.6),
                            now,
                            now,
                        ),
                    )
                    stats["claims_extracted"] += 1
                except Exception as e:
                    print(f"\n    [WARN] Failed to insert behavioral: {e}")

            obs_ids = [row["id"] for row in batch]
            conn.executemany(
                "UPDATE observations SET processed = 1 WHERE id = ?",
                [(oid,) for oid in obs_ids],
            )
            conn.commit()

            stats["observations_processed"] += len(batch)
            n_ent, n_cl = len(entities), len(claims)
            n_rel, n_beh = len(relationships), len(behavioral)
            print(f"+{n_ent} entities, +{n_cl} claims, +{n_rel} rels, +{n_beh} behavioral")

            time.sleep(1)

        print()
        print(f"  Observations processed: {stats['observations_processed']}")
        print(f"  Claims extracted:       {stats['claims_extracted']}")
        print(f"  Relationships found:    {stats['relationships_extracted']}")
        print(f"  Batches sent to LLM:    {stats['batches_sent']}")
        if stats["skipped_unresolved"]:
            print(f"  Skipped (unresolved):   {stats['skipped_unresolved']}")
        if stats["alias_collisions"]:
            print(f"  Alias collisions:       {stats['alias_collisions']}")
        if stats["errors"]:
            print(f"  Errors:                 {stats['errors']}")

        return stats

    finally:
        conn.close()
