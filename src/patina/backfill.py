"""Backfill decisions from historical reactions stored in observation metadata.

Scans observations for Slack-style reactions by the owner and records
corresponding decision rows so that get_act_on_rate() reflects real
behavioral history.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from patina.owner import get_owner_user_ids

ACK_REACTIONS = frozenset(
    {
        "+1",
        "thumbsup",
        "white_check_mark",
        "heavy_check_mark",
        "check",
        "ballot_box_with_check",
        "100",
        "ok",
        "ok_hand",
        "raised_hands",
        "tada",
    }
)


def _decision_id(observation_id: str, action: str) -> str:
    return hashlib.sha256(f"backfill:{observation_id}:{action}".encode()).hexdigest()[:16]


def backfill_decisions_from_reactions(
    conn: sqlite3.Connection,
    owner_user_ids: list[str],
    *,
    dry_run: bool = False,
) -> dict:
    """Scan observations for owner reactions and insert decision rows.

    Returns a dict with counts: inserted, skipped (already has decision),
    and scanned (total observations with reactions).
    """
    owner_set = set(owner_user_ids)
    if not owner_set:
        return {"inserted": 0, "skipped": 0, "scanned": 0}

    rows = conn.execute(
        """SELECT o.id, o.timestamp, o.metadata
           FROM observations o
           WHERE o.metadata IS NOT NULL AND o.metadata != '{}'"""
    ).fetchall()

    existing = set(
        r["observation_id"] for r in conn.execute("SELECT observation_id FROM decisions").fetchall()
    )

    inserted = 0
    skipped = 0
    scanned = 0

    for row in rows:
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        reactions = meta.get("reactions", [])
        if not reactions:
            continue

        scanned += 1

        if row["id"] in existing:
            skipped += 1
            continue

        has_owner_ack = False
        for reaction in reactions:
            name = reaction.get("name", "")
            users = reaction.get("users", [])
            if name in ACK_REACTIONS and owner_set.intersection(users):
                has_owner_ack = True
                break

        if not has_owner_ack:
            continue

        if dry_run:
            inserted += 1
            continue

        dec_id = _decision_id(row["id"], "acted")
        acted_at_ts = row["timestamp"]
        from datetime import UTC, datetime

        acted_at = datetime.fromtimestamp(acted_at_ts, tz=UTC).isoformat()

        conn.execute(
            """INSERT OR IGNORE INTO decisions
               (id, observation_id, action, acted_at, latency_seconds, context)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (dec_id, row["id"], "acted", acted_at, None, "backfill:reaction"),
        )
        inserted += 1

    if not dry_run:
        conn.commit()

    return {"inserted": inserted, "skipped": skipped, "scanned": scanned}


def run_backfill(
    *,
    home: Path | None = None,
    dry_run: bool = False,
) -> dict:
    """High-level entry point: resolve owner IDs and run the backfill."""
    from patina.store import connect, get_db_path, init_db

    owner_ids = get_owner_user_ids(home)
    if not owner_ids:
        return {"inserted": 0, "skipped": 0, "scanned": 0, "error": "no_owner_ids"}

    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)
    try:
        result = backfill_decisions_from_reactions(conn, owner_ids, dry_run=dry_run)
    finally:
        conn.close()

    return result
