from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from patina.conversations import build_checkpoint_summary, get_recent_messages
from patina.store import connect, get_db_path, init_db


def _get_conn():
    db_path = get_db_path()
    init_db(db_path)
    return connect(db_path)


def recent_messages(channel: str, limit: int = 5) -> str:
    """Retrieve recent conversation messages for a channel."""
    conn = _get_conn()
    try:
        messages = get_recent_messages(conn, channel, limit)
        if not messages:
            return f"No recent messages on channel '{channel}'."
        lines = []
        for msg in messages:
            lines.append(f"- [{msg['role']}]: {msg['content']}")
        return "\n".join(lines)
    finally:
        conn.close()


def session_checkpoint(
    channel: str | None = None,
    decisions: list[str] | None = None,
    open_threads: list[str] | None = None,
    user_focus: str | None = None,
) -> str:
    """Save a session checkpoint with decisions, open threads, and context."""
    conn = _get_conn()
    try:
        summary = build_checkpoint_summary(conn, channel)
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        body = f"## Session Checkpoint — {summary['checkpoint_time']}\n\n"
        if decisions:
            body += "### Decisions made:\n"
            body += "\n".join(f"- {d}" for d in decisions) + "\n\n"
        if open_threads:
            body += "### Open threads:\n"
            body += "\n".join(f"- {t}" for t in open_threads) + "\n\n"
        if user_focus:
            body += f"### User focus/mood:\n{user_focus}\n\n"
        if summary["recent_context"]:
            body += "### Recent conversation:\n"
            for msg in summary["recent_context"][-5:]:
                preview = msg["content"][:100]
                body += f"- [{msg['role']}]: {preview}\n"

        now = datetime.now(UTC).isoformat()
        entry_id = hashlib.sha256(f"checkpoint:{today}:{now}".encode()).hexdigest()[:16]
        conn.execute(
            """INSERT INTO journal (id, date, body, entry_type, created_at)
               VALUES (?, ?, ?, 'session_end', ?)""",
            (entry_id, today, body, now),
        )
        conn.commit()

        return f"Checkpoint saved for {today}. Safe to start a fresh session."
    finally:
        conn.close()


def register(mcp):
    mcp.tool()(recent_messages)
    mcp.tool()(session_checkpoint)
