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
Analyze these messages and extract structured beliefs.

For each message, identify:
1. CLAIMS: factual assertions (e.g., "X is VP of Engineering")
2. RELATIONSHIPS: connections (e.g., "X reports_to Y")
3. COMMITMENTS: promises (e.g., "X will deliver Y by Z date")

Output JSON with this exact structure:
{
  "claims": [
    {"subject": "name", "predicate": "role|expertise|location|team",
     "object": "value", "confidence": 0.5-1.0}
  ],
  "relationships": [
    {"subject": "name", "predicate": "reports_to|collaborates_with|manages",
     "object": "other_name", "confidence": 0.5-1.0}
  ]
}

Rules:
- Only extract claims that are stated or strongly implied, not speculated
- Confidence: 0.9+ for explicit statements, 0.7 for implied, 0.5 for inferred
- Use the sender's name as subject when they state something about themselves
- Use mentioned names as subjects when claims are about others
- Skip greetings, bot messages, and messages with no extractable information (return empty lists)

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


def _resolve_entity_id(conn, name: str) -> str | None:
    row = conn.execute(
        "SELECT id FROM entities WHERE name = ? OR name LIKE ? LIMIT 1",
        (name, f"%{name}%"),
    ).fetchone()
    return row["id"] if row else None


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
            claims = extracted.get("claims", [])
            relationships = extracted.get("relationships", [])

            for claim in claims:
                subject_name = claim.get("subject", "")
                subject_id = _resolve_entity_id(conn, subject_name)
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
                            first_asserted, last_confirmed, decay_rate, source_ids)
                           VALUES (?, ?, ?, ?, ?, ?, ?, 0.02, '["extraction"]')""",
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
                           VALUES (?, ?, ?, ?, ?, ?, ?, '["extraction"]')""",
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

            obs_ids = [row["id"] for row in batch]
            conn.executemany(
                "UPDATE observations SET processed = 1 WHERE id = ?",
                [(oid,) for oid in obs_ids],
            )
            conn.commit()

            stats["observations_processed"] += len(batch)
            print(f"+{len(claims)} claims, +{len(relationships)} rels")

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
