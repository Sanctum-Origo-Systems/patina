from __future__ import annotations

from patina.autonomy.levels import current_level, freeze_advancement, set_level
from patina.decisions import record_decision
from patina.graph import insert_observation
from patina.models import Observation
from patina.scheduler import heartbeat_once
from patina.store import connect, get_db_path, init_db


def _setup_db(tmp_path):
    db_path = get_db_path(tmp_path)
    init_db(db_path)
    return db_path


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


def test_heartbeat_advances_0_to_1(tmp_path):
    db_path = _setup_db(tmp_path)
    conn = connect(db_path)
    try:
        _insert_obs(conn)
    finally:
        conn.close()

    result = heartbeat_once(home=tmp_path)
    assert "autonomy" in result["tasks_run"]
    assert result.get("autonomy") is not None
    assert result["autonomy"]["from"] == 0
    assert result["autonomy"]["to"] == 1
    assert result["autonomy"]["direction"] == "advance"

    conn = connect(db_path)
    try:
        assert current_level(conn) == 1
    finally:
        conn.close()


def test_heartbeat_frozen_no_advance(tmp_path):
    db_path = _setup_db(tmp_path)
    conn = connect(db_path)
    try:
        _insert_obs(conn)
        freeze_advancement(conn)
    finally:
        conn.close()

    result = heartbeat_once(home=tmp_path)
    assert "autonomy" in result["tasks_run"]
    assert result.get("autonomy") is None

    conn = connect(db_path)
    try:
        assert current_level(conn) == 0
    finally:
        conn.close()


def test_heartbeat_demotes_on_high_error_rate(tmp_path):
    db_path = _setup_db(tmp_path)
    conn = connect(db_path)
    try:
        set_level(conn, 3)
        for i in range(12):
            _insert_obs(conn, obs_id=f"o{i}", text=f"msg {i}")
            action = "deferred" if i < 3 else "acted"
            record_decision(conn, f"o{i}", action)
    finally:
        conn.close()

    result = heartbeat_once(home=tmp_path)
    assert "autonomy" in result["tasks_run"]
    assert result["autonomy"]["direction"] == "demote"
    assert result["autonomy"]["from"] == 3
    assert result["autonomy"]["to"] == 2

    conn = connect(db_path)
    try:
        assert current_level(conn) == 2
    finally:
        conn.close()


def test_heartbeat_autonomy_result_in_dict(tmp_path):
    db_path = _setup_db(tmp_path)
    conn = connect(db_path)
    try:
        _insert_obs(conn)
    finally:
        conn.close()

    result = heartbeat_once(home=tmp_path)
    autonomy = result["autonomy"]
    assert "from" in autonomy
    assert "to" in autonomy
    assert "reason" in autonomy
    assert "direction" in autonomy


def test_heartbeat_no_change_no_autonomy_key(tmp_path):
    result = heartbeat_once(home=tmp_path)
    assert "autonomy" in result["tasks_run"]
    assert "autonomy" not in result or result.get("autonomy") is None


def test_heartbeat_at_most_one_level_change(tmp_path):
    db_path = _setup_db(tmp_path)
    conn = connect(db_path)
    try:
        _insert_obs(conn)
    finally:
        conn.close()

    result = heartbeat_once(home=tmp_path)
    if result.get("autonomy"):
        change = abs(result["autonomy"]["to"] - result["autonomy"]["from"])
        assert change == 1
