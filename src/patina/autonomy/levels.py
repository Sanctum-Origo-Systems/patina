from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

_DESCRIPTIONS = {
    0: "Observe only",
    1: "Classify + surface",
    2: "Propose actions",
    3: "Auto-triage (dismiss noise, ack FYIs)",
    4: "Draft + queue (one-tap send)",
    5: "Auto-send routine (acks, scheduling)",
    6: "Full autonomous (escalate only on novel)",
}


def _ensure_state(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS autonomy_state (
               id INTEGER PRIMARY KEY CHECK (id = 1),
               level INTEGER NOT NULL DEFAULT 0,
               frozen_until TEXT,
               last_advanced TEXT
           )"""
    )
    row = conn.execute("SELECT level FROM autonomy_state WHERE id = 1").fetchone()
    if row is None:
        conn.execute("INSERT INTO autonomy_state (id, level) VALUES (1, 0)")
    conn.commit()


def current_level(conn: sqlite3.Connection) -> int:
    _ensure_state(conn)
    row = conn.execute("SELECT level FROM autonomy_state WHERE id = 1").fetchone()
    return row["level"]


def level_description(level: int) -> str:
    return _DESCRIPTIONS.get(level, f"Unknown level {level}")


def can_advance(conn: sqlite3.Connection, current: int) -> tuple[bool, str]:
    if is_frozen(conn):
        return False, "Advancement frozen due to recent override"

    if current == 0:
        obs_count = conn.execute("SELECT COUNT(*) AS c FROM observations").fetchone()["c"]
        if obs_count > 0:
            return True, "Observations ingested"
        return False, "No observations yet — run an ingest first"

    if current == 1:
        dec_count = conn.execute("SELECT COUNT(*) AS c FROM decisions").fetchone()["c"]
        if dec_count >= 50:
            return True, f"{dec_count} decisions recorded (need 50)"
        return False, f"{dec_count}/50 decisions needed"

    if current == 2:
        row = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN action IN ('acted', 'dismissed') THEN 1 ELSE 0 END) AS confirmed
               FROM decisions"""
        ).fetchone()
        total = row["total"]
        if total < 100:
            return False, f"{total}/100 confirmed judgments needed"
        error_rate = 1.0 - ((row["confirmed"] or 0) / total)
        if error_rate < 0.05:
            return True, f"{total} judgments, {error_rate:.1%} error rate"
        return False, f"Error rate {error_rate:.1%} (need <5%)"

    if current == 3:
        row = conn.execute(
            """SELECT COUNT(*) AS c FROM action_queue
               WHERE action_type = 'draft' AND status = 'approved'"""
        ).fetchone()
        if row["c"] >= 20:
            return True, f"{row['c']} drafts confirmed"
        return False, f"{row['c']}/20 style-confirmed drafts needed"

    if current == 4:
        row = conn.execute(
            """SELECT COUNT(*) AS c FROM action_queue
               WHERE status = 'executed' AND action_type IN ('ack', 'schedule')"""
        ).fetchone()
        if row["c"] >= 50:
            return True, f"{row['c']} auto-sent with low reopen rate"
        return False, f"{row['c']}/50 auto-sent needed"

    if current == 5:
        state = conn.execute("SELECT last_advanced FROM autonomy_state WHERE id = 1").fetchone()
        if state["last_advanced"]:
            advanced_dt = datetime.fromisoformat(state["last_advanced"])
            days = (datetime.now(UTC) - advanced_dt).days
            if days >= 90:
                return True, f"{days} days at level 5"
            return False, f"{days}/90 days at level 5 needed"
        return False, "No advancement date recorded"

    return False, "Already at maximum level"


def advance_level(conn: sqlite3.Connection) -> int:
    _ensure_state(conn)
    level = current_level(conn)
    can, _ = can_advance(conn, level)
    if not can:
        return level

    new_level = level + 1
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE autonomy_state SET level = ?, last_advanced = ? WHERE id = 1",
        (new_level, now),
    )
    conn.commit()
    return new_level


def set_level(conn: sqlite3.Connection, level: int) -> None:
    _ensure_state(conn)
    now = datetime.now(UTC).isoformat()
    conn.execute(
        "UPDATE autonomy_state SET level = ?, last_advanced = ? WHERE id = 1",
        (level, now),
    )
    conn.commit()


def freeze_advancement(conn: sqlite3.Connection, days: int = 7) -> None:
    _ensure_state(conn)
    until = (datetime.now(UTC) + timedelta(days=days)).isoformat()
    conn.execute(
        "UPDATE autonomy_state SET frozen_until = ? WHERE id = 1",
        (until,),
    )
    conn.commit()


def is_frozen(conn: sqlite3.Connection) -> bool:
    _ensure_state(conn)
    row = conn.execute("SELECT frozen_until FROM autonomy_state WHERE id = 1").fetchone()
    if not row["frozen_until"]:
        return False
    frozen_until = datetime.fromisoformat(row["frozen_until"])
    return datetime.now(UTC) < frozen_until
