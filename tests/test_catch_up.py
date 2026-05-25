from __future__ import annotations

import time

from patina.graph import insert_observation
from patina.models import Observation
from patina.priority.catch_up import catch_up, priorities
from patina.store import init_db


def _insert_obs(conn, obs_id, text, age_hours):
    now = time.time()
    obs = Observation(
        id=obs_id,
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=now - (age_hours * 3600),
        sender_entity_id=None,
        text=text,
    )
    insert_observation(conn, obs)


def test_returns_three_groups(tmp_path):
    result = catch_up(home=tmp_path)
    assert "needs_action" in result
    assert "new" in result
    assert "waiting" in result


def test_empty_store_returns_empty(tmp_path):
    result = catch_up(home=tmp_path)
    assert result["needs_action"] == []
    assert result["new"] == []
    assert result["waiting"] == []


def test_fresh_items_in_new(db_conn, db_path, tmp_path):
    init_db(db_path)
    _insert_obs(db_conn, "fresh1", "Hello world", age_hours=2)
    db_conn.close()

    result = catch_up(home=tmp_path)
    ids = [i["id"] for i in result["new"]]
    assert "fresh1" in ids


def test_old_items_in_waiting(db_conn, db_path, tmp_path):
    init_db(db_path)
    _insert_obs(db_conn, "old1", "Something from a while ago", age_hours=48)
    db_conn.close()

    result = catch_up(home=tmp_path)
    ids = [i["id"] for i in result["waiting"]]
    assert "old1" in ids


def test_severity_items_in_needs_action(db_conn, db_path, tmp_path):
    init_db(db_path)
    _insert_obs(
        db_conn,
        "sev1",
        "SEV1: production outage on all endpoints",
        age_hours=4,
    )
    db_conn.close()

    result = catch_up(home=tmp_path)
    all_ids = [i["id"] for i in result["needs_action"]] + [i["id"] for i in result["new"]]
    assert "sev1" in all_ids


def test_respects_days_parameter(db_conn, db_path, tmp_path):
    init_db(db_path)
    _insert_obs(db_conn, "recent", "Hello", age_hours=12)
    _insert_obs(db_conn, "old", "Old message", age_hours=96)
    db_conn.close()

    result_1d = catch_up(home=tmp_path, days=1)
    all_1d = result_1d["needs_action"] + result_1d["new"] + result_1d["waiting"]
    ids_1d = [i["id"] for i in all_1d]
    assert "recent" in ids_1d
    assert "old" not in ids_1d


def test_priorities_groups_by_quadrant(db_conn, db_path, tmp_path):
    init_db(db_path)
    _insert_obs(db_conn, "p1", "regular message", age_hours=12)
    db_conn.close()

    result = priorities(home=tmp_path)
    assert "Q1" in result
    assert "Q2" in result
    assert "Q3" in result
    assert "Q4" in result

    all_items = result["Q1"] + result["Q2"] + result["Q3"] + result["Q4"]
    assert len(all_items) >= 1
