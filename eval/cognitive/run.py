"""Cognitive eval: collect metrics and write a snapshot to latest.json.

Run: python eval/cognitive/run.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from eval.cognitive import EvalSnapshot, MetricValue


def collect_merge_rate() -> MetricValue:
    return MetricValue(value=0.0, collected_at=datetime.now(UTC).isoformat())


def collect_time_to_implement() -> MetricValue:
    return MetricValue(value=0.0, collected_at=datetime.now(UTC).isoformat())


def collect_tool_reliability(log_path: Path | str | None = None) -> MetricValue:
    now = datetime.now(UTC).isoformat()

    if log_path is None:
        log_path = Path.home() / ".patina" / "mcp_call_log.jsonl"
    else:
        log_path = Path(log_path)

    try:
        text = log_path.read_text()
    except OSError:
        return MetricValue(value=0.0, collected_at=now, unavailable=True)

    total = 0
    successes = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        total += 1
        if record.get("success"):
            successes += 1

    if total == 0:
        return MetricValue(value=0.0, collected_at=now)

    return MetricValue(value=successes / total, collected_at=now)


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
