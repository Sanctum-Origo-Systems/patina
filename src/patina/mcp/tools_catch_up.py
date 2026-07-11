from __future__ import annotations

from patina.decisions import record_decision
from patina.priority.catch_up import catch_up as do_catch_up
from patina.priority.catch_up import priorities as do_priorities
from patina.store import connect, get_db_path, init_db


def _get_conn(home=None):
    db_path = get_db_path(home)
    init_db(db_path)
    return connect(db_path)


def _format_item(item: dict) -> str:
    age_d = item["staleness_days"]
    age = f"{age_d * 24:.0f}h" if age_d < 1 else f"{age_d:.1f}d"
    text = item["text"][:80] if item["text"] else ""
    source = item.get("source", "")
    permalink = item.get("permalink", "")

    sender = item["sender_name"]
    if permalink:
        sender = f"[{sender}]({permalink})"

    parts = [f"- **{sender}**: {text} ({age} ago, {item['quadrant']})"]
    if source and not permalink:
        parts[0] += f" via {source.replace('_', ' ')}"
    return parts[0]


def catch_up(days: int = 3) -> str:
    """Summarize recent unread messages, mentions, and items needing action."""
    result = do_catch_up(days=days)
    lines = []

    lines.append("## Needs Action Now")
    if result["needs_action"]:
        for item in result["needs_action"]:
            lines.append(_format_item(item))
    else:
        lines.append("(none)")

    lines.append("\n## New")
    if result["new"]:
        for item in result["new"]:
            lines.append(_format_item(item))
    else:
        lines.append("(none)")

    lines.append("\n## Waiting")
    if result["waiting"]:
        for item in result["waiting"]:
            lines.append(_format_item(item))
    else:
        lines.append("(none)")

    return "\n".join(lines)


def priorities(days: int = 7) -> str:
    """Rank pending items by urgency and importance into Do/Delegate/Schedule/Drop quadrants."""
    result = do_priorities(days=days)
    labels = {
        "Q1": "Q1 — Do Now",
        "Q2": "Q2 — Delegate/Decline",
        "Q3": "Q3 — Schedule",
        "Q4": "Q4 — Drop",
    }
    lines = []
    for q in ["Q1", "Q2", "Q3", "Q4"]:
        lines.append(f"## {labels[q]}")
        if result[q]:
            for item in result[q]:
                lines.append(_format_item(item))
        else:
            lines.append("(none)")
        lines.append("")
    return "\n".join(lines)


def dismiss(item_id: str) -> str:
    """Dismiss an observation — mark it as not needing action."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM observations WHERE id LIKE ?",
            (item_id + "%",),
        ).fetchone()
        if not row:
            return f"No observation found matching '{item_id}'"
        record_decision(conn, row["id"], "dismissed")
        return f"Dismissed {row['id'][:8]}"
    finally:
        conn.close()


def acknowledge(item_id: str) -> str:
    """Mark an observation as seen and acted upon."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM observations WHERE id LIKE ?",
            (item_id + "%",),
        ).fetchone()
        if not row:
            return f"No observation found matching '{item_id}'"
        record_decision(conn, row["id"], "acted")
        return f"Acknowledged {row['id'][:8]}"
    finally:
        conn.close()


def done(item_id: str) -> str:
    """Mark an observation as completed."""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM observations WHERE id LIKE ?",
            (item_id + "%",),
        ).fetchone()
        if not row:
            return f"No observation found matching '{item_id}'"
        record_decision(conn, row["id"], "acted")
        return f"Marked {row['id'][:8]} as done"
    finally:
        conn.close()


def _sanitize_fts_query(query: str) -> str:
    """Wrap query in double quotes to disable FTS5 special syntax."""
    return '"' + query.replace('"', '""') + '"'


