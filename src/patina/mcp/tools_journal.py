from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from patina.store import connect, get_db_path, init_db


def _get_conn(home=None):
    db_path = get_db_path(home)
    init_db(db_path)
    return connect(db_path)


def journal_write(date: str, body: str) -> str:
    conn = _get_conn()
    try:
        now = datetime.now(UTC).isoformat()
        entry_id = hashlib.sha256(f"journal:{date}:{now}".encode()).hexdigest()[:16]
        conn.execute(
            """INSERT INTO journal (id, date, body, entry_type, created_at)
               VALUES (?, ?, ?, 'note', ?)""",
            (entry_id, date, body, now),
        )
        conn.commit()
        return f"Journal entry saved for {date} [{entry_id[:8]}]"
    finally:
        conn.close()


def journal_search(query: str, limit: int = 10) -> str:
    conn = _get_conn()
    try:
        rows = conn.execute(
            """SELECT j.id, j.date, j.body
               FROM journal j
               WHERE j.body LIKE ?
               ORDER BY j.date DESC
               LIMIT ?""",
            (f"%{query}%", limit),
        ).fetchall()
        if not rows:
            return f"No journal entries matching '{query}'."
        lines = []
        for r in rows:
            preview = r["body"][:100]
            lines.append(f"- [{r['date']}] {preview}")
        return "\n".join(lines)
    finally:
        conn.close()


def register(mcp):
    mcp.tool()(journal_write)
    mcp.tool()(journal_search)
