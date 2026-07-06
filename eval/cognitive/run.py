"""Cognitive eval: collect metrics and write a snapshot to latest.json.

Run: python eval/cognitive/run.py
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from eval.cognitive import EvalSnapshot, MetricValue


def collect_merge_rate() -> MetricValue:
    return MetricValue(value=0.0, collected_at=datetime.now(UTC).isoformat())


def collect_time_to_implement() -> MetricValue:
    return MetricValue(value=0.0, collected_at=datetime.now(UTC).isoformat())


def collect_tool_reliability() -> MetricValue:
    return MetricValue(value=0.0, collected_at=datetime.now(UTC).isoformat())


def main() -> None:
    snapshot = EvalSnapshot(
        metrics={
            "merge_rate": collect_merge_rate(),
            "time_to_implement": collect_time_to_implement(),
            "tool_reliability": collect_tool_reliability(),
        }
    )
    out = Path(__file__).resolve().parent / "latest.json"
    out.write_text(snapshot.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