def store_search(query: str, limit: int = 20) -> str:
    """Full-text search across all ingested messages (Slack, email, calendar)."""
    import json
    from datetime import UTC, datetime

    from patina.graph import resolve_entity_id

    conn = _get_conn()
    try:
        limit = min(limit, 50)
        seen_ids: set[str] = set()
        all_rows: list = []

        safe_query = _sanitize_fts_query(query)
        fts_rows = conn.execute(
            """SELECT o.id, o.source, o.timestamp, o.text,
                      e.name AS sender_name,
                      o.metadata
               FROM observations_fts f
               JOIN observations o ON f.rowid = o.rowid
               LEFT JOIN entities e ON o.sender_entity_id = e.id
               WHERE observations_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (safe_query, limit),
        ).fetchall()

        for row in fts_rows:
            seen_ids.add(row["id"])
            all_rows.append(row)

        entity_id = resolve_entity_id(conn, query)
        if entity_id:
            sender_limit = max(limit - len(all_rows), 10)
            sender_rows = conn.execute(
                """SELECT o.id, o.source, o.timestamp, o.text,
                          e.name AS sender_name,
                          o.metadata
                   FROM observations o
                   LEFT JOIN entities e ON o.sender_entity_id = e.id
                   WHERE o.sender_entity_id = ?
                   ORDER BY o.timestamp DESC
                   LIMIT ?""",
                (entity_id, sender_limit),
            ).fetchall()
            for row in sender_rows:
                if row["id"] not in seen_ids:
                    seen_ids.add(row["id"])
                    all_rows.append(row)

        if not all_rows:
            return f"No messages found matching '{query}'."

        lines = [f"**{len(all_rows)} results for '{query}':**\n"]
        for row in all_rows:
            try:
                dt = datetime.fromtimestamp(row["timestamp"], tz=UTC)
                date_str = dt.strftime("%Y-%m-%d")
            except Exception:
                date_str = "unknown date"

            try:
                meta = json.loads(row["metadata"] or "{}")
                channel = meta.get("channel_name", "")
            except Exception:
                channel = ""

            sender = row["sender_name"] or "unknown"
            source = row["source"] or ""
            text = (row["text"] or "")[:200]

            context_parts = [f"[{date_str}]", f"**{sender}**", f"via {source}"]
            if channel:
                context_parts.append(f"in #{channel}")

            lines.append(" ".join(context_parts))
            lines.append(f"> {text}")
            lines.append("")

        return "\n".join(lines)
    finally:
        conn.close()


def sender_watch(alias: str, reason: str | None = None) -> str:
    """Watch a person — pull all their messages on next ingest, not just DMs/mentions."""
    from datetime import UTC, datetime

    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO watched_senders"
            " (user_id, alias, reason, added_at)"
            " VALUES (?, ?, ?, ?)",
            (alias, alias, reason, datetime.now(UTC).isoformat()),
        )
        conn.commit()
        return f"Now watching {alias}."
    finally:
        conn.close()


def sender_unwatch(alias: str) -> str:
    """Stop watching a person."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM watched_senders WHERE alias = ?", (alias,))
        conn.commit()
        return f"Stopped watching {alias}."
    finally:
        conn.close()


def sender_list_watched() -> str:
    """List all watched people."""
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT alias, reason, added_at FROM watched_senders").fetchall()
        if not rows:
            return "No watched senders."
        lines = [
            f"- {r['alias']}: {r['reason'] or 'no reason'} (since {r['added_at'][:10]})"
            for r in rows
        ]
        return "\n".join(lines)
    finally:
        conn.close()


def channel_watch(
    channel_name: str,
    channel_id: str | None = None,
    reason: str | None = None,
) -> str:
    """Watch a message source (channel, folder, etc.) — pull its messages on next ingest."""
    from datetime import UTC, datetime

    conn = _get_conn()
    try:
        resolved_id = channel_id or f"unresolved:{channel_name}"
        conn.execute(
            "INSERT OR REPLACE INTO watched_channels"
            " (channel_id, channel_name, reason, added_at)"
            " VALUES (?, ?, ?, ?)",
            (resolved_id, channel_name, reason, datetime.now(UTC).isoformat()),
        )
        conn.commit()
        return f"Now watching #{channel_name}."
    finally:
        conn.close()


def channel_unwatch(channel_name: str) -> str:
    """Stop watching a message source."""
    conn = _get_conn()
    try:
        conn.execute(
            "DELETE FROM watched_channels WHERE channel_name = ?",
            (channel_name,),
        )
        conn.commit()
        return f"Stopped watching #{channel_name}."
    finally:
        conn.close()


def channel_list_watched() -> str:
    """List all watched message sources (channels, folders, etc.)."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT channel_name, reason, added_at FROM watched_channels"
        ).fetchall()
        if not rows:
            return "No watched channels."
        lines = [
            f"- #{r['channel_name']}: {r['reason'] or 'no reason'} (since {r['added_at'][:10]})"
            for r in rows
        ]
        return "\n".join(lines)
    finally:
        conn.close()


def register(mcp):
    mcp.tool()(catch_up)
    mcp.tool()(priorities)
    mcp.tool()(dismiss)
    mcp.tool()(acknowledge)
    mcp.tool()(done)
    mcp.tool()(store_search)
    mcp.tool()(sender_watch)
    mcp.tool()(sender_unwatch)
    mcp.tool()(sender_list_watched)
    mcp.tool()(channel_watch)
    mcp.tool()(channel_unwatch)
    mcp.tool()(channel_list_watched)
