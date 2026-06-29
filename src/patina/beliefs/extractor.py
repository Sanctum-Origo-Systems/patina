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

from patina.store import connect, get_db_path, init_db

EXTRACTION_PROMPT = """\
Analyze these messages and extract structured beliefs about people and their relationships.

For each message, identify:
1. ENTITIES: people mentioned or sending messages (extract their name and any identifiers)
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


def _resolve_entity_id(conn, name: str, *, exclude_owner: bool = False) -> str | None:
    if exclude_owner:
        row = conn.execute(
            "SELECT id FROM entities WHERE (name = ? OR name LIKE ?) AND is_owner = 0 LIMIT 1",
            (name, f"%{name}%"),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM entities WHERE name = ? OR name LIKE ? LIMIT 1",
            (name, f"%{name}%"),
        ).fetchone()
    return row["id"] if row else None


def _upsert_entity(conn, name: str, aliases: list[str] | None = None) -> str:
    entity_id = _resolve_entity_id(conn, name)
    if entity_id:
        return entity_id
    now = _iso_now()
    entity_id = _id("person", name)
    conn.execute(
        """INSERT OR IGNORE INTO entities
           (id, type, name, aliases, metadata, first_seen, last_seen,
            decay_rate, is_owner)
           VALUES (?, 'person', ?, ?, '{}', ?, ?, 0.02, 0)""",
        (entity_id, name, json.dumps(aliases or []), now, now),
    )
    return entity_id


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
    }

    try:
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
                if name and len(name) > 1:
                    _upsert_entity(conn, name, ent.get("aliases", []))

            for item in claims + relationships + behavioral:
                for key in ("subject", "object"):
                    name = item.get(key, "").strip()
                    if name and len(name) > 1 and not name[0].islower():
                        _upsert_entity(conn, name)

            for claim in claims:
                subject_name = claim.get("subject", "")
                subject_id = _resolve_entity_id(
                    conn, subject_name, exclude_owner=True
                )
                if not subject_id:
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
                subject_id = _resolve_entity_id(conn, rel.get("subject", ""))
                object_id = _resolve_entity_id(conn, rel.get("object", ""))
                if not subject_id or not object_id:
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
                    print(
                        f"\n    [WARN] Failed to insert relationship: {e}"
                    )

            for beh in behavioral:
                subject_name = beh.get("subject", "")
                subject_id = _resolve_entity_id(
                    conn, subject_name, exclude_owner=True
                )
                if not subject_id:
                    continue
                predicate = (
                    f"behavioral:{beh.get('predicate', 'pattern')}"
                )
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
                    print(
                        f"\n    [WARN] Failed to insert behavioral: {e}"
                    )

            obs_ids = [row["id"] for row in batch]
            conn.executemany(
                "UPDATE observations SET processed = 1 WHERE id = ?",
                [(oid,) for oid in obs_ids],
            )
            conn.commit()

            stats["observations_processed"] += len(batch)
            n_ent, n_cl = len(entities), len(claims)
            n_rel, n_beh = len(relationships), len(behavioral)
            print(
                f"+{n_ent} entities, +{n_cl} claims, "
                f"+{n_rel} rels, +{n_beh} behavioral"
            )

            time.sleep(1)

        print()
        print(f"  Observations processed: {stats['observations_processed']}")
        print(f"  Claims extracted:       {stats['claims_extracted']}")
        print(f"  Relationships found:    {stats['relationships_extracted']}")
        print(f"  Batches sent to LLM:    {stats['batches_sent']}")
        if stats["errors"]:
            print(f"  Errors:                 {stats['errors']}")

        return stats

    finally:
        conn.close()
