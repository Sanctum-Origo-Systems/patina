from __future__ import annotations

import json

from patina.llm import MockLLM
from patina.store import connect, get_db_path, init_db
from patina.style.draft import generate_draft, load_style_profile


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


def draft_reply(to: str, context: str) -> str:
    conn = _get_conn()
    try:
        row = _find_entity(conn, to)
        if not row:
            return f"No entity found matching '{to}'"
        llm = MockLLM()
        text = generate_draft(
            context=context,
            recipient_entity_id=row["id"],
            llm=llm,
            conn=conn,
        )
        return f"**Draft to {row['name']}:**\n\n{text}"
    finally:
        conn.close()


def register(mcp):
    mcp.tool()(style_show)
    mcp.tool()(draft_reply)
