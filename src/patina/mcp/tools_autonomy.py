from __future__ import annotations

from patina.autonomy.actions import approve_action, edit_action, reject_action
from patina.autonomy.levels import (
    can_advance,
    current_level,
    is_frozen,
    level_description,
)
from patina.autonomy.tracker import get_accuracy_stats, get_anti_patterns
from patina.store import connect, get_db_path, init_db


def _get_conn(home=None):
    db_path = get_db_path(home)
    init_db(db_path)
    return connect(db_path)


def autonomy_status() -> str:
    """Check the current autonomy level, accuracy stats, and advancement status."""
    conn = _get_conn()
    try:
        level = current_level(conn)
        desc = level_description(level)
        frozen = is_frozen(conn)
        stats = get_accuracy_stats(conn)
        patterns = get_anti_patterns(conn)
        can, reason = can_advance(conn, level)

        lines = [
            f"**Level {level}** — {desc}",
            f"Frozen: {'yes' if frozen else 'no'}",
            f"Accuracy: {stats['accuracy_rate']:.0%} ({stats['correct']}/{stats['total']})",
            f"Anti-patterns: {len(patterns)}",
        ]
        if can:
            lines.append(f"Ready to advance: {reason}")
        else:
            lines.append(f"Next: {reason}")
        return "\n".join(lines)
    finally:
        conn.close()


def approve(action_id: str) -> str:
    """Approve a pending autonomous action."""
    conn = _get_conn()
    try:
        if approve_action(conn, action_id):
            return f"Approved [{action_id[:8]}]"
        return f"No pending action found matching '{action_id}'"
    finally:
        conn.close()


def reject(action_id: str) -> str:
    """Reject a pending autonomous action and freeze advancement."""
    conn = _get_conn()
    try:
        if reject_action(conn, action_id):
            return f"Rejected [{action_id[:8]}]. Advancement frozen for 7 days."
        return f"No pending action found matching '{action_id}'"
    finally:
        conn.close()


def edit(action_id: str) -> str:
    """Mark a pending autonomous action as edited (user modified it before acting)."""
    conn = _get_conn()
    try:
        if edit_action(conn, action_id):
            return f"Edited [{action_id[:8]}]"
        return f"No pending action found matching '{action_id}'"
    finally:
        conn.close()


def register(mcp):
    mcp.tool()(autonomy_status)
    mcp.tool()(approve)
    mcp.tool()(reject)
    mcp.tool()(edit)
