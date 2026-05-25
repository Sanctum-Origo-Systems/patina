from __future__ import annotations

from patina.decisions import get_act_on_rate, record_decision
from patina.graph import insert_observation
from patina.models import Observation


def _make_obs(db_conn, obs_id: str, sender: str | None = None) -> None:
    obs = Observation(
        id=obs_id,
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=sender,
        text="test",
    )
    insert_observation(db_conn, obs)


def test_record_decision_inserts(db_conn):
    _make_obs(db_conn, "o1")
    record_decision(db_conn, "o1", "acted")

    row = db_conn.execute("SELECT * FROM decisions WHERE observation_id = 'o1'").fetchone()
    assert row is not None
    assert row["action"] == "acted"


def test_act_on_rate_calculation(db_conn):
    _make_obs(db_conn, "o1")
    _make_obs(db_conn, "o2")
    _make_obs(db_conn, "o3")

    record_decision(db_conn, "o1", "acted")
    record_decision(db_conn, "o2", "acted")
    record_decision(db_conn, "o3", "dismissed")

    rate = get_act_on_rate(db_conn)
    assert abs(rate - 2 / 3) < 0.01


def test_act_on_rate_default_no_data(db_conn):
    rate = get_act_on_rate(db_conn)
    assert rate == 0.5
