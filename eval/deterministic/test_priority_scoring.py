"""Eval: priority scoring is deterministic and quadrant assignment is stable."""

from __future__ import annotations

from patina.priority.scoring import score_item, score_urgency

SCENARIOS = [
    {
        "name": "fresh_unknown",
        "kwargs": {
            "staleness_days": 0.5,
            "escalation": None,
            "is_commitment": False,
            "has_deadline": False,
            "sender_tier": "unknown",
            "objectives": None,
            "act_on_rate": None,
        },
        "expected_quadrant": "Q4",
    },
    {
        "name": "old_inner_circle",
        "kwargs": {
            "staleness_days": 10.0,
            "escalation": "urgent",
            "is_commitment": True,
            "has_deadline": False,
            "sender_tier": "inner_circle",
            "objectives": None,
            "act_on_rate": 1.0,
        },
        "expected_quadrant": "Q1",
    },
    {
        "name": "severity_fresh",
        "kwargs": {
            "staleness_days": 0.5,
            "escalation": None,
            "is_commitment": False,
            "has_deadline": False,
            "sender_tier": "unknown",
            "objectives": None,
            "act_on_rate": None,
        },
        "text": "SEV1: production outage",
        "expected_quadrant": "Q3",
    },
]


def test_scenarios_stable():
    for s in SCENARIOS:
        text = s.get("text", "hello world")
        result = score_item(item_id="test", text=text, **s["kwargs"])
        assert result.quadrant == s["expected_quadrant"], (
            f"Scenario {s['name']}: expected {s['expected_quadrant']}, got {result.quadrant}"
        )


def test_deterministic():
    kwargs = {
        "item_id": "det1",
        "text": "Check the deployment pipeline",
        "staleness_days": 3.0,
        "escalation": "gentle",
        "is_commitment": True,
        "has_deadline": False,
        "sender_tier": "team",
        "objectives": None,
        "act_on_rate": 0.7,
    }
    r1 = score_item(**kwargs)
    r2 = score_item(**kwargs)
    assert r1.urgency == r2.urgency
    assert r1.importance == r2.importance
    assert r1.quadrant == r2.quadrant


def test_urgency_importance_independent():
    u1, _ = score_urgency(
        staleness_days=1.0, escalation=None, is_commitment=False, has_deadline=False
    )
    u2, _ = score_urgency(
        staleness_days=10.0, escalation="urgent", is_commitment=True, has_deadline=True
    )
    assert u2 > u1
