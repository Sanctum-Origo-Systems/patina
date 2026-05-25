from __future__ import annotations

import sqlite3

from patina.llm import LLMPort


def load_style_profile(conn: sqlite3.Connection, entity_id: str) -> str | None:
    row = conn.execute(
        "SELECT profile FROM style_profiles WHERE entity_id = ?",
        (entity_id,),
    ).fetchone()
    if row is None:
        return None
    return row["profile"]


def generate_draft(
    *,
    context: str,
    recipient_entity_id: str,
    llm: LLMPort,
    conn: sqlite3.Connection,
) -> str:
    recipient_profile = load_style_profile(conn, recipient_entity_id) or "{}"

    row = conn.execute(
        "SELECT name FROM entities WHERE id = ?",
        (recipient_entity_id,),
    ).fetchone()
    recipient_name = row["name"] if row else "Unknown"

    user_rows = conn.execute("SELECT entity_id, profile FROM style_profiles LIMIT 1").fetchone()
    user_style = user_rows["profile"] if user_rows else "{}"

    style_prompt = (
        f"Recipient: {recipient_name}\n"
        f"Recipient style profile: {recipient_profile}\n"
        f"Your communication style: {user_style}\n"
    )

    return llm.draft(context, style_prompt, recipient_profile)
