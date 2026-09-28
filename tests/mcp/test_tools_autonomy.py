from __future__ import annotations

from datetime import UTC, datetime

from patina.autonomy.actions import (
    ACTION_TYPE_TO_DOMAIN,
    edit_action,
    propose_action,
    reject_action,
)
from patina.autonomy.levels import current_level, set_level
from patina.autonomy.tracker import check_demotion, demote_level
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


def test_autonomy_status_per_domain_table(db_path, tmp_path):
    from patina.autonomy.levels import freeze_advancement, set_level
    from patina.store import connect

    init_db(db_path)
    conn = connect(db_path)
    try:
        set_level(conn, 3, domain="triage")
        set_level(conn, 2, domain="draft")
        freeze_advancement(conn, domain="draft")
    finally:
        conn.close()

    result = autonomy_status()
    assert "triage" in result
    assert "draft" in result
    assert "| 3 |" in result
    assert "| 2 |" in result
    assert "yes" in result


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


def test_check_demotion_triage_evaluates_error_rate(db_conn):
    set_level(db_conn, 3, domain="triage")
    for i in range(8):
        _make_obs(db_conn, f"dt{i}")
        record_decision(db_conn, f"dt{i}", "acted")
    for i in range(8, 11):
        _make_obs(db_conn, f"dt{i}")
        record_decision(db_conn, f"dt{i}", "deferred")

    should, reason, items = check_demotion(db_conn, current=3, domain="triage")
    assert should is True
    assert "error rate" in reason.lower()


def _insert_action(conn, aid, action_type, status, level, ts):
    conn.execute(
        """INSERT INTO action_queue
               (id, action_type, status, confidence, autonomy_level, created_at)
           VALUES (?, ?, ?, 0.9, ?, ?)""",
        (aid, action_type, status, level, ts),
    )


def test_check_demotion_draft_evaluates_acceptance(db_conn):
    set_level(db_conn, 4, domain="draft")
    now = datetime.now(UTC).isoformat()
    for i in range(15):
        _insert_action(db_conn, f"drf{i}", "draft", "rejected", 4, now)
    for i in range(5):
        _insert_action(db_conn, f"drfa{i}", "draft", "approved", 4, now)
    db_conn.commit()

    should, reason, items = check_demotion(db_conn, current=4, domain="draft")
    assert should is True
    assert "draft acceptance" in reason.lower()


def test_check_demotion_send_evaluates_reopen_rate(db_conn):
    set_level(db_conn, 5, domain="send")
    now = datetime.now(UTC).isoformat()
    for i in range(50):
        _insert_action(db_conn, f"snd{i}", "ack", "executed", 5, now)
    for i in range(5):
        _insert_action(db_conn, f"sndr{i}", "ack", "rejected", 5, now)
    db_conn.commit()

    should, reason, items = check_demotion(db_conn, current=5, domain="send")
    assert should is True
    assert "reopen rate" in reason.lower()


def test_demote_level_only_affects_target_domain(db_conn):
    set_level(db_conn, 4, domain="triage")
    set_level(db_conn, 4, domain="draft")
    set_level(db_conn, 4, domain="send")

    demote_level(db_conn, reason="test demotion", domain="triage")

    assert current_level(db_conn, domain="triage") == 3
    assert current_level(db_conn, domain="draft") == 4
    assert current_level(db_conn, domain="send") == 4


def test_reject_draft_freezes_only_draft_domain(db_conn):
    set_level(db_conn, 4, domain="triage")
    set_level(db_conn, 4, domain="draft")

    aid = propose_action(
        db_conn,
        action_type="draft",
        confidence=0.9,
        autonomy_level=4,
    )
    reject_action(db_conn, aid)

    draft_row = db_conn.execute(
        "SELECT frozen_until FROM autonomy_state WHERE domain = 'draft'"
    ).fetchone()
    triage_row = db_conn.execute(
        "SELECT frozen_until FROM autonomy_state WHERE domain = 'triage'"
    ).fetchone()

    assert draft_row["frozen_until"] is not None
    assert triage_row["frozen_until"] is None


def test_action_type_to_domain_covers_all_known_types():
    expected = {"dismiss", "draft", "ack", "schedule"}
    assert set(ACTION_TYPE_TO_DOMAIN.keys()) == expected
    assert ACTION_TYPE_TO_DOMAIN["dismiss"] == "triage"
    assert ACTION_TYPE_TO_DOMAIN["draft"] == "draft"
    assert ACTION_TYPE_TO_DOMAIN["ack"] == "send"
    assert ACTION_TYPE_TO_DOMAIN["schedule"] == "send"
