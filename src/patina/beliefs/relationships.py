from __future__ import annotations

import sqlite3
import time


def compute_interaction_stats(conn: sqlite3.Connection, entity_id: str) -> dict:
    rows = conn.execute(
        """SELECT timestamp FROM observations
           WHERE sender_entity_id = ?
              OR text LIKE '%' || ? || '%'
           ORDER BY timestamp""",
        (entity_id, entity_id),
    ).fetchall()

    if not rows:
        return {
            "message_count": 0,
            "last_interaction": None,
            "first_interaction": None,
            "avg_messages_per_week": 0.0,
            "days_since_last": None,
        }

    timestamps = [r["timestamp"] for r in rows]
    first = timestamps[0]
    last = timestamps[-1]
    now = time.time()

    span_weeks = max((last - first) / (7 * 86400), 1.0)
    avg_per_week = len(timestamps) / span_weeks

    return {
        "message_count": len(timestamps),
        "last_interaction": last,
        "first_interaction": first,
        "avg_messages_per_week": round(avg_per_week, 2),
        "days_since_last": round((now - last) / 86400, 1),
    }


def compute_trust_level(conn: sqlite3.Connection, entity_id: str) -> float:
    """Compute trust score blending decision history + behavioral graph.

    Returns float in [0.0, 1.0].
    """
    scores = []
    weights = []

    row = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN d.action = 'acted' THEN 1 ELSE 0 END) AS acted
           FROM decisions d
           JOIN observations o ON d.observation_id = o.id
           WHERE o.sender_entity_id = ?""",
        (entity_id,),
    ).fetchone()

    if row["total"] > 0:
        decision_score = round((row["acted"] or 0) / row["total"], 3)
        scores.append(decision_score)
        weights.append(0.4)

    behavioral = conn.execute(
        """SELECT predicate, object, confidence
           FROM claims
           WHERE subject_id = ? AND predicate LIKE 'behavioral:%'""",
        (entity_id,),
    ).fetchall()

    if behavioral:
        behavioral_score = _score_behavioral_claims(behavioral)
        scores.append(behavioral_score)
        weights.append(0.4)

    rel_rows = conn.execute(
        """SELECT predicate, confidence
           FROM relationships
           WHERE subject_id = ? OR object_id = ?""",
        (entity_id, entity_id),
    ).fetchall()

    if rel_rows:
        rel_score = _score_relationship_predicates(rel_rows)
        scores.append(rel_score)
        weights.append(0.2)

    if not scores:
        return 0.5

    total_weight = sum(weights)
    return round(
        sum(s * w for s, w in zip(scores, weights)) / total_weight, 3
    )


_HIGH_TRUST_KEYWORDS = {
    "proactive", "responsive", "transparent", "helpful",
    "collaborative", "consistent", "reliable", "follows up",
    "delivers", "on time",
}
_LOW_TRUST_KEYWORDS = {
    "escalates", "pressures", "demands", "avoids", "delays",
    "inconsistent", "unreliable", "misses", "late", "ignores",
}


def _score_behavioral_claims(claims: list) -> float:
    score_sum = 0.0
    count = 0.0

    for claim in claims:
        predicate = claim["predicate"].lower()
        obj = claim["object"].lower()
        confidence = claim["confidence"]

        base = 0.5
        if "commitment" in predicate:
            base = 0.75

        positive_hits = sum(1 for kw in _HIGH_TRUST_KEYWORDS if kw in obj)
        negative_hits = sum(1 for kw in _LOW_TRUST_KEYWORDS if kw in obj)

        if positive_hits > 0 and negative_hits == 0:
            base = min(base + 0.15 * positive_hits, 0.9)
        elif negative_hits > 0 and positive_hits == 0:
            base = max(base - 0.15 * negative_hits, 0.1)

        score_sum += base * confidence
        count += confidence

    if count == 0:
        return 0.5

    return round(score_sum / count, 3)


_PREDICATE_SCORES = {
    "manages": 0.8,
    "reports_to": 0.75,
    "collaborates_with": 0.7,
    "works_with": 0.65,
    "watches": 0.6,
    "mentors": 0.8,
    "mentored_by": 0.75,
}


def _score_relationship_predicates(rels: list) -> float:
    if not rels:
        return 0.5

    total = sum(
        _PREDICATE_SCORES.get(r["predicate"], 0.5) * r["confidence"]
        for r in rels
    )
    weight = sum(r["confidence"] for r in rels)

    return round(total / weight, 3) if weight > 0 else 0.5


def _classify_activity(avg_per_week: float, days_since_last: float | None) -> str:
    if days_since_last is None:
        return "dormant"
    if days_since_last > 60:
        return "dormant"
    if avg_per_week < 1.0 or days_since_last > 7:
        return "low-frequency"
    return "active"


def get_relationship_map(conn: sqlite3.Connection, *, top_n: int = 20) -> list[dict]:
    entities = conn.execute(
        "SELECT id, name FROM entities WHERE type = 'person' AND is_owner = 0"
    ).fetchall()

    results: list[dict] = []
    for ent in entities:
        stats = compute_interaction_stats(conn, ent["id"])
        if stats["message_count"] == 0:
            continue

        trust = compute_trust_level(conn, ent["id"])
        activity = _classify_activity(stats["avg_messages_per_week"], stats["days_since_last"])

        top_beh = conn.execute(
            """SELECT predicate, object FROM claims
               WHERE subject_id = ? AND predicate LIKE 'behavioral:%'
               ORDER BY confidence DESC LIMIT 1""",
            (ent["id"],),
        ).fetchone()
        behavioral_note = top_beh["object"][:80] if top_beh else None

        results.append(
            {
                "entity_id": ent["id"],
                "name": ent["name"],
                "trust_level": trust,
                "activity_status": activity,
                "avg_per_week": stats["avg_messages_per_week"],
                "days_since_last": stats["days_since_last"],
                "message_count": stats["message_count"],
                "behavioral_note": behavioral_note,
            }
        )

    results.sort(key=lambda x: x["trust_level"], reverse=True)
    return results[:top_n]
