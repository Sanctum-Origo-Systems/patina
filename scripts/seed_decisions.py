"""Seed decision records to simulate user behavior patterns for trust scoring.

Reads existing observations and creates decisions that reflect differential
trust: fast action on high-trust senders, slow/no action on low-priority ones.

Usage:
    python scripts/seed_decisions.py

Run AFTER ingestion and belief extraction. No LLM needed.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from patina.store import connect, get_db_path, init_db

# Define behavioral patterns per sender
# act_rate: fraction of their messages user acts on
# action: what the user does ("acted", "dismissed", "acknowledged")
BEHAVIOR = {
    "Alexis Williams": {"act_rate": 0.9, "action": "acted"},
    "Dana Torres": {"act_rate": 1.0, "action": "acted"},
    "Jordan Kim": {"act_rate": 0.85, "action": "acted"},
    "Kai Robertson": {"act_rate": 0.8, "action": "acted"},
    "Priya Sharma": {"act_rate": 0.7, "action": "acted"},
    "Sam O'Brien": {"act_rate": 0.75, "action": "acted"},
    "Maya Patel": {"act_rate": 0.35, "action": "acted"},
    "Atlas CI Bot": {"act_rate": 0.0, "dismiss_rate": 1.0, "action": "dismissed"},
}


def _id(prefix: str, key: str) -> str:
    return hashlib.sha256(f"{prefix}:{key}".encode()).hexdigest()[:16]


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def seed_decisions(*, home: Path | None = None) -> dict:
    db_path = get_db_path(home)
    init_db(db_path)
    conn = connect(db_path)

    stats = {"acted": 0, "dismissed": 0, "skipped": 0}

    try:
        # Get all observations grouped by sender
        rows = conn.execute(
            """SELECT o.id, o.timestamp, o.sender_entity_id, e.name AS sender_name
               FROM observations o
               LEFT JOIN entities e ON o.sender_entity_id = e.id
               WHERE e.name IS NOT NULL AND (e.is_owner IS NULL OR e.is_owner = 0)
               ORDER BY o.timestamp""",
        ).fetchall()

        # Check existing decisions to avoid duplicates
        existing = set(
            r["observation_id"]
            for r in conn.execute("SELECT observation_id FROM decisions").fetchall()
        )

        import random

        random.seed(42)  # Deterministic for reproducibility

        # Group by sender, seed decisions for all BUT last 2 per sender
        grouped: dict[str, list] = {}
        for row in rows:
            sender = row["sender_name"]
            grouped.setdefault(sender, []).append(row)

        for sender, obs_list in grouped.items():
            behavior = BEHAVIOR.get(sender)
            if not behavior:
                stats["skipped"] += len(obs_list)
                continue

            old = obs_list[:-2]
            # obs_list[-2:] left without decisions → appears in catch-up

            for row in old:
                if row["id"] in existing:
                    continue

                act_rate = behavior.get("act_rate", 0)
                dismiss_rate = behavior.get("dismiss_rate", 0)

                roll = random.random()

                if roll < act_rate:
                    action = "acted"
                    stats["acted"] += 1
                elif roll < act_rate + dismiss_rate:
                    action = "dismissed"
                    stats["dismissed"] += 1
                else:
                    action = "ignored"
                    stats["skipped"] += 1

                if sender in ("Alexis Williams", "Dana Torres"):
                    latency = random.uniform(60, 300)
                elif sender in ("Jordan Kim", "Kai Robertson", "Priya Sharma"):
                    latency = random.uniform(300, 1800)
                elif sender == "Sam O'Brien":
                    latency = random.uniform(1800, 7200)
                elif sender == "Maya Patel":
                    latency = random.uniform(7200, 86400)
                elif sender == "Atlas CI Bot":
                    latency = random.uniform(5, 30)
                else:
                    latency = random.uniform(600, 3600)

                decision_id = _id("decision", f"{row['id']}:{action}")
                acted_at = datetime.fromtimestamp(row["timestamp"] + latency, tz=UTC).isoformat()

                conn.execute(
                    """INSERT OR IGNORE INTO decisions
                       (id, observation_id, action, acted_at, latency_seconds, context)
                       VALUES (?, ?, ?, ?, ?, NULL)""",
                    (decision_id, row["id"], action, acted_at, round(latency, 1)),
                )

        conn.commit()

        # Print trust scores after seeding
        print("Decisions seeded:")
        print(f"  Acted:     {stats['acted']}")
        print(f"  Dismissed: {stats['dismissed']}")
        print(f"  Skipped:   {stats['skipped']}")
        print()

        # Show resulting trust levels
        print("Resulting trust levels:")
        from patina.beliefs.relationships import compute_trust_level

        for name in BEHAVIOR:
            entity = conn.execute("SELECT id FROM entities WHERE name = ?", (name,)).fetchone()
            if entity:
                trust = compute_trust_level(conn, entity["id"])
                print(f"  {name:<20} → {trust:.3f}")

        return stats

    finally:
        conn.close()


if __name__ == "__main__":
    seed_decisions()
