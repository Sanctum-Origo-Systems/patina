"""Compare baseline.json and latest.json, emit a structured delta report.

Run: python eval/cognitive/compare.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from eval.cognitive.snapshot import REQUIRED_METRICS, EvalSnapshot

_DIR = Path(__file__).resolve().parent


def load_snapshot(path: Path) -> EvalSnapshot:
    raw = path.read_text()
    data = json.loads(raw)
    return EvalSnapshot.model_validate(data)


def compute_deltas(baseline: EvalSnapshot, latest: EvalSnapshot) -> list[dict[str, object]]:
    deltas: list[dict[str, object]] = []
    for metric in sorted(REQUIRED_METRICS):
        b_val = baseline.metrics[metric].value
        l_val = latest.metrics[metric].value
        abs_delta = l_val - b_val
        pct_delta = (abs_delta / b_val * 100) if b_val != 0 else None
        deltas.append(
            {
                "metric": metric,
                "baseline": b_val,
                "latest": l_val,
                "absolute_delta": abs_delta,
                "percent_delta": pct_delta,
            }
        )
    return deltas


def main(
    baseline_path: Path | None = None,
    latest_path: Path | None = None,
) -> None:
    baseline_path = baseline_path or (_DIR / "baseline.json")
    latest_path = latest_path or (_DIR / "latest.json")

    for label, path in [("baseline", baseline_path), ("latest", latest_path)]:
        if not path.is_file():
            print(f"error: {label} file not found: {path}", file=sys.stderr)
            sys.exit(1)

    for label, path in [("baseline", baseline_path), ("latest", latest_path)]:
        try:
            raw = path.read_text()
            json.loads(raw)
        except json.JSONDecodeError as exc:
            print(
                f"error: {label} file contains malformed JSON: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

    for label, path in [("baseline", baseline_path), ("latest", latest_path)]:
        try:
            load_snapshot(path)
        except Exception as exc:
            print(
                f"error: {label} file is missing required metric keys: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

    baseline = load_snapshot(baseline_path)
    latest = load_snapshot(latest_path)
    deltas = compute_deltas(baseline, latest)
    print(json.dumps({"deltas": deltas}, indent=2))


if __name__ == "__main__":
    main()
