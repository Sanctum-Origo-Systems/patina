"""Tests for cognitive eval delta reporter (compare.py)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from eval.cognitive.compare import compute_deltas, load_snapshot, main
from eval.cognitive.snapshot import EvalSnapshot, MetricValue

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_TS = "2025-01-01T00:00:00+00:00"


def _make_snapshot(merge_rate=0.5, time_to_implement=10.0, tool_reliability=0.9):
    return EvalSnapshot(
        metrics={
            "merge_rate": MetricValue(value=merge_rate, collected_at=_TS),
            "time_to_implement": MetricValue(value=time_to_implement, collected_at=_TS),
            "tool_reliability": MetricValue(value=tool_reliability, collected_at=_TS),
        }
    )


def _write_snapshot(path: Path, snap: EvalSnapshot) -> None:
    path.write_text(snap.model_dump_json(indent=2))


# --- load_snapshot ---


class TestLoadSnapshot:
    def test_loads_valid_file(self, tmp_path: Path) -> None:
        snap = _make_snapshot()
        f = tmp_path / "snap.json"
        _write_snapshot(f, snap)
        loaded = load_snapshot(f)
        assert set(loaded.metrics.keys()) == {"merge_rate", "time_to_implement", "tool_reliability"}

    def test_raises_on_malformed_json(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("{not valid json")
        with pytest.raises(json.JSONDecodeError):
            load_snapshot(f)

    def test_raises_on_missing_keys(self, tmp_path: Path) -> None:
        f = tmp_path / "partial.json"
        f.write_text(
            json.dumps(
                {
                    "metrics": {
                        "merge_rate": {"value": 0.5, "collected_at": _TS},
                    }
                }
            )
        )
        with pytest.raises(Exception, match="missing"):
            load_snapshot(f)


# --- compute_deltas ---


class TestComputeDeltas:
    def test_basic_deltas(self) -> None:
        baseline = _make_snapshot(merge_rate=0.5, time_to_implement=20.0, tool_reliability=0.8)
        latest = _make_snapshot(merge_rate=0.7, time_to_implement=15.0, tool_reliability=0.9)
        deltas = compute_deltas(baseline, latest)

        by_metric = {d["metric"]: d for d in deltas}

        assert by_metric["merge_rate"]["baseline"] == 0.5
        assert by_metric["merge_rate"]["latest"] == 0.7
        assert by_metric["merge_rate"]["absolute_delta"] == pytest.approx(0.2)
        assert by_metric["merge_rate"]["percent_delta"] == pytest.approx(40.0)

        assert by_metric["time_to_implement"]["absolute_delta"] == pytest.approx(-5.0)
        assert by_metric["time_to_implement"]["percent_delta"] == pytest.approx(-25.0)

        assert by_metric["tool_reliability"]["absolute_delta"] == pytest.approx(0.1)
        assert by_metric["tool_reliability"]["percent_delta"] == pytest.approx(12.5)

    def test_identical_snapshots(self) -> None:
        snap = _make_snapshot()
        deltas = compute_deltas(snap, snap)
        for d in deltas:
            assert d["absolute_delta"] == 0.0

    def test_zero_baseline_produces_null_percent(self) -> None:
        baseline = _make_snapshot(merge_rate=0.0)
        latest = _make_snapshot(merge_rate=0.5)
        deltas = compute_deltas(baseline, latest)
        by_metric = {d["metric"]: d for d in deltas}
        assert by_metric["merge_rate"]["percent_delta"] is None
        assert by_metric["merge_rate"]["absolute_delta"] == pytest.approx(0.5)

    def test_returns_sorted_by_metric_name(self) -> None:
        deltas = compute_deltas(_make_snapshot(), _make_snapshot())
        names = [d["metric"] for d in deltas]
        assert names == sorted(names)

    def test_all_required_fields_present(self) -> None:
        deltas = compute_deltas(_make_snapshot(), _make_snapshot())
        for d in deltas:
            assert set(d.keys()) == {
                "metric",
                "baseline",
                "latest",
                "absolute_delta",
                "percent_delta",
            }


# --- main() ---


class TestMain:
    def test_valid_inputs_exit_zero(self, tmp_path: Path, capsys) -> None:
        baseline = tmp_path / "baseline.json"
        latest = tmp_path / "latest.json"
        _write_snapshot(baseline, _make_snapshot(merge_rate=0.4))
        _write_snapshot(latest, _make_snapshot(merge_rate=0.6))

        main(baseline_path=baseline, latest_path=latest)

        captured = capsys.readouterr()
        report = json.loads(captured.out)
        assert "deltas" in report
        assert len(report["deltas"]) == 3

    def test_missing_baseline_exits_nonzero(self, tmp_path: Path, capsys) -> None:
        latest = tmp_path / "latest.json"
        _write_snapshot(latest, _make_snapshot())
        baseline = tmp_path / "baseline.json"

        with pytest.raises(SystemExit) as exc_info:
            main(baseline_path=baseline, latest_path=latest)
        assert exc_info.value.code != 0

        captured = capsys.readouterr()
        assert "baseline" in captured.err
        assert "not found" in captured.err

    def test_missing_latest_exits_nonzero(self, tmp_path: Path, capsys) -> None:
        baseline = tmp_path / "baseline.json"
        _write_snapshot(baseline, _make_snapshot())
        latest = tmp_path / "latest.json"

        with pytest.raises(SystemExit) as exc_info:
            main(baseline_path=baseline, latest_path=latest)
        assert exc_info.value.code != 0

        captured = capsys.readouterr()
        assert "latest" in captured.err
        assert "not found" in captured.err

    def test_malformed_baseline_exits_nonzero(self, tmp_path: Path, capsys) -> None:
        baseline = tmp_path / "baseline.json"
        baseline.write_text("{corrupt")
        latest = tmp_path / "latest.json"
        _write_snapshot(latest, _make_snapshot())

        with pytest.raises(SystemExit) as exc_info:
            main(baseline_path=baseline, latest_path=latest)
        assert exc_info.value.code != 0

        captured = capsys.readouterr()
        assert "malformed JSON" in captured.err

    def test_malformed_latest_exits_nonzero(self, tmp_path: Path, capsys) -> None:
        baseline = tmp_path / "baseline.json"
        _write_snapshot(baseline, _make_snapshot())
        latest = tmp_path / "latest.json"
        latest.write_text("[bad")

        with pytest.raises(SystemExit) as exc_info:
            main(baseline_path=baseline, latest_path=latest)
        assert exc_info.value.code != 0

        captured = capsys.readouterr()
        assert "malformed JSON" in captured.err

    def test_missing_metric_keys_exits_nonzero(self, tmp_path: Path, capsys) -> None:
        baseline = tmp_path / "baseline.json"
        _write_snapshot(baseline, _make_snapshot())
        latest = tmp_path / "latest.json"
        latest.write_text(
            json.dumps(
                {
                    "metrics": {
                        "merge_rate": {"value": 0.5, "collected_at": _TS},
                    }
                }
            )
        )

        with pytest.raises(SystemExit) as exc_info:
            main(baseline_path=baseline, latest_path=latest)
        assert exc_info.value.code != 0

        captured = capsys.readouterr()
        assert "missing required metric keys" in captured.err

    def test_output_is_valid_json(self, tmp_path: Path, capsys) -> None:
        baseline = tmp_path / "baseline.json"
        latest = tmp_path / "latest.json"
        _write_snapshot(baseline, _make_snapshot())
        _write_snapshot(latest, _make_snapshot())

        main(baseline_path=baseline, latest_path=latest)

        captured = capsys.readouterr()
        report = json.loads(captured.out)
        for delta in report["deltas"]:
            assert "metric" in delta
            assert "baseline" in delta
            assert "latest" in delta
            assert "absolute_delta" in delta
            assert "percent_delta" in delta


# --- subprocess integration ---


def test_script_exits_zero_with_valid_files(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    latest = tmp_path / "latest.json"
    _write_snapshot(baseline, _make_snapshot(merge_rate=0.3))
    _write_snapshot(latest, _make_snapshot(merge_rate=0.6))

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; from eval.cognitive.compare import main; "
            f"main(baseline_path=Path(r'{baseline}'), latest_path=Path(r'{latest}'))",
        ],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert len(report["deltas"]) == 3


def test_script_exits_nonzero_on_missing_file(tmp_path: Path) -> None:
    latest = tmp_path / "latest.json"
    _write_snapshot(latest, _make_snapshot())
    baseline = tmp_path / "baseline.json"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; from eval.cognitive.compare import main; "
            f"main(baseline_path=Path(r'{baseline}'), latest_path=Path(r'{latest}'))",
        ],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "not found" in result.stderr
