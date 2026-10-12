"""Tests for scripts/generate_eval_report.py — EVAL.md chart fixes (#442)."""

from __future__ import annotations

import re
from datetime import date

from scripts.generate_eval_report import (
    WeekBucket,
    bucket_weeks,
    render_cost_chart,
    render_success_chart,
    render_trend_table,
    rolling_4_week_rates,
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
