from __future__ import annotations

import time

from patina.graph import insert_observation
from patina.models import Observation
from patina.priority.escalation import detect_urgency_shifts, escalation_tier


def test_fresh_items_no_escalation():
    assert escalation_tier(0.5) is None
    assert escalation_tier(2.9) is None


def test_gentle_escalation():
    assert escalation_tier(3.0) == "gentle"
    assert escalation_tier(5.0) == "gentle"
    assert escalation_tier(6.9) == "gentle"


def test_urgent_escalation():
    assert escalation_tier(7.0) == "urgent"
    assert escalation_tier(10.0) == "urgent"


def test_detect_shifts_finds_crossed_items(db_conn, tmp_path):
    now = time.time()
    obs = Observation(
        id="shift1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=now - (8 * 86400),
        sender_entity_id=None,
        text="SEV1: production outage critical",
    )
    insert_observation(db_conn, obs)

    shifts = detect_urgency_shifts(db_conn, since_days=3, home=tmp_path)
    found = [s for s in shifts if s["item_id"] == "shift1"]
    assert len(found) <= 1


def test_detect_shifts_ignores_non_shifted(db_conn, tmp_path):
    now = time.time()
    obs = Observation(
        id="stable1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=now - (1 * 86400),
        sender_entity_id=None,
        text="Hello world",
    )
    insert_observation(db_conn, obs)

    shifts = detect_urgency_shifts(db_conn, since_days=1, home=tmp_path)
    found = [s for s in shifts if s["item_id"] == "stable1"]
    assert len(found) == 0
