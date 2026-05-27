from __future__ import annotations

import hashlib
import sqlite3
import time
from datetime import UTC, datetime


def store_exchange(
    conn: sqlite3.Connection,
    channel: str,
    user_id: str,
    role: str,
    content: str,
    timestamp: float | None = None,
) -> None:
    ts = timestamp or time.time()
    exchange_id = hashlib.sha256(f"{channel}:{user_id}:{role}:{ts}".encode()).hexdigest()[:16]
    conn.execute(
        """INSERT OR IGNORE INTO conversations
               (id, channel, user_id, role, content, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (exchange_id, channel, user_id, role, content, ts),
    )
    conn.commit()


def get_recent_messages(conn: sqlite3.Connection, channel: str, limit: int = 5) -> list[dict]:
    rows = conn.execute(
        """SELECT role, content, timestamp FROM conversations
           WHERE channel = ?
           ORDER BY timestamp DESC
           LIMIT ?""",
        (channel, limit),
    ).fetchall()
    return [
        {"role": r["role"], "content": r["content"], "timestamp": r["timestamp"]}
        for r in reversed(rows)
    ]


def prune_conversations(conn: sqlite3.Connection, max_age_days: int = 30) -> int:
    cutoff = time.time() - (max_age_days * 86400)
    cur = conn.execute("DELETE FROM conversations WHERE timestamp < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def build_checkpoint_summary(conn: sqlite3.Connection, channel: str | None = None) -> dict:
    recent_context: list[dict] = []
    if channel:
        recent_context = get_recent_messages(conn, channel, limit=10)

    return {
        "recent_context": recent_context,
        "checkpoint_time": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    }
