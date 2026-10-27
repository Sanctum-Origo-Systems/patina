"""Tests for scripts/generate_eval_report.py — EVAL.md chart fixes (#442)
and metric definitions, denominators, bounds and freshness (#506)."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from scripts.generate_eval_report import (
    DEFINITIONS,
    SNAPSHOT_DIR,
    Rate,
    ReportConfig,
    WeekBucket,
    bucket_weeks,
    compute_metrics,
    generate_report,
    load_config,
    load_snapshots,
    render_cost_chart,
    render_freshness,
    render_overall,
    render_per_module,
    render_pie_chart,
    render_snapshot_history,
    render_success_chart,
    render_trend_table,
    rolling_4_week_rates,
    run_outcome,
    snapshot_history,
)

# ---------------------------------------------------------------------------
# Helpers — build synthetic run_history entries
# ---------------------------------------------------------------------------


def _run(
    ts: str,
    issue: int,
    *,
    success: bool = True,
    attempts: int = 1,
    cost: float = 1.0,
) -> dict:
    return {
        "timestamp": ts,
        "issue": issue,
        "success": success,
        "attempts": attempts,
        "cost_usd": cost,
    }


# ---------------------------------------------------------------------------
# Acceptance test 1 — no false-zero weeks
# ---------------------------------------------------------------------------


class TestNoFalseZeros:
    """No week plots 0% unless it has finished outcomes that all failed."""

    def test_week_with_all_successes_shows_100(self) -> None:
        runs = [
            _run("2026-08-03T10:00:00+00:00", 100),
            _run("2026-08-04T10:00:00+00:00", 101),
        ]
        weeks = bucket_weeks(runs)
        assert len(weeks) == 1
        assert weeks[0].first_attempt_rate == 1.0

    def test_week_with_all_failures_shows_zero(self) -> None:
        """0% is correct when every finished outcome actually failed."""
        runs = [
            _run("2026-08-03T10:00:00+00:00", 200, attempts=2),
            _run("2026-08-04T10:00:00+00:00", 201, attempts=3),
        ]
        weeks = bucket_weeks(runs)
        assert len(weeks) == 1
        assert weeks[0].first_attempt_rate == 0.0
        assert weeks[0].n == 2

    def test_failed_runs_excluded_from_buckets(self) -> None:
        """Unsuccessful runs (success=false) are not counted."""
        runs = [
            _run("2026-08-03T10:00:00+00:00", 300, success=False),
        ]
        weeks = bucket_weeks(runs)
        assert weeks == []

    def test_non_implementation_runs_excluded(self) -> None:
        """Runs with issue=0 (triage/review) are not counted."""
        runs = [
            _run("2026-08-03T10:00:00+00:00", 0),
        ]
        weeks = bucket_weeks(runs)
        assert weeks == []


# ---------------------------------------------------------------------------
# Acceptance test 2 — n labels on bars
# ---------------------------------------------------------------------------


class TestNLabels:
    """Each bar or point shows its n."""

    def test_chart_labels_include_n(self) -> None:
        runs = [
            _run("2026-09-01T10:00:00+00:00", 100),
            _run("2026-09-02T10:00:00+00:00", 101),
            _run("2026-09-03T10:00:00+00:00", 102),
        ]
        weeks = bucket_weeks(runs)
        chart = render_success_chart(weeks)
        assert "(n=3)" in chart

    def test_cost_chart_labels_include_n(self) -> None:
        runs = [
            _run("2026-09-01T10:00:00+00:00", 100, cost=0.50),
            _run("2026-09-02T10:00:00+00:00", 101, cost=1.50),
        ]
        weeks = bucket_weeks(runs)
        chart = render_cost_chart(weeks)
        assert "(n=2)" in chart

    def test_label_with_n_format(self) -> None:
        wb = WeekBucket(
            week_start=date(2026, 9, 28),
            n=9,
            first_attempt_successes=7,
            avg_cost_usd=1.23,
        )
        assert wb.label_with_n == "9/28 (n=9)"


# ---------------------------------------------------------------------------
# Acceptance test 3 — pending-only weeks produce no bar
# ---------------------------------------------------------------------------


class TestPendingWeeks:
    """A fixture week with only pending outcomes shows no bar."""

    def test_no_bar_for_week_with_no_completed_runs(self) -> None:
        """If all implementations are pending (no success=true entries),
        no bar appears for that week."""
        runs = [
            _run("2026-09-01T10:00:00+00:00", 100),
            # Week of 9/8: only a failed run — pending outcome
            _run("2026-09-08T10:00:00+00:00", 200, success=False),
            _run("2026-09-15T10:00:00+00:00", 300),
        ]
        weeks = bucket_weeks(runs)
        week_starts = [w.week_start for w in weeks]
        # Week of 9/8 should not appear
        assert date(2026, 9, 8) not in week_starts
        assert len(weeks) == 2

    def test_chart_omits_pending_week(self) -> None:
        runs = [
            _run("2026-09-01T10:00:00+00:00", 100),
            _run("2026-09-08T10:00:00+00:00", 200, success=False),
            _run("2026-09-15T10:00:00+00:00", 300),
        ]
        weeks = bucket_weeks(runs)
        chart = render_success_chart(weeks)
        assert "9/8" not in chart


# ---------------------------------------------------------------------------
# Acceptance test 4 — chart values match table for the same week
# ---------------------------------------------------------------------------


class TestChartTableConsistency:
    """Chart values match the table for the same week."""

    def test_rates_match_between_chart_and_table(self) -> None:
        runs = [
            _run("2026-08-04T10:00:00+00:00", 100),
            _run("2026-08-05T10:00:00+00:00", 101, attempts=2),
            _run("2026-08-06T10:00:00+00:00", 102),
            _run("2026-08-11T10:00:00+00:00", 200),
        ]
        weeks = bucket_weeks(runs)

        table = render_trend_table(weeks)
        chart = render_success_chart(weeks)

        # Week of 8/3 (Monday): 3 implementations, 2 first-attempt → 67%
        assert "| 2026-08-03 | 3 | 67% |" in table
        # The chart should show 67 in the bar data
        bar_match = re.search(r"bar \[(.+)\]", chart)
        assert bar_match
        bar_values = [int(v.strip()) for v in bar_match.group(1).split(",")]
        assert bar_values[0] == 67

    def test_single_week_consistency(self) -> None:
        runs = [
            _run("2026-10-06T10:00:00+00:00", 400),
            _run("2026-10-07T10:00:00+00:00", 401),
            _run("2026-10-08T10:00:00+00:00", 402),
            _run("2026-10-09T10:00:00+00:00", 403, attempts=3),
        ]
        weeks = bucket_weeks(runs)
        assert len(weeks) == 1
        assert weeks[0].n == 4
        assert weeks[0].first_attempt_rate == 0.75

        table = render_trend_table(weeks)
        assert "75%" in table

        chart = render_success_chart(weeks)
        assert "75" in chart


# ---------------------------------------------------------------------------
# Chart format
# ---------------------------------------------------------------------------


class TestChartFormat:
    """Charts use bars, not lines, for per-week data."""

    def test_success_chart_uses_bar(self) -> None:
        runs = [_run("2026-08-04T10:00:00+00:00", 100)]
        weeks = bucket_weeks(runs)
        chart = render_success_chart(weeks)
        assert "bar [" in chart

    def test_success_chart_has_title(self) -> None:
        runs = [_run("2026-08-04T10:00:00+00:00", 100)]
        weeks = bucket_weeks(runs)
        chart = render_success_chart(weeks)
        assert "per Week" in chart

    def test_cost_chart_uses_bar(self) -> None:
        runs = [_run("2026-08-04T10:00:00+00:00", 100, cost=0.50)]
        weeks = bucket_weeks(runs)
        chart = render_cost_chart(weeks)
        assert "bar [" in chart

    def test_cost_chart_has_title(self) -> None:
        runs = [_run("2026-08-04T10:00:00+00:00", 100, cost=0.50)]
        weeks = bucket_weeks(runs)
        chart = render_cost_chart(weeks)
        assert "per Week" in chart

    def test_success_chart_has_rolling_trend_line(self) -> None:
        runs = [
            _run("2026-08-04T10:00:00+00:00", 100),
            _run("2026-08-11T10:00:00+00:00", 200),
        ]
        weeks = bucket_weeks(runs)
        chart = render_success_chart(weeks)
        assert "line [" in chart

    def test_empty_runs_no_chart(self) -> None:
        assert render_success_chart([]) == ""
        assert render_cost_chart([]) == ""


# ---------------------------------------------------------------------------
# Rolling 4-week rate
# ---------------------------------------------------------------------------


class TestRolling4Week:
    def test_single_week(self) -> None:
        weeks = [WeekBucket(date(2026, 8, 4), n=10, first_attempt_successes=8, avg_cost_usd=1.0)]
        rates = rolling_4_week_rates(weeks)
        assert rates == [0.8]

    def test_rolling_window(self) -> None:
        weeks = [
            WeekBucket(date(2026, 8, 4), n=10, first_attempt_successes=10, avg_cost_usd=1.0),
            WeekBucket(date(2026, 8, 11), n=10, first_attempt_successes=0, avg_cost_usd=1.0),
            WeekBucket(date(2026, 8, 18), n=10, first_attempt_successes=10, avg_cost_usd=1.0),
            WeekBucket(date(2026, 8, 25), n=10, first_attempt_successes=0, avg_cost_usd=1.0),
        ]
        rates = rolling_4_week_rates(weeks)
        # All 4 weeks are within the 4-week window at position 3
        assert rates[3] == 20 / 40  # 0.5

    def test_old_week_drops_out(self) -> None:
        weeks = [
            WeekBucket(date(2026, 8, 4), n=10, first_attempt_successes=10, avg_cost_usd=1.0),
            WeekBucket(date(2026, 8, 11), n=10, first_attempt_successes=0, avg_cost_usd=1.0),
            WeekBucket(date(2026, 8, 18), n=10, first_attempt_successes=0, avg_cost_usd=1.0),
            WeekBucket(date(2026, 8, 25), n=10, first_attempt_successes=0, avg_cost_usd=1.0),
            WeekBucket(date(2026, 9, 1), n=10, first_attempt_successes=0, avg_cost_usd=1.0),
        ]
        rates = rolling_4_week_rates(weeks)
        # Week of 8/4 (100%) should drop out by week of 9/1
        assert rates[4] == 0.0


# ---------------------------------------------------------------------------
# Week bucketing edge cases
# ---------------------------------------------------------------------------


class TestBucketWeeksEdgeCases:
    def test_mixed_week(self) -> None:
        """Mix of first-attempt and multi-attempt in same week."""
        runs = [
            _run("2026-08-04T10:00:00+00:00", 100, attempts=1),
            _run("2026-08-05T10:00:00+00:00", 101, attempts=2),
            _run("2026-08-06T10:00:00+00:00", 102, attempts=1),
            _run("2026-08-07T10:00:00+00:00", 103, attempts=1),
        ]
        weeks = bucket_weeks(runs)
        assert len(weeks) == 1
        assert weeks[0].n == 4
        assert weeks[0].first_attempt_successes == 3
        assert weeks[0].first_attempt_rate == 0.75

    def test_multiple_weeks(self) -> None:
        runs = [
            _run("2026-08-04T10:00:00+00:00", 100),
            _run("2026-08-11T10:00:00+00:00", 200),
            _run("2026-08-12T10:00:00+00:00", 201),
        ]
        weeks = bucket_weeks(runs)
        assert len(weeks) == 2
        assert weeks[0].n == 1
        assert weeks[1].n == 2

    def test_avg_cost(self) -> None:
        runs = [
            _run("2026-08-04T10:00:00+00:00", 100, cost=1.00),
            _run("2026-08-05T10:00:00+00:00", 101, cost=3.00),
        ]
        weeks = bucket_weeks(runs)
        assert weeks[0].avg_cost_usd == 2.00


# ---------------------------------------------------------------------------
# #506 — definitions, denominators, pending outcomes, bounds, freshness
# ---------------------------------------------------------------------------


def _pr_run(
    ts: str,
    issue: int,
    *,
    pr_state: str = "merged",
    attempts: int = 1,
    human_edited: bool = False,
    cost: float = 1.0,
) -> dict:
    return {
        **_run(ts, issue, attempts=attempts, cost=cost),
        "run_type": "implement",
        "pr_state": pr_state,
        "human_edited": human_edited,
    }


def _snapshot(day: str, merged: int, edited: int, **extra: object) -> dict:
    return {
        "date": day,
        "merged_pr_count": merged,
        "human_edit_count": edited,
        "modules": {},
        **extra,
    }


def _write_fixture(tmp_path: Path, runs: list[dict], snapshots: list[dict]) -> tuple[Path, Path]:
    snap_dir = tmp_path / "eval_snapshots"
    snap_dir.mkdir()
    for s in snapshots:
        (snap_dir / f"{s['date']}.json").write_text(json.dumps(s))
    history = tmp_path / "run_history.jsonl"
    history.write_text("".join(json.dumps(r) + "\n" for r in runs))
    return snap_dir, history


PATINA = ReportConfig(repo="Example-Org/patina")
AUTOLOOP = ReportConfig(repo="Example-Org/autoloop")
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def _ten_merged_three_open() -> list[dict]:
    runs = [
        _pr_run(f"2026-10-2{i % 5}T10:00:00+00:00", 500 + i, attempts=1 if i < 7 else 2)
        for i in range(10)
    ]
    runs += [_pr_run("2026-10-26T10:00:00+00:00", 600 + i, pr_state="open") for i in range(3)]
    return runs


def _all_percentages(text: str) -> list[int]:
    return [int(v) for v in re.findall(r"(\d+)%", text)]


class TestRateBounds:
    """Acceptance 1 — the 333% shape is marked invalid, never printed."""

    def test_rate_over_denominator_is_invalid(self) -> None:
        rate = Rate(10, 3)
        assert not rate.valid
        assert rate.value is None
        assert rate.render() == "invalid"

    def test_negative_count_is_invalid(self) -> None:
        assert Rate(-1, 3).render() == "invalid"

    def test_zero_denominator_renders_dash(self) -> None:
        assert Rate(0, 0).render() == "—"

    def test_snapshot_333_shape_marked_invalid(self, caplog: pytest.LogCaptureFixture) -> None:
        snaps = [
            _snapshot("2026-10-15", merged=106, edited=27),
            _snapshot("2026-10-17", merged=109, edited=37, period_human_edit_rate=3.33),
        ]
        with caplog.at_level(logging.WARNING):
            rows = snapshot_history(snaps)
        assert rows[0].human_edit == Rate(10, 3)
        assert not rows[0].human_edit.valid
        assert "2026-10-17 human edit rate" in caplog.text

        table = render_snapshot_history(rows)
        assert "| 2026-10-17 | 3 | 10 | invalid |" in table
        assert "333" not in table

    def test_report_has_no_value_above_100(self, tmp_path: Path) -> None:
        snaps = [
            _snapshot("2026-10-15", merged=106, edited=27),
            _snapshot("2026-10-17", merged=109, edited=37, period_human_edit_rate=3.33),
        ]
        snap_dir, history = _write_fixture(tmp_path, _ten_merged_three_open(), snaps)
        report = generate_report(snap_dir, history, config=PATINA, now=NOW)
        assert "invalid" in report
        assert "333" not in report
        assert all(v <= 100 for v in _all_percentages(report))

    def test_committed_history_row_above_100_is_invalid(self) -> None:
        """The published 2026-10-17 row (333%) is recomputed as invalid."""
        rows = {r.date: r for r in snapshot_history(load_snapshots(SNAPSHOT_DIR))}
        assert not rows["2026-10-17"].human_edit.valid
        assert all(r.human_edit.value is None or r.human_edit.value <= 1 for r in rows.values())

    def test_stored_module_rate_above_one_is_withheld(self) -> None:
        snap = {
            "modules": {
                "src/demo/": {
                    "implementations": 3,
                    "first_attempt_rate": 3.33,
                    "avg_cost_usd": 1.0,
                }
            }
        }
        assert "| src/demo/ | invalid |" in render_per_module(snap)
        assert "333" not in render_pie_chart(snap)


class TestPendingOutcomes:
    """Acceptance 2 — pending outcomes stay out of every denominator."""

    def test_open_prs_excluded_from_denominator(self) -> None:
        m = compute_metrics(_ten_merged_three_open())
        assert m.first_attempt == Rate(7, 10)
        assert m.first_attempt.value == 0.7
        assert m.pending == 3
        assert m.human_edit.denominator == 10
        assert m.issues == 10

    def test_overall_shows_70_with_pending(self) -> None:
        overall = render_overall(compute_metrics(_ten_merged_three_open()))
        assert "70%" in overall
        assert "pending: 3" in overall
        assert "54%" not in overall  # 7/13

    def test_run_outcome_classification(self) -> None:
        assert run_outcome({"success": True, "pr_state": "merged"}) == "resolved"
        assert run_outcome({"success": True, "pr_state": "closed"}) == "resolved"
        assert run_outcome({"success": True, "pr_state": "open"}) == "pending"
        assert run_outcome({"success": True, "pr_state": None}) == "pending"
        assert run_outcome({"pr_state": "open"}) == "pending"
        assert run_outcome({"success": False}) == "failed"
        assert run_outcome({"success": True}) == "resolved"  # legacy row

    def test_triage_runs_excluded(self) -> None:
        runs = [
            _pr_run("2026-10-20T10:00:00+00:00", 700),
            {**_pr_run("2026-10-20T11:00:00+00:00", 700, attempts=3), "run_type": "triage"},
        ]
        assert compute_metrics(runs).first_attempt == Rate(1, 1)

    def test_human_edit_rate_counts_merged_only(self) -> None:
        runs = [
            _pr_run("2026-10-20T10:00:00+00:00", 800, human_edited=True),
            _pr_run("2026-10-20T10:00:00+00:00", 801),
            _pr_run("2026-10-20T10:00:00+00:00", 802, pr_state="closed", human_edited=True),
            _pr_run("2026-10-20T10:00:00+00:00", 803, pr_state="open", human_edited=True),
        ]
        assert compute_metrics(runs).human_edit == Rate(1, 2)

    def test_pending_only_week_shows_pending_count(self) -> None:
        runs = [
            _pr_run("2026-10-12T10:00:00+00:00", 900),
            _pr_run("2026-10-19T10:00:00+00:00", 901, pr_state="open"),
        ]
        assert [w.week_start for w in bucket_weeks(runs)] == [date(2026, 10, 12)]
        weeks = bucket_weeks(runs, include_pending_only=True)
        table = render_trend_table(weeks)
        assert "| 2026-10-19 | 0 | — | — | — | 1 |" in table
        assert "10/19" not in render_success_chart(weeks)


class TestSharedCodePath:
    """Acceptance 3 — patina- and autoloop-shaped configs give identical metrics."""

    def test_identical_metrics_for_both_configs(self, tmp_path: Path) -> None:
        snaps = [
            _snapshot("2026-10-25", merged=10, edited=2),
            _snapshot("2026-10-26", merged=13, edited=3),
        ]
        snap_dir, history = _write_fixture(tmp_path, _ten_merged_three_open(), snaps)
        patina = generate_report(snap_dir, history, config=PATINA, now=NOW)
        autoloop = generate_report(snap_dir, history, config=AUTOLOOP, now=NOW)

        patina_title, patina_body = patina.split("\n", 1)
        autoloop_title, autoloop_body = autoloop.split("\n", 1)
        assert patina_title != autoloop_title
        assert patina_body == autoloop_body

    def test_load_config_reads_repo(self, tmp_path: Path) -> None:
        toml = tmp_path / "autoloop.toml"
        toml.write_text('repo = "Example-Org/autoloop"\nimpl_model = "x"\n')
        assert load_config(toml) == AUTOLOOP
        assert AUTOLOOP.name == "autoloop"


class TestFreshness:
    """Acceptance 4 — reports from data older than 48 h are flagged stale."""

    def test_stale_flag_when_older_than_48h(self) -> None:
        runs = [_pr_run("2026-10-24T10:00:00+00:00", 1000)]
        text = render_freshness(runs, now=datetime(2026, 10, 26, 11, 0, tzinfo=UTC))
        assert "Data as of 2026-10-24 10:00 UTC, 1 history rows." in text
        assert "Stale" in text
        assert "49 h old" in text

    def test_fresh_within_48h(self) -> None:
        runs = [_pr_run("2026-10-24T10:00:00+00:00", 1000)]
        text = render_freshness(runs, now=datetime(2026, 10, 26, 9, 0, tzinfo=UTC))
        assert "Stale" not in text

    def test_no_history_is_stale(self) -> None:
        assert "Stale" in render_freshness([], now=NOW)

    def test_report_shows_stale_flag(self, tmp_path: Path) -> None:
        snap_dir, history = _write_fixture(tmp_path, _ten_merged_three_open(), [])
        report = generate_report(snap_dir, history, config=PATINA, now=NOW + timedelta(days=3))
        assert "13 history rows" in report
        assert "> **Stale:**" in report


class TestDefinitions:
    """Acceptance 5 — the generated EVAL.md documents every metric."""

    def test_definitions_section_present(self, tmp_path: Path) -> None:
        snap_dir, history = _write_fixture(tmp_path, _ten_merged_three_open(), [])
        report = generate_report(snap_dir, history, config=PATINA, now=NOW)
        assert "## Metric Definitions" in report
        assert "| Metric | Numerator | Denominator | Run types | Window |" in report
        for metric in ("First-attempt success", "Human edit rate", "Avg cost/issue", "Pending"):
            assert f"| {metric} |" in DEFINITIONS
