from __future__ import annotations

from patina.autonomy.actions import approve_action, edit_action, reject_action
from patina.autonomy.levels import (
    DOMAINS,
    can_advance,
    current_level,
    is_frozen,
    level_description,
)
from patina.store import connect, get_db_path, init_db


def _get_conn(home=None):
    db_path = get_db_path(home)
    init_db(db_path)
    return connect(db_path)


def autonomy_status() -> str:
    """Check the autonomy level, frozen state, and advancement status per domain."""
    conn = _get_conn()
    try:
        lines = [
            "| Domain | Level | Description | Frozen | Advance |",
            "|--------|-------|-------------|--------|---------|",
        ]
        for domain in DOMAINS:
            level = current_level(conn, domain)
            desc = level_description(level)
            frozen = is_frozen(conn, domain)
            can, reason = can_advance(conn, level, domain)
            advance = f"Ready: {reason}" if can else reason
            lines.append(
                f"| {domain} | {level} | {desc} | {'yes' if frozen else 'no'} | {advance} |"
            )
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
