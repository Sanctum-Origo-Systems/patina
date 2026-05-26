from __future__ import annotations

from patina.autonomy.actions import (
    approve_action,
    auto_execute_eligible,
    list_pending,
    propose_action,
    reject_action,
)
from patina.autonomy.levels import is_frozen


def test_propose_creates_pending(db_conn):
    aid = propose_action(
        db_conn,
        action_type="dismiss",
        confidence=0.9,
        autonomy_level=3,
    )
    pending = list_pending(db_conn)
    assert len(pending) == 1
    assert pending[0]["id"] == aid


def test_approve_changes_status(db_conn):
    aid = propose_action(
        db_conn,
        action_type="dismiss",
        confidence=0.9,
        autonomy_level=3,
    )
    assert approve_action(db_conn, aid) is True

    pending = list_pending(db_conn)
    assert len(pending) == 0

    row = db_conn.execute("SELECT status FROM action_queue WHERE id = ?", (aid,)).fetchone()
    assert row["status"] == "approved"


def test_reject_changes_status_and_freezes(db_conn):
    aid = propose_action(
        db_conn,
        action_type="dismiss",
        confidence=0.9,
        autonomy_level=3,
    )
    assert reject_action(db_conn, aid) is True

    row = db_conn.execute("SELECT status FROM action_queue WHERE id = ?", (aid,)).fetchone()
    assert row["status"] == "rejected"
    assert is_frozen(db_conn) is True


def test_list_pending_only_proposed(db_conn):
    aid1 = propose_action(
        db_conn,
        action_type="dismiss",
        confidence=0.9,
        autonomy_level=3,
    )
    propose_action(
        db_conn,
        action_type="ack",
        confidence=0.8,
        autonomy_level=2,
    )
    approve_action(db_conn, aid1)

    pending = list_pending(db_conn)
    assert len(pending) == 1
    assert pending[0]["action_type"] == "ack"


def test_auto_execute_respects_level(db_conn):
    propose_action(
        db_conn,
        action_type="dismiss",
        confidence=0.9,
        autonomy_level=3,
    )
    propose_action(
        db_conn,
        action_type="ack",
        confidence=0.85,
        autonomy_level=1,
    )

    count = auto_execute_eligible(db_conn, current_level=2)
    assert count == 1

    pending = list_pending(db_conn)
    assert len(pending) == 1
    assert pending[0]["autonomy_level"] == 3
