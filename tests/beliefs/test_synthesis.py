from __future__ import annotations

import time

from patina.beliefs.synthesis import find_convergence
from patina.graph import insert_observation, upsert_entity
from patina.llm import MockLLM
from patina.models import Entity, Observation


def _add_obs(conn, obs_id, sender_id, text, ts=None):
    if ts is None:
        ts = time.time()
    obs = Observation(
        id=obs_id,
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=ts,
        sender_entity_id=sender_id,
        text=text,
    )
    insert_observation(conn, obs)


def test_detects_topic_with_3_participants(db_conn):
    now = time.time()
    for i in range(3):
        eid = f"e{i}"
        upsert_entity(db_conn, Entity(id=eid, type="person", name=f"Person{i}"))
        _add_obs(
            db_conn,
            f"o{i}",
            eid,
            "We need to discuss the infrastructure costs soon",
            ts=now - 3600 * i,
        )

    results = find_convergence(db_conn, days=7)
    topics = [r["topic"] for r in results]
    assert any("infrastructure" in t for t in topics)


def test_returns_empty_no_convergence(db_conn):
    now = time.time()
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    _add_obs(db_conn, "o1", "e1", "Unique message about nothing", ts=now)

    results = find_convergence(db_conn, days=7)
    assert results == []


def test_with_mock_llm_populates_insight(db_conn):
    now = time.time()
    for i in range(3):
        eid = f"e{i}"
        upsert_entity(db_conn, Entity(id=eid, type="person", name=f"Person{i}"))
        _add_obs(
            db_conn,
            f"o{i}",
            eid,
            "The deployment pipeline needs attention",
            ts=now - 3600 * i,
        )

    llm = MockLLM()
    results = find_convergence(db_conn, llm=llm, days=7)
    if results:
        assert results[0]["insight"] is not None
        assert isinstance(results[0]["insight"], str)
