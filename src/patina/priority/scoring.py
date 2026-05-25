from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from patina.priority.objectives import Objective

_SEVERITY_RE = re.compile(
    r"\b(sev[- ]?[12]|incident|outage|regression|production issue|critical|urgent)\b",
    re.IGNORECASE,
)

_ESCALATION_SCORES: dict[str, float] = {
    "gentle": 0.2,
    "firm": 0.5,
    "urgent": 0.9,
}

_SENDER_TIER_SCORES: dict[str, float] = {
    "inner_circle": 0.9,
    "team": 0.6,
    "colleague": 0.3,
    "unknown": 0.1,
}


@dataclass
class QuadrantScore:
    item_id: str
    urgency: float
    importance: float
    quadrant: str
    confidence: float
    urgency_reasons: list[str] = field(default_factory=list)
    importance_reasons: list[str] = field(default_factory=list)


def _sigmoid(x: float, midpoint: float = 3.0, steepness: float = 0.8) -> float:
    return 1.0 / (1.0 + math.exp(-steepness * (x - midpoint)))


def score_urgency(
    *,
    staleness_days: float,
    escalation: str | None,
    is_commitment: bool,
    has_deadline: bool,
) -> tuple[float, list[str]]:
    reasons: list[str] = []

    stale_score = _sigmoid(staleness_days) * 0.4
    reasons.append(f"staleness={staleness_days:.1f}d")

    esc_raw = _ESCALATION_SCORES.get(escalation or "", 0.0)
    esc_score = esc_raw * 0.3
    if escalation:
        reasons.append(f"escalation={escalation}")

    commit_score = (0.7 if is_commitment else 0.0) * 0.2
    if is_commitment:
        reasons.append("commitment")

    deadline_score = (0.9 if has_deadline else 0.0) * 0.3
    if has_deadline:
        reasons.append("deadline")

    total = min(stale_score + esc_score + commit_score + deadline_score, 1.0)
    return total, reasons


def score_importance(
    *,
    text: str,
    sender_tier: str,
    objectives: list[Objective] | None,
    act_on_rate: float | None,
) -> tuple[float, list[str]]:
    reasons: list[str] = []

    tier_raw = _SENDER_TIER_SCORES.get(sender_tier, 0.1)
    tier_score = tier_raw * 0.35
    reasons.append(f"sender={sender_tier}")

    obj_score = 0.0
    if objectives:
        text_words = set(text.lower().split())
        best_overlap = 0.0
        for obj in objectives:
            kw = [k.strip().lower() for k in obj.keywords.split(",") if k.strip()]
            if kw:
                overlap = len(text_words & set(kw)) / len(kw)
                best_overlap = max(best_overlap, overlap)
        obj_score = best_overlap * 0.45
        if best_overlap > 0:
            reasons.append(f"objective_match={best_overlap:.0%}")

    aor = act_on_rate if act_on_rate is not None else 0.5
    aor_score = aor * 0.20
    reasons.append(f"act_on_rate={aor:.0%}")

    sev_score = 0.0
    if _SEVERITY_RE.search(text):
        sev_score = 0.95 * 0.50
        reasons.append("severity_keyword")

    total = min(tier_score + obj_score + aor_score + sev_score, 1.0)
    return total, reasons


def assign_quadrant(urgency: float, importance: float) -> str:
    if urgency >= 0.5 and importance >= 0.5:
        return "Q1"
    if urgency >= 0.5 and importance < 0.5:
        return "Q2"
    if urgency < 0.5 and importance >= 0.5:
        return "Q3"
    return "Q4"


def score_item(
    *,
    item_id: str,
    text: str,
    staleness_days: float,
    escalation: str | None,
    is_commitment: bool,
    has_deadline: bool,
    sender_tier: str,
    objectives: list[Objective] | None,
    act_on_rate: float | None,
) -> QuadrantScore:
    urgency, u_reasons = score_urgency(
        staleness_days=staleness_days,
        escalation=escalation,
        is_commitment=is_commitment,
        has_deadline=has_deadline,
    )
    importance, i_reasons = score_importance(
        text=text,
        sender_tier=sender_tier,
        objectives=objectives,
        act_on_rate=act_on_rate,
    )
    quadrant = assign_quadrant(urgency, importance)
    confidence = (urgency + importance) / 2.0

    return QuadrantScore(
        item_id=item_id,
        urgency=urgency,
        importance=importance,
        quadrant=quadrant,
        confidence=confidence,
        urgency_reasons=u_reasons,
        importance_reasons=i_reasons,
    )
