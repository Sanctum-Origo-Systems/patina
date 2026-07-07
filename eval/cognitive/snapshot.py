"""EvalSnapshot Pydantic schema for cognitive eval metrics."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, model_validator

REQUIRED_METRICS = frozenset({"merge_rate", "time_to_implement", "tool_reliability"})


class MetricValue(BaseModel):
    value: float
    collected_at: datetime
    unavailable: bool = False


class EvalSnapshot(BaseModel):
    metrics: dict[str, MetricValue]

    @model_validator(mode="after")
    def _check_required_keys(self) -> EvalSnapshot:
        keys = set(self.metrics.keys())
        if keys != REQUIRED_METRICS:
            missing = REQUIRED_METRICS - keys
            extra = keys - REQUIRED_METRICS
            parts = []
            if missing:
                parts.append(f"missing: {sorted(missing)}")
            if extra:
                parts.append(f"unexpected: {sorted(extra)}")
            raise ValueError(
                f"metrics must contain exactly {sorted(REQUIRED_METRICS)}; " + ", ".join(parts)
            )
        return self
