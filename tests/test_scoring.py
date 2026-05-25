from __future__ import annotations

from patina.priority.objectives import Objective
from patina.priority.scoring import (
    QuadrantScore,
    assign_quadrant,
    score_importance,
    score_item,
    score_urgency,
)


def test_low_staleness_low_urgency():
    score, reasons = score_urgency(
        staleness_days=0.5,
        escalation=None,
        is_commitment=False,
        has_deadline=False,
    )
    assert score < 0.3


def test_high_staleness_high_urgency():
    score, reasons = score_urgency(
        staleness_days=10.0,
        escalation=None,
        is_commitment=False,
        has_deadline=False,
    )
    assert score > 0.3


def test_escalation_boosts_urgency():
    base, _ = score_urgency(
        staleness_days=2.0,
        escalation=None,
        is_commitment=False,
        has_deadline=False,
    )
    boosted, _ = score_urgency(
        staleness_days=2.0,
        escalation="urgent",
        is_commitment=False,
        has_deadline=False,
    )
    assert boosted > base


def test_commitment_boosts_urgency():
    base, _ = score_urgency(
        staleness_days=2.0,
        escalation=None,
        is_commitment=False,
        has_deadline=False,
    )
    boosted, _ = score_urgency(
        staleness_days=2.0,
        escalation=None,
        is_commitment=True,
        has_deadline=False,
    )
    assert boosted > base


def test_deadline_boosts_urgency():
    base, _ = score_urgency(
        staleness_days=2.0,
        escalation=None,
        is_commitment=False,
        has_deadline=False,
    )
    boosted, _ = score_urgency(
        staleness_days=2.0,
        escalation=None,
        is_commitment=False,
        has_deadline=True,
    )
    assert boosted > base


def test_inner_circle_high_importance():
    score, reasons = score_importance(
        text="hello",
        sender_tier="inner_circle",
        objectives=None,
        act_on_rate=None,
    )
    assert score > 0.3


def test_unknown_sender_low_importance():
    score, reasons = score_importance(
        text="hello",
        sender_tier="unknown",
        objectives=None,
        act_on_rate=None,
    )
    assert score < 0.3


def test_severity_keywords_boost():
    score, reasons = score_importance(
        text="SEV1: production outage on API",
        sender_tier="unknown",
        objectives=None,
        act_on_rate=None,
    )
    assert score >= 0.5


def test_objective_keyword_overlap():
    obj = Objective(
        id="o1",
        label="Platform",
        keywords="platform, migration, deploy",
        active=True,
        created_at="",
        updated_at="",
    )
    score_with, _ = score_importance(
        text="platform migration is blocked",
        sender_tier="unknown",
        objectives=[obj],
        act_on_rate=None,
    )
    score_without, _ = score_importance(
        text="lunch plans for friday",
        sender_tier="unknown",
        objectives=[obj],
        act_on_rate=None,
    )
    assert score_with > score_without


def test_quadrant_q1():
    assert assign_quadrant(0.7, 0.6) == "Q1"


def test_quadrant_q2():
    assert assign_quadrant(0.7, 0.3) == "Q2"


def test_quadrant_q3():
    assert assign_quadrant(0.3, 0.7) == "Q3"


def test_quadrant_q4():
    assert assign_quadrant(0.3, 0.3) == "Q4"


def test_quadrant_boundary():
    assert assign_quadrant(0.5, 0.5) == "Q1"
    assert assign_quadrant(0.49, 0.49) == "Q4"


def test_score_capped_at_1():
    score, _ = score_urgency(
        staleness_days=100.0,
        escalation="urgent",
        is_commitment=True,
        has_deadline=True,
    )
    assert score <= 1.0


def test_importance_capped_at_1():
    obj = Objective(
        id="o1",
        label="Test",
        keywords="sev1, outage",
        active=True,
        created_at="",
        updated_at="",
    )
    score, _ = score_importance(
        text="SEV1 outage in production",
        sender_tier="inner_circle",
        objectives=[obj],
        act_on_rate=0.99,
    )
    assert score <= 1.0


def test_score_item_returns_quadrant_score():
    result = score_item(
        item_id="test1",
        text="hello world",
        staleness_days=1.0,
        escalation=None,
        is_commitment=False,
        has_deadline=False,
        sender_tier="unknown",
        objectives=None,
        act_on_rate=None,
    )
    assert isinstance(result, QuadrantScore)
    assert result.quadrant in ("Q1", "Q2", "Q3", "Q4")
