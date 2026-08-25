from __future__ import annotations

import json

from patina.autonomy.actions import propose_action
from patina.store import connect, get_db_path, init_db
from patina.style.draft import load_style_profile


def _get_conn(home=None):
    db_path = get_db_path(home)
    init_db(db_path)
    return connect(db_path)


def _find_entity(conn, name):
    return conn.execute(
        "SELECT id, name FROM entities WHERE LOWER(name) LIKE ?",
        (f"%{name.lower()}%",),
    ).fetchone()


def style_show(entity_name: str) -> str:
    """Show a person's communication style profile."""
    conn = _get_conn()
    try:
        row = _find_entity(conn, entity_name)
        if not row:
            return f"No entity found matching '{entity_name}'"
        profile = load_style_profile(conn, row["id"])
        if not profile:
            return f"No style profile for {row['name']}."
        data = json.loads(profile)
        lines = [f"Style profile for **{row['name']}**:"]
        for key, val in data.items():
            lines.append(f"- {key}: {val}")
        return "\n".join(lines)
    finally:
        conn.close()


def draft_reply(to: str, context: str, draft_text: str = "") -> str:
    """Return style context for drafting a reply — the calling agent generates the actual text."""
    conn = _get_conn()
    try:
        row = _find_entity(conn, to)
        if not row:
            return f"No entity found matching '{to}'"

        recipient_profile = conn.execute(
            "SELECT profile FROM style_profiles WHERE entity_id = ?",
            (row["id"],),
        ).fetchone()
        profile_text = (
            recipient_profile["profile"] if recipient_profile else "no style profile available"
        )

        owner_id = None
        try:
            from patina.owner import get_owner_entity_id

            owner_id = get_owner_entity_id(conn)
        except Exception:
            pass

        user_profile = None
        if owner_id:
            user_row = conn.execute(
                "SELECT profile FROM style_profiles WHERE entity_id = ?",
                (owner_id,),
            ).fetchone()
            user_profile = user_row["profile"] if user_row else None

        lines = [
            f"**Draft a reply to {row['name']}.**\n",
            f"Context: {context}\n",
            f"Their communication style: {profile_text}",
        ]
        if user_profile:
            lines.append(f"Your communication style: {user_profile}")
        lines.append("\nMatch their formality, length, and tone. Be concise.")

        obs = conn.execute(
            """SELECT id FROM observations
               WHERE sender_entity_id = ?
               ORDER BY timestamp DESC LIMIT 1""",
            (row["id"],),
        ).fetchone()

        propose_action(
            conn,
            action_type="draft_reply",
            target_observation_id=obs["id"] if obs else None,
            target_entity_id=row["id"],
            payload={"context": context, **({"draft_text": draft_text} if draft_text else {})},
            confidence=0.5,
            autonomy_level=1,
        )

        return "\n".join(lines)
    finally:
        conn.close()


def register(mcp):
    mcp.tool()(style_show)
    mcp.tool()(draft_reply)
