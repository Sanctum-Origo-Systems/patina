from __future__ import annotations

from datetime import UTC, datetime, timedelta

from patina.beliefs.decay import (
    compute_effective_confidence,
    get_stale_beliefs,
    run_decay_pass,
)
from patina.graph import insert_claim, upsert_entity
from patina.models import Claim, Entity


def test_fresh_belief_unchanged():
    eff = compute_effective_confidence(1.0, 0.02, 0.0)
    assert eff == 1.0


def test_30_days_at_2pct():
    eff = compute_effective_confidence(1.0, 0.02, 30)
    assert abs(eff - 0.545) < 0.01


def test_60_days_at_2pct():
    eff = compute_effective_confidence(1.0, 0.02, 60)
    assert abs(eff - 0.297) < 0.01


def test_stale_beliefs_returned(db_conn):
    e = Entity(id="e1", type="person", name="Alice")
    upsert_entity(db_conn, e)

    old_date = (datetime.now(UTC) - timedelta(days=90)).isoformat()
    claim = Claim(
        id="c1",
        subject_id="e1",
        predicate="owns",
        object="ProjectX",
        confidence=0.5,
        first_asserted=old_date,
        last_confirmed=old_date,
        decay_rate=0.02,
    )
    insert_claim(db_conn, claim)

    stale = get_stale_beliefs(db_conn, threshold=0.3)
    assert len(stale) >= 1
    assert stale[0]["id"] == "c1"


def test_fresh_beliefs_not_stale(db_conn):
    e = Entity(id="e1", type="person", name="Alice")
    upsert_entity(db_conn, e)

    now = datetime.now(UTC).isoformat()
    claim = Claim(
        id="c1",
        subject_id="e1",
        predicate="owns",
        object="ProjectX",
        confidence=1.0,
        first_asserted=now,
        last_confirmed=now,
        decay_rate=0.02,
    )
    insert_claim(db_conn, claim)

    stale = get_stale_beliefs(db_conn, threshold=0.3)
    assert len(stale) == 0


def test_run_decay_pass_counts(db_conn):
    e = Entity(id="e1", type="person", name="Alice")
    upsert_entity(db_conn, e)

    old_date = (datetime.now(UTC) - timedelta(days=90)).isoformat()
    claim = Claim(
        id="c1",
        subject_id="e1",
        predicate="owns",
        object="ProjectX",
        confidence=0.5,
        first_asserted=old_date,
        last_confirmed=old_date,
    )
    insert_claim(db_conn, claim)

    count = run_decay_pass(db_conn)
    assert count >= 1
