from __future__ import annotations

from patina.graph import upsert_entity
from patina.mcp.tools_style import draft_reply, style_show
from patina.models import Entity
from patina.store import init_db


def test_style_show_no_profile(db_path, db_conn, tmp_path):
    init_db(db_path)
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    db_conn.close()

    result = style_show("Alice")
    assert isinstance(result, str)
    assert "No style profile" in result or "Alice" in result


def test_draft_reply_returns_string(db_path, db_conn, tmp_path):
    init_db(db_path)
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Bob"))
    db_conn.close()

    result = draft_reply("Bob", "follow up on project")
    assert isinstance(result, str)
    assert "Bob" in result
