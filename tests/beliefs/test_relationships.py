from __future__ import annotations

import time

from patina.beliefs.relationships import (
    _classify_activity,
    compute_interaction_stats,
    compute_trust_level,
    get_relationship_map,
)
from patina.decisions import record_decision
from patina.graph import insert_observation, upsert_entity
from patina.models import Entity, Observation


def _add_obs(conn, obs_id, sender_id, text="hello", ts=None):
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


def test_stats_computed(db_conn):
    e = Entity(id="e1", type="person", name="Alice")
    upsert_entity(db_conn, e)
    now = time.time()
    _add_obs(db_conn, "o1", "e1", ts=now - 86400)
    _add_obs(db_conn, "o2", "e1", ts=now - 3600)
    _add_obs(db_conn, "o3", "e1", ts=now)

    stats = compute_interaction_stats(db_conn, "e1")
    assert stats["message_count"] == 3
    assert stats["days_since_last"] is not None
    assert stats["avg_messages_per_week"] > 0


def test_classify_active():
    assert _classify_activity(5.0, 2.0) == "active"


def test_classify_low_frequency():
    assert _classify_activity(0.5, 10.0) == "low-frequency"


def test_classify_dormant():
    assert _classify_activity(0.1, 90.0) == "dormant"


def test_classify_dormant_none():
    assert _classify_activity(0.0, None) == "dormant"


def test_trust_uses_act_rate_not_recency(db_conn):
    e = Entity(id="e1", type="person", name="Alice")
    upsert_entity(db_conn, e)

    now = time.time()
    _add_obs(db_conn, "o1", "e1", ts=now - 90 * 86400)
    record_decision(db_conn, "o1", "acted")

    trust = compute_trust_level(db_conn, "e1")
    assert trust > 0.5


def test_high_trust_dormant_valid(db_conn):
    e = Entity(id="e1", type="person", name="Alice")
    upsert_entity(db_conn, e)

    old_ts = time.time() - 90 * 86400
    _add_obs(db_conn, "o1", "e1", ts=old_ts)
    record_decision(db_conn, "o1", "acted")

    trust = compute_trust_level(db_conn, "e1")
    stats = compute_interaction_stats(db_conn, "e1")
    activity = _classify_activity(stats["avg_messages_per_week"], stats["days_since_last"])

    assert trust > 0.5
    assert activity == "dormant"


def test_relationship_map_top_n(db_conn):
    for i in range(5):
        eid = f"e{i}"
        upsert_entity(db_conn, Entity(id=eid, type="person", name=f"Person {i}"))
        _add_obs(db_conn, f"o{i}", eid)

    results = get_relationship_map(db_conn, top_n=3)
    assert len(results) <= 3


def test_empty_graph_empty_map(db_conn):
    results = get_relationship_map(db_conn)
    assert results == []
