from __future__ import annotations

import time

from patina.beliefs.relationships import get_relationship_map
from patina.graph import insert_observation, upsert_entity
from patina.models import Entity, Observation
from patina.owner import (
    get_owner_entity_id,
    get_owner_user_ids,
    is_owner_entity,
    mark_entity_as_owner,
)


def test_get_owner_user_ids_empty(tmp_path):
    result = get_owner_user_ids(tmp_path)
    assert result == []


def test_get_owner_user_ids_from_config(tmp_path):
    import yaml

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"owner": {"user_ids": ["U001", "U002"]}}))
    result = get_owner_user_ids(tmp_path)
    assert result == ["U001", "U002"]


def test_mark_and_check_owner(db_conn):
    e = Entity(id="e1", type="person", name="Me")
    upsert_entity(db_conn, e)
    assert is_owner_entity(db_conn, "e1") is False

    mark_entity_as_owner(db_conn, "e1")
    assert is_owner_entity(db_conn, "e1") is True


def test_get_owner_entity_id(db_conn):
    assert get_owner_entity_id(db_conn) is None

    e = Entity(id="e1", type="person", name="Me")
    upsert_entity(db_conn, e)
    mark_entity_as_owner(db_conn, "e1")

    assert get_owner_entity_id(db_conn) == "e1"


def test_relationship_map_excludes_owner(db_conn):
    owner = Entity(id="owner1", type="person", name="Me")
    upsert_entity(db_conn, owner)
    mark_entity_as_owner(db_conn, "owner1")

    contact = Entity(id="contact1", type="person", name="Alice")
    upsert_entity(db_conn, contact)

    now = time.time()
    for i, eid in enumerate(["owner1", "contact1"]):
        obs = Observation(
            id=f"o{i}",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=now - i * 3600,
            sender_entity_id=eid,
            text=f"msg from {eid}",
        )
        insert_observation(db_conn, obs)

    rels = get_relationship_map(db_conn)
    names = [r["name"] for r in rels]
    assert "Me" not in names
    assert "Alice" in names


def test_owner_not_in_default_entity(db_conn):
    assert is_owner_entity(db_conn, "nonexistent") is False
