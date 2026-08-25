from __future__ import annotations

from patina.autonomy.actions import edit_action, propose_action, reject_action
from patina.decisions import get_act_on_rate, record_decision
from patina.graph import insert_observation
from patina.mcp.tools_autonomy import autonomy_status
from patina.models import Observation
from patina.store import init_db


def _make_obs(conn, obs_id: str) -> None:
    obs = Observation(
        id=obs_id,
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=None,
        text="test",
    )
    insert_observation(conn, obs)


def test_autonomy_status_returns_string(db_path, tmp_path):
    init_db(db_path)
    result = autonomy_status()
    assert isinstance(result, str)
    assert "Level" in result


def test_reject_action_records_decision(db_conn):
    _make_obs(db_conn, "obs1")
    aid = propose_action(
        db_conn,
        action_type="dismiss",
        target_observation_id="obs1",
        confidence=0.9,
        autonomy_level=3,
    )
    reject_action(db_conn, aid)

    row = db_conn.execute("SELECT action FROM decisions WHERE observation_id = 'obs1'").fetchone()
    assert row is not None
    assert row["action"] == "rejected"


def test_edit_action_records_decision(db_conn):
    _make_obs(db_conn, "obs2")
    aid = propose_action(
        db_conn,
        action_type="dismiss",
        target_observation_id="obs2",
        confidence=0.9,
        autonomy_level=3,
    )
    edit_action(db_conn, aid)

    row = db_conn.execute("SELECT action FROM decisions WHERE observation_id = 'obs2'").fetchone()
    assert row is not None
    assert row["action"] == "edited"


def test_act_on_rate_with_mixed_outcomes(db_conn):
    _make_obs(db_conn, "o1")
    _make_obs(db_conn, "o2")
    _make_obs(db_conn, "o3")
    _make_obs(db_conn, "o4")

    record_decision(db_conn, "o1", "acted")
    record_decision(db_conn, "o2", "acted")
    record_decision(db_conn, "o3", "rejected")
    record_decision(db_conn, "o4", "edited")

    rate = get_act_on_rate(db_conn)
    assert abs(rate - 2 / 4) < 0.01
