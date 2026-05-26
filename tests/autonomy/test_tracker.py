from __future__ import annotations

from patina.autonomy.levels import current_level, set_level
from patina.autonomy.tracker import (
    clear_anti_pattern,
    demote_level,
    get_accuracy_stats,
    get_anti_patterns,
    get_override_count,
    matches_anti_pattern,
    should_auto_act,
)
from patina.decisions import record_decision
from patina.graph import insert_observation
from patina.models import Observation


def _add_obs_and_decision(conn, obs_id, action):
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
    record_decision(conn, obs_id, action)


def test_accuracy_with_data(db_conn):
    _add_obs_and_decision(db_conn, "o1", "acted")
    _add_obs_and_decision(db_conn, "o2", "acted")
    _add_obs_and_decision(db_conn, "o3", "deferred")

    stats = get_accuracy_stats(db_conn)
    assert stats["total"] == 3
    assert stats["correct"] == 2
    assert stats["incorrect"] == 1
    assert abs(stats["accuracy_rate"] - 2 / 3) < 0.01


def test_accuracy_no_data(db_conn):
    stats = get_accuracy_stats(db_conn)
    assert stats["total"] == 0
    assert stats["accuracy_rate"] == 0.5


def test_override_count(db_conn):
    from patina.autonomy.actions import propose_action, reject_action

    aid = propose_action(db_conn, action_type="dismiss", confidence=0.9, autonomy_level=3)
    reject_action(db_conn, aid)

    count = get_override_count(db_conn, since_days=7)
    assert count == 1


def test_demotion_stores_anti_pattern(db_conn):
    set_level(db_conn, 3)

    items = [
        {
            "id": "item1",
            "pattern_type": "dismiss_error",
            "text_keywords": ["urgent", "sev1"],
            "wrong_action": "dismissed",
            "correct_action": "acted",
        }
    ]
    new_level = demote_level(db_conn, reason="error rate exceeded", items=items)
    assert new_level == 2
    assert current_level(db_conn) == 2

    patterns = get_anti_patterns(db_conn)
    assert len(patterns) == 1
    assert patterns[0]["pattern_type"] == "dismiss_error"
    assert "urgent" in patterns[0]["text_keywords"]


def test_should_auto_act_false_on_anti_pattern(db_conn):
    set_level(db_conn, 3)
    demote_level(
        db_conn,
        reason="test",
        items=[
            {
                "pattern_type": "error",
                "text_keywords": ["outage"],
                "wrong_action": "dismissed",
                "correct_action": "acted",
            }
        ],
    )

    item = {"text": "production outage detected", "confidence": 0.9, "autonomy_level": 2}
    assert should_auto_act(db_conn, item, current=3) is False


def test_should_auto_act_true_no_match(db_conn):
    item = {"text": "hello world", "confidence": 0.9, "autonomy_level": 1}
    assert should_auto_act(db_conn, item, current=2) is True


def test_should_auto_act_false_low_confidence(db_conn):
    item = {"text": "hello", "confidence": 0.3, "autonomy_level": 1}
    assert should_auto_act(db_conn, item, current=2) is False


def test_matches_anti_pattern():
    patterns = [{"text_keywords": ["urgent", "sev1"], "pattern_type": "error"}]
    assert matches_anti_pattern({"text": "URGENT: server down"}, patterns) is True
    assert matches_anti_pattern({"text": "normal message"}, patterns) is False


def test_clear_anti_pattern(db_conn):
    set_level(db_conn, 3)
    demote_level(
        db_conn,
        reason="test",
        items=[
            {
                "pattern_type": "error",
                "text_keywords": ["test"],
                "wrong_action": "dismissed",
                "correct_action": "acted",
            }
        ],
    )

    patterns = get_anti_patterns(db_conn)
    assert len(patterns) == 1

    clear_anti_pattern(db_conn, patterns[0]["id"])
    assert len(get_anti_patterns(db_conn)) == 0


def test_manual_set_level(db_conn):
    set_level(db_conn, 5)
    assert current_level(db_conn) == 5
    set_level(db_conn, 2)
    assert current_level(db_conn) == 2
