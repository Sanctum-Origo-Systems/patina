from __future__ import annotations

import sqlite3

from patina.autonomy.levels import advance_level, can_advance, current_level
from patina.autonomy.tracker import check_demotion, demote_level


def evaluate_autonomy(conn: sqlite3.Connection) -> dict | None:
    """Evaluate one step of the autonomy ladder. Returns change dict or None."""
    level = current_level(conn)

    should_demote, reason, items = check_demotion(conn, level)
    if should_demote:
        new_level = demote_level(conn, reason=reason, items=items)
        return {"from": level, "to": new_level, "reason": reason, "direction": "demote"}

    can, reason = can_advance(conn, level)
    if can:
        new_level = advance_level(conn)
        return {"from": level, "to": new_level, "reason": reason, "direction": "advance"}

    return None
