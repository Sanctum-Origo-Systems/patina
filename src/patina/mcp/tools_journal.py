from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from patina.mcp.tools_catch_up import _sanitize_fts_query
from patina.store import connect, get_db_path, init_db


def _get_conn(home=None):
    db_path = get_db_path(home)
    init_db(db_path)
    return connect(db_path)


def journal_write(date: str, body: str) -> str:
    """Save a journal entry for a given date."""
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


def journal_search(query: str = "", limit: int = 10, snippet_chars: int = 2000) -> str:
    """Search past journal entries by keyword, or retrieve recent entries.

    When *query* is empty the latest *limit* entries are returned by date
    (recency mode) — useful for session-start catch-up without guessing
    keywords.  An empty result means "no keyword match," not "no data";
    try recency mode to confirm.

    Args:
        query: Search term to match against entry bodies.  Empty string
            returns the most recent entries regardless of content.
        limit: Maximum number of entries to return.
        snippet_chars: Maximum characters per entry body. 0 for unlimited.
    """
    conn = _get_conn()
    try:
        if not query or not query.strip():
            rows = conn.execute(
                """SELECT id, date, body FROM journal
                   ORDER BY date DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            if not rows:
                return "No journal entries yet."
        else:
            fts_sql = """SELECT j.id, j.date, j.body
                         FROM journal_fts f
                         JOIN journal j ON f.rowid = j.rowid
                         WHERE journal_fts MATCH ?
                         ORDER BY j.date DESC
                         LIMIT ?"""

            and_query = _sanitize_fts_query(query, join="AND")
            rows = conn.execute(fts_sql, (and_query, limit)).fetchall()

            if not rows:
                or_query = _sanitize_fts_query(query, join="OR")
                rows = conn.execute(fts_sql, (or_query, limit)).fetchall()

            if not rows:
                return f"No journal entries matching '{query}'."

        lines = []
        for r in rows:
            body = r["body"]
            if snippet_chars and len(body) > snippet_chars:
                body = body[:snippet_chars] + "…"
            lines.append(f"- [{r['date']}] {body}")
        return "\n".join(lines)
    finally:
        conn.close()


def register(mcp):
    mcp.tool()(journal_write)
    mcp.tool()(journal_search)
