from __future__ import annotations

from pydantic import BaseModel


class MetricValue(BaseModel):
    value: float
    collected_at: str
    unavailable: bool = False


class EvalSnapshot(BaseModel):
    metrics: dict[str, MetricValue]
