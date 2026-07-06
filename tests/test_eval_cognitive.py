from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def test_import_no_side_effects():
    from eval.cognitive import EvalSnapshot, MetricValue

    assert EvalSnapshot is not None
    assert MetricValue is not None


def test_metric_value_fields():
    from eval.cognitive import MetricValue

    mv = MetricValue(value=1.5, collected_at="2025-01-01T00:00:00+00:00")
    assert mv.value == 1.5
    assert mv.collected_at == "2025-01-01T00:00:00+00:00"
    assert mv.unavailable is False


def test_metric_value_unavailable():
    from eval.cognitive import MetricValue

    mv = MetricValue(value=0.0, collected_at="2025-01-01T00:00:00+00:00", unavailable=True)
    assert mv.unavailable is True


def test_eval_snapshot_metrics():
    from eval.cognitive import EvalSnapshot, MetricValue

    snap = EvalSnapshot(
        metrics={
            "merge_rate": MetricValue(value=0.0, collected_at="2025-01-01T00:00:00+00:00"),
        }
    )
    assert "merge_rate" in snap.metrics
    assert snap.metrics["merge_rate"].value == 0.0


def test_collector_functions_return_metric_value():
    from eval.cognitive import MetricValue
    from eval.cognitive.run import (
        collect_merge_rate,
        collect_time_to_implement,
        collect_tool_reliability,
    )

    for fn in (collect_merge_rate, collect_time_to_implement, collect_tool_reliability):
        result = fn()
        assert isinstance(result, MetricValue)
        assert result.value == 0.0
        datetime.fromisoformat(result.collected_at)


def test_run_writes_valid_snapshot():
    from eval.cognitive import EvalSnapshot
    from eval.cognitive.run import main

    main()

    latest = Path(__file__).resolve().parent.parent / "eval" / "cognitive" / "latest.json"
    assert latest.exists()

    snap = EvalSnapshot.model_validate_json(latest.read_text())
    assert set(snap.metrics.keys()) == {"merge_rate", "time_to_implement", "tool_reliability"}
    for mv in snap.metrics.values():
        assert mv.value == 0.0
        datetime.fromisoformat(mv.collected_at)

    latest.unlink()


def test_run_script_exit_code():
    project_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "eval/cognitive/run.py"],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    latest = project_root / "eval" / "cognitive" / "latest.json"
    assert latest.exists()

    from eval.cognitive import EvalSnapshot

    snap = EvalSnapshot.model_validate_json(latest.read_text())
    assert set(snap.metrics.keys()) == {"merge_rate", "time_to_implement", "tool_reliability"}

    latest.unlink()


def test_run_overwrites_existing():
    latest = Path(__file__).resolve().parent.parent / "eval" / "cognitive" / "latest.json"
    latest.write_text('{"old": true}')

    from eval.cognitive.run import main

    main()

    data = json.loads(latest.read_text())
    assert "old" not in data
    assert "metrics" in data

    latest.unlink()
