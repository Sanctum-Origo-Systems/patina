from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime


def compute_effective_confidence(
    confidence: float, decay_rate: float, days_since_confirmed: float
) -> float:
    return confidence * (1 - decay_rate) ** days_since_confirmed


def _days_since(iso_str: str) -> float:
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return (time.time() - dt.timestamp()) / 86400
    except (ValueError, TypeError):
        return 0.0


def run_decay_pass(conn: sqlite3.Connection) -> int:
    stale_count = 0

    claims = conn.execute(
        "SELECT id, confidence, decay_rate, last_confirmed FROM claims"
    ).fetchall()
    for row in claims:
        days = _days_since(row["last_confirmed"])
        eff = compute_effective_confidence(row["confidence"], row["decay_rate"], days)
        if eff < 0.3:
            stale_count += 1

    rels = conn.execute("SELECT id, confidence, last_confirmed FROM relationships").fetchall()
    for row in rels:
        days = _days_since(row["last_confirmed"])
        eff = compute_effective_confidence(row["confidence"], 0.02, days)
        if eff < 0.3:
            stale_count += 1

    return stale_count


def get_stale_beliefs(conn: sqlite3.Connection, threshold: float = 0.3) -> list[dict]:
    results: list[dict] = []

    claims = conn.execute(
        """SELECT c.id, c.subject_id, c.predicate, c.object,
                  c.confidence, c.decay_rate, c.last_confirmed,
                  e.name AS subject_name
           FROM claims c
           LEFT JOIN entities e ON c.subject_id = e.id"""
    ).fetchall()

    for row in claims:
        days = _days_since(row["last_confirmed"])
        eff = compute_effective_confidence(row["confidence"], row["decay_rate"], days)
        if eff < threshold:
            results.append(
                {
                    "id": row["id"],
                    "type": "claim",
                    "subject_name": row["subject_name"] or row["subject_id"],
                    "predicate": row["predicate"],
                    "object": row["object"],
                    "effective_confidence": round(eff, 3),
                    "days_since_confirmed": round(days, 1),
                }
            )

    rels = conn.execute(
        """SELECT r.id, r.subject_id, r.predicate, r.object_id,
                  r.confidence, r.last_confirmed,
                  e1.name AS subject_name, e2.name AS object_name
           FROM relationships r
           LEFT JOIN entities e1 ON r.subject_id = e1.id
           LEFT JOIN entities e2 ON r.object_id = e2.id"""
    ).fetchall()

    for row in rels:
        days = _days_since(row["last_confirmed"])
        eff = compute_effective_confidence(row["confidence"], 0.02, days)
        if eff < threshold:
            results.append(
                {
                    "id": row["id"],
                    "type": "relationship",
                    "subject_name": row["subject_name"] or row["subject_id"],
                    "predicate": row["predicate"],
                    "object": row["object_name"] or row["object_id"],
                    "effective_confidence": round(eff, 3),
                    "days_since_confirmed": round(days, 1),
                }
            )

    results.sort(key=lambda x: x["effective_confidence"])
    return results
