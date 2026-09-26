from __future__ import annotations

from patina.autonomy.evaluate import evaluate_autonomy
from patina.autonomy.levels import current_level, freeze_advancement, set_level
from patina.autonomy.tracker import get_anti_patterns
from patina.decisions import record_decision
from patina.graph import insert_observation
from patina.models import Observation


def _insert_obs(conn, obs_id="o1", text="hello"):
    obs = Observation(
        id=obs_id,
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=None,
        text=text,
    )
    insert_observation(conn, obs)


def test_advance_0_to_1(db_conn):
    _insert_obs(db_conn)
    result = evaluate_autonomy(db_conn)
    assert result is not None
    assert result["from"] == 0
    assert result["to"] == 1
    assert result["direction"] == "advance"
    assert current_level(db_conn) == 1


def test_no_change_without_observations(db_conn):
    result = evaluate_autonomy(db_conn)
    assert result is None
    assert current_level(db_conn) == 0


def test_frozen_blocks_advancement(db_conn):
    _insert_obs(db_conn)
    freeze_advancement(db_conn)
    result = evaluate_autonomy(db_conn)
    assert result is None
    assert current_level(db_conn) == 0


def test_demotion_at_level_3(db_conn):
    set_level(db_conn, 3)
    for i in range(12):
        _insert_obs(db_conn, obs_id=f"o{i}", text=f"msg {i}")
        action = "deferred" if i < 3 else "acted"
        record_decision(db_conn, f"o{i}", action)

    result = evaluate_autonomy(db_conn)
    assert result is not None
    assert result["from"] == 3
    assert result["to"] == 2
    assert result["direction"] == "demote"
    assert current_level(db_conn) == 2


def test_demotion_records_anti_patterns(db_conn):
    set_level(db_conn, 3)
    for i in range(12):
        _insert_obs(db_conn, obs_id=f"o{i}", text=f"msg {i}")
        action = "deferred" if i < 3 else "acted"
        record_decision(db_conn, f"o{i}", action)

    evaluate_autonomy(db_conn)
    patterns = get_anti_patterns(db_conn)
    assert isinstance(patterns, list)


def test_only_one_level_change_per_call(db_conn):
    _insert_obs(db_conn)
    result = evaluate_autonomy(db_conn)
    assert result["from"] == 0
    assert result["to"] == 1
    assert abs(result["to"] - result["from"]) == 1


def test_demotion_checked_before_advancement(db_conn):
    set_level(db_conn, 3)
    for i in range(12):
        _insert_obs(db_conn, obs_id=f"o{i}", text=f"msg {i}")
        action = "deferred" if i < 3 else "acted"
        record_decision(db_conn, f"o{i}", action)

    result = evaluate_autonomy(db_conn)
    assert result["direction"] == "demote"
