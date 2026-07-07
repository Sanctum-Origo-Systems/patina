from __future__ import annotations

import json
from datetime import datetime

from eval.cognitive import EvalSnapshot, MetricValue


def _make_metric(**overrides):
    defaults = {"value": 0.0, "collected_at": "2025-01-01T00:00:00+00:00"}
    defaults.update(overrides)
    return MetricValue(**defaults)


def _make_full_metrics(**overrides):
    metrics = {
        "merge_rate": _make_metric(),
        "time_to_implement": _make_metric(),
        "tool_reliability": _make_metric(),
    }
    metrics.update(overrides)
    return metrics


def test_import_no_side_effects():
    from eval.cognitive import EvalSnapshot, MetricValue

    assert EvalSnapshot is not None
    assert MetricValue is not None


def test_metric_value_fields():
    mv = MetricValue(value=1.5, collected_at="2025-01-01T00:00:00+00:00")
    assert mv.value == 1.5
    assert isinstance(mv.collected_at, datetime)
    assert mv.unavailable is False


def test_metric_value_unavailable():
    mv = MetricValue(value=0.0, collected_at="2025-01-01T00:00:00+00:00", unavailable=True)
    assert mv.unavailable is True


def test_metric_value_rejects_invalid_timestamp():
    import pytest

    with pytest.raises(Exception):
        MetricValue(value=0.0, collected_at="not-a-date")


def test_eval_snapshot_requires_all_three_keys():
    snap = EvalSnapshot(metrics=_make_full_metrics())
    assert set(snap.metrics.keys()) == {
        "merge_rate",
        "time_to_implement",
        "tool_reliability",
    }


def test_eval_snapshot_rejects_missing_key():
    import pytest

    with pytest.raises(Exception, match="missing"):
        EvalSnapshot(metrics={"merge_rate": _make_metric(), "time_to_implement": _make_metric()})


def test_eval_snapshot_rejects_extra_key():
    import pytest

    metrics = _make_full_metrics()
    metrics["bonus"] = _make_metric()
    with pytest.raises(Exception, match="unexpected"):
        EvalSnapshot(metrics=metrics)


def test_eval_snapshot_rejects_empty_metrics():
    import pytest

    with pytest.raises(Exception, match="missing"):
        EvalSnapshot(metrics={})


def test_collector_functions_return_metric_value():
    from eval.cognitive.run import (
        collect_merge_rate,
        collect_time_to_implement,
        collect_tool_reliability,
    )

    for fn in (collect_merge_rate, collect_time_to_implement, collect_tool_reliability):
        result = fn()
        assert isinstance(result, MetricValue)
        assert result.value == 0.0
        assert isinstance(result.collected_at, datetime)


def test_run_writes_valid_snapshot(tmp_path):
    from eval.cognitive.run import main

    out = tmp_path / "latest.json"
    main(output_path=out)
    assert out.exists()

    snap = EvalSnapshot.model_validate_json(out.read_text())
    assert set(snap.metrics.keys()) == {
        "merge_rate",
        "time_to_implement",
        "tool_reliability",
    }
    for mv in snap.metrics.values():
        assert mv.value == 0.0
        assert isinstance(mv.collected_at, datetime)


def test_run_overwrites_existing(tmp_path):
    from eval.cognitive.run import main

    out = tmp_path / "latest.json"
    out.write_text('{"old": true}')

    main(output_path=out)

    data = json.loads(out.read_text())
    assert "old" not in data
    assert "metrics" in data
