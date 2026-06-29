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


def register(mcp):
    mcp.tool()(catch_up)
    mcp.tool()(priorities)
    mcp.tool()(dismiss)
    mcp.tool()(acknowledge)
    mcp.tool()(done)
