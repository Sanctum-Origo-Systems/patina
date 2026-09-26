from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime

from patina.autonomy.levels import current_level, set_level


def get_accuracy_stats(conn: sqlite3.Connection, *, since_days: int = 30) -> dict:
    cutoff = (datetime.now(UTC) - __import__("datetime").timedelta(days=since_days)).isoformat()
    row = conn.execute(
        """SELECT
               COUNT(*) AS total,
               SUM(CASE WHEN action IN ('acted', 'dismissed') THEN 1 ELSE 0 END) AS correct,
               SUM(CASE WHEN action NOT IN ('acted', 'dismissed') THEN 1 ELSE 0 END) AS incorrect
           FROM decisions WHERE acted_at >= ?""",
        (cutoff,),
    ).fetchone()

    total = row["total"]
    if total == 0:
        return {
            "total": 0,
            "correct": 0,
            "incorrect": 0,
            "accuracy_rate": 0.5,
            "error_rate": 0.0,
        }

    correct = row["correct"] or 0
    incorrect = row["incorrect"] or 0
    return {
        "total": total,
        "correct": correct,
        "incorrect": incorrect,
        "accuracy_rate": correct / total,
        "error_rate": incorrect / total,
    }


def get_draft_acceptance_rate(conn: sqlite3.Connection, *, since_days: int = 30) -> float:
    cutoff = (datetime.now(UTC) - __import__("datetime").timedelta(days=since_days)).isoformat()
    row = conn.execute(
        """SELECT
               COUNT(*) AS total,
               SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) AS accepted
           FROM action_queue WHERE action_type = 'draft' AND created_at >= ?""",
        (cutoff,),
    ).fetchone()
    if row["total"] == 0:
        return 0.0
    return (row["accepted"] or 0) / row["total"]


def get_override_count(conn: sqlite3.Connection, *, since_days: int = 7) -> int:
    cutoff = (datetime.now(UTC) - __import__("datetime").timedelta(days=since_days)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM action_queue WHERE status = 'rejected' AND resolved_at >= ?",
        (cutoff,),
    ).fetchone()
    return row["c"]


def check_demotion(conn: sqlite3.Connection, current: int) -> tuple[bool, str | None, list[dict]]:
    if current <= 1:
        return False, None, []

    if current == 3:
        stats = get_accuracy_stats(conn, since_days=30)
        if stats["total"] >= 10 and stats["error_rate"] > 0.05:
            cutoff = (datetime.now(UTC) - __import__("datetime").timedelta(days=30)).isoformat()
            rows = conn.execute(
                """SELECT d.id, d.action, o.text
                   FROM decisions d
                   LEFT JOIN observations o ON d.observation_id = o.id
                   WHERE d.acted_at >= ?
                   AND d.action NOT IN ('acted', 'dismissed')
                   LIMIT 10""",
                (cutoff,),
            ).fetchall()
            items = [
                {
                    "id": r["id"],
                    "pattern_type": "high_error_rate",
                    "text_keywords": (r["text"] or "").split()[:5],
                    "wrong_action": r["action"],
                    "correct_action": "acted",
                }
                for r in rows
            ]
            return True, f"Error rate {stats['error_rate']:.1%} exceeds 5% threshold", items

    if current == 4:
        cutoff = (datetime.now(UTC) - __import__("datetime").timedelta(days=30)).isoformat()
        row = conn.execute(
            """SELECT
                   COUNT(*) AS total,
                   SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) AS accepted
               FROM action_queue WHERE action_type = 'draft' AND created_at >= ?""",
            (cutoff,),
        ).fetchone()
        total = row["total"]
        accepted = row["accepted"] or 0
        rate = accepted / total if total else 0.0
        if total >= 20 and rate < 0.80:
            rows = conn.execute(
                """SELECT id FROM action_queue
                   WHERE action_type = 'draft' AND status = 'rejected' AND created_at >= ?
                   LIMIT 10""",
                (cutoff,),
            ).fetchall()
            items = [
                {
                    "id": r["id"],
                    "pattern_type": "low_draft_acceptance",
                    "wrong_action": "draft",
                    "correct_action": "manual_compose",
                }
                for r in rows
            ]
            return True, f"Draft acceptance {rate:.0%} below 80%", items

    if current == 5:
        cutoff = (datetime.now(UTC) - __import__("datetime").timedelta(days=30)).isoformat()
        row = conn.execute(
            """SELECT COUNT(*) AS c FROM action_queue
               WHERE status = 'executed' AND action_type IN ('ack', 'schedule')
               AND created_at >= ?""",
            (cutoff,),
        ).fetchone()
        total = row["c"]
        rows_rejected = conn.execute(
            """SELECT id, action_type FROM action_queue
               WHERE status = 'rejected' AND action_type IN ('ack', 'schedule')
               AND created_at >= ?""",
            (cutoff,),
        ).fetchall()
        reopens = len(rows_rejected)
        if total >= 50 and reopens / max(total, 1) > 0.02:
            items = [
                {
                    "id": r["id"],
                    "pattern_type": "high_reopen_rate",
                    "wrong_action": r["action_type"],
                    "correct_action": "manual_review",
                }
                for r in rows_rejected[:10]
            ]
            return True, f"Reopen rate {reopens / total:.1%} exceeds 2%", items

    return False, None, []


def demote_level(
    conn: sqlite3.Connection,
    *,
    reason: str,
    items: list[dict] | None = None,
) -> int:
    level = current_level(conn)
    new_level = max(level - 1, 0)
    set_level(conn, new_level)

    now = datetime.now(UTC).isoformat()
    for item in items or []:
        pat_id = hashlib.sha256(f"ap:{reason}:{item.get('id', '')}:{now}".encode()).hexdigest()[:16]
        conn.execute(
            """INSERT OR IGNORE INTO anti_patterns
                   (id, from_level, pattern_type, text_keywords, sender_tier,
                    context, wrong_action, correct_action, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pat_id,
                level,
                item.get("pattern_type", "error"),
                json.dumps(item.get("text_keywords", [])),
                item.get("sender_tier"),
                json.dumps(item.get("context", {})),
                item.get("wrong_action", "unknown"),
                item.get("correct_action", "unknown"),
                now,
            ),
        )
    conn.commit()
    return new_level


def get_anti_patterns(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM anti_patterns ORDER BY created_at DESC").fetchall()
    return [
        {
            "id": r["id"],
            "from_level": r["from_level"],
            "pattern_type": r["pattern_type"],
            "text_keywords": json.loads(r["text_keywords"]) if r["text_keywords"] else [],
            "sender_tier": r["sender_tier"],
            "context": json.loads(r["context"]) if r["context"] else {},
            "wrong_action": r["wrong_action"],
            "correct_action": r["correct_action"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def matches_anti_pattern(item: dict, anti_patterns: list[dict]) -> bool:
    item_text = (item.get("text") or "").lower()
    for pat in anti_patterns:
        keywords = pat.get("text_keywords", [])
        if keywords and any(kw.lower() in item_text for kw in keywords):
            return True
    return False


def should_auto_act(conn: sqlite3.Connection, item: dict, current: int) -> bool:
    patterns = get_anti_patterns(conn)
    if matches_anti_pattern(item, patterns):
        return False
    confidence = item.get("confidence", 0.0)
    return confidence >= 0.8 and item.get("autonomy_level", 99) <= current


def clear_anti_pattern(conn: sqlite3.Connection, pattern_id: str) -> bool:
    cur = conn.execute("DELETE FROM anti_patterns WHERE id = ?", (pattern_id,))
    conn.commit()
    return cur.rowcount > 0
