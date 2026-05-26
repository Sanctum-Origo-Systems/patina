from __future__ import annotations

from patina.graph import upsert_entity
from patina.mcp.tools_beliefs import beliefs, contradictions, relationships, stale
from patina.models import Entity
from patina.store import init_db


def test_beliefs_returns_string(db_path, db_conn, tmp_path):
    init_db(db_path)
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    db_conn.close()

    result = beliefs()
    assert isinstance(result, str)
    assert "Alice" in result


def test_stale_returns_string(db_path, tmp_path):
    init_db(db_path)
    result = stale()
    assert isinstance(result, str)


def test_contradictions_returns_string(db_path, tmp_path):
    init_db(db_path)
    result = contradictions()
    assert isinstance(result, str)


def test_relationships_returns_string(db_path, tmp_path):
    init_db(db_path)
    result = relationships()
    assert isinstance(result, str)
