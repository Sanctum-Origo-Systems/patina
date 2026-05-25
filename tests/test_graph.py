from __future__ import annotations

from patina.graph import (
    count_entities,
    count_observations,
    get_entity,
    insert_claim,
    insert_observation,
    upsert_entity,
    upsert_relationship,
)
from patina.models import Claim, Entity, Observation, Relationship


def test_upsert_entity_inserts(db_conn):
    e = Entity(id="e1", type="person", name="Alice")
    upsert_entity(db_conn, e)
    result = get_entity(db_conn, "e1")
    assert result is not None
    assert result.name == "Alice"


def test_upsert_entity_updates_last_seen(db_conn):
    e1 = Entity(id="e1", type="person", name="Alice", last_seen="2024-01-01")
    upsert_entity(db_conn, e1)

    e2 = Entity(id="e1", type="person", name="Alice Updated", last_seen="2024-06-01")
    upsert_entity(db_conn, e2)

    result = get_entity(db_conn, "e1")
    assert result.last_seen == "2024-06-01"
    assert result.name == "Alice Updated"


def test_insert_observation_new(db_conn):
    obs = Observation(
        id="o1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=None,
        text="hi",
    )
    assert insert_observation(db_conn, obs) is True


def test_insert_observation_duplicate(db_conn):
    obs = Observation(
        id="o1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=None,
        text="hi",
    )
    insert_observation(db_conn, obs)
    assert insert_observation(db_conn, obs) is False


def test_count_entities_all(db_conn):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    upsert_entity(db_conn, Entity(id="e2", type="topic", name="general"))
    assert count_entities(db_conn) == 2


def test_count_entities_by_type(db_conn):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    upsert_entity(db_conn, Entity(id="e2", type="topic", name="general"))
    assert count_entities(db_conn, "person") == 1
    assert count_entities(db_conn, "topic") == 1


def test_count_observations(db_conn):
    obs = Observation(
        id="o1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=None,
        text="hi",
    )
    insert_observation(db_conn, obs)
    assert count_observations(db_conn) == 1


def test_upsert_relationship(db_conn):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    upsert_entity(db_conn, Entity(id="e2", type="project", name="Atlas"))
    rel = Relationship(id="r1", subject_id="e1", predicate="works-on", object_id="e2")
    upsert_relationship(db_conn, rel)
    row = db_conn.execute("SELECT * FROM relationships WHERE id = 'r1'").fetchone()
    assert row is not None
    assert row["predicate"] == "works-on"


def test_insert_claim(db_conn):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    claim = Claim(id="c1", subject_id="e1", predicate="owns", object="ProjectX", confidence=0.8)
    insert_claim(db_conn, claim)
    row = db_conn.execute("SELECT * FROM claims WHERE id = 'c1'").fetchone()
    assert row is not None
    assert row["confidence"] == 0.8
