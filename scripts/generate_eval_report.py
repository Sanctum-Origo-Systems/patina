"""Generate EVAL.md from autoloop run history and eval snapshots.

Every rate in the report comes from one code path, ``compute_metrics``, which
reads only the run history.  The repo config supplies the title, never the
numbers, so the same history gives the same metrics for any repo (#506).

Daily snapshots feed the per-module breakdown and the snapshot history table.
"""

from __future__ import annotations

import json
import logging
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = PROJECT_ROOT / "autoloop" / "eval_snapshots"
RUN_HISTORY = PROJECT_ROOT / "autoloop" / "run_history.jsonl"
AUTOLOOP_TOML = PROJECT_ROOT / "autoloop.toml"
EVAL_MD = PROJECT_ROOT / "EVAL.md"

STALE_AFTER = timedelta(hours=48)
FINAL_PR_STATES = ("merged", "closed")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rate:
    """A count ratio that is only reported when it lies in [0, 1]."""

    numerator: int
    denominator: int

    @property
    def valid(self) -> bool:
        return 0 <= self.numerator <= self.denominator

    @property
    def value(self) -> float | None:
        """Fraction in [0, 1], or None when invalid or the denominator is 0."""
        if not self.valid or self.denominator == 0:
            return None
        return self.numerator / self.denominator

    def render(self) -> str:
        if not self.valid:
            return "invalid"
        if self.value is None:
            return "—"
        return f"{round(self.value * 100)}%"


def checked_rate(numerator: int, denominator: int, context: str) -> Rate:
    """Build a Rate, logging it when the counts are impossible."""
    rate = Rate(numerator, denominator)
    if not rate.valid:
        logger.warning(
            "Invalid rate for %s: numerator %d, denominator %d — value withheld",
            context,
            numerator,
            denominator,
        )
    return rate


def _fraction_pct(value: float | None, context: str) -> str:
    """Render a stored fraction (snapshot field), withholding values outside [0, 1]."""
    if value is None:
        return "—"
    if not 0 <= value <= 1:
        logger.warning("Invalid stored rate for %s: %s — value withheld", context, value)
        return "invalid"
    return f"{round(value * 100)}%"


# ---------------------------------------------------------------------------
# Run classification and metrics (the single shared code path)
# ---------------------------------------------------------------------------


def is_implement_run(run: dict) -> bool:
    """True for implement runs; triage/review runs are excluded (#400).

    Uses ``run_type`` when recorded; legacy rows fall back to ``issue > 0``.
    """
    run_type = run.get("run_type")
    if run_type is not None:
        return run_type == "implement"
    return run.get("issue", 0) > 0


def run_outcome(run: dict) -> str:
    """Classify an implement run as ``resolved``, ``pending`` or ``failed``.

    - pending: no ``success`` flag yet, or a PR state is recorded but the PR
      is not merged or closed (open PR).
    - failed: the run produced no PR (``success`` is false).
    - resolved: the run succeeded and its PR merged or closed.  Legacy rows
      without ``pr_state`` count as resolved when ``success`` is true.
    """
    if "success" not in run:
        return "pending"
    if not run["success"]:
        return "failed"
    if "pr_state" in run and run["pr_state"] not in FINAL_PR_STATES:
        return "pending"
    return "resolved"


@dataclass(frozen=True)
class PeriodMetrics:
    first_attempt: Rate
    human_edit: Rate
    total_cost_usd: float
    issues: int
    pending: int

    @property
    def cost_per_issue(self) -> float | None:
        return self.total_cost_usd / self.issues if self.issues else None

    @property
    def clean_merges(self) -> int:
        return self.human_edit.denominator - self.human_edit.numerator


def compute_metrics(runs: list[dict], context: str = "overall") -> PeriodMetrics:
    """Compute every reported metric for one period of run history.

    Pending outcomes are counted separately and never enter a denominator.
    """
    implement = [r for r in runs if is_implement_run(r)]
    resolved = [r for r in implement if run_outcome(r) == "resolved"]
    pending = sum(1 for r in implement if run_outcome(r) == "pending")
    merged = [r for r in resolved if r.get("pr_state") == "merged"]

    first_attempt = checked_rate(
        sum(1 for r in resolved if r.get("attempts", 0) == 1),
        len(resolved),
        f"{context} first-attempt success",
    )
    human_edit = checked_rate(
        sum(1 for r in merged if r.get("human_edited", False)),
        len(merged),
        f"{context} human edit rate",
    )
    return PeriodMetrics(
        first_attempt=first_attempt,
        human_edit=human_edit,
        total_cost_usd=sum(r.get("cost_usd", 0.0) for r in resolved),
        issues=len({r.get("issue") for r in resolved}),
        pending=pending,
    )


@dataclass
class WeekBucket:
    week_start: date
    n: int
    first_attempt_successes: int
    avg_cost_usd: float | None
    costs: list[float] = field(default_factory=list, repr=False)
    pending: int = 0
    human_edit: Rate = Rate(0, 0)

    @property
    def first_attempt(self) -> Rate:
        return Rate(self.first_attempt_successes, self.n)

    @property
    def first_attempt_rate(self) -> float:
        return self.first_attempt.value or 0.0

    @property
    def label(self) -> str:
        return f"{self.week_start.month}/{self.week_start.day}"

    @property
    def label_with_n(self) -> str:
        return f"{self.label} (n={self.n})"


def _monday_of(dt: date) -> date:
    """Return the Monday of the ISO week containing *dt*."""
    return dt - timedelta(days=dt.weekday())


def _parse_ts(ts: str) -> datetime:
    """Parse an ISO timestamp, treating naive values as UTC."""
    parsed = datetime.fromisoformat(ts)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportConfig:
    """Repo-specific report settings.  Affects labels only, never metrics."""

    repo: str

    @property
    def name(self) -> str:
        return self.repo.rsplit("/", 1)[-1]


def load_config(path: Path = AUTOLOOP_TOML) -> ReportConfig:
    """Read the repo slug from an autoloop.toml-style config."""
    with open(path, "rb") as fp:
        return ReportConfig(repo=tomllib.load(fp)["repo"])


def load_runs(path: Path) -> list[dict]:
    """Load run_history.jsonl entries."""
    runs: list[dict] = []
    with open(path) as fp:
        for line in fp:
            stripped = line.strip()
            if stripped:
                runs.append(json.loads(stripped))
    return runs


def load_snapshots(snapshot_dir: Path) -> list[dict]:
    """Load and sort all eval snapshot JSON files."""
    snapshots: list[dict] = []
    for f in sorted(snapshot_dir.glob("*.json")):
        with open(f) as fp:
            snapshots.append(json.load(fp))
    return sorted(snapshots, key=lambda s: s["date"])


# ---------------------------------------------------------------------------
# Weekly bucketing (from run_history — ground truth)
# ---------------------------------------------------------------------------


def bucket_weeks(runs: list[dict], *, include_pending_only: bool = False) -> list[WeekBucket]:
    """Group implement runs by ISO week and compute each week's metrics.

    Weeks with no resolved outcome are dropped unless *include_pending_only*
    is set, in which case weeks holding only pending runs are kept (n=0) so
    their pending count can be shown.
    """
    by_week: dict[date, list[dict]] = defaultdict(list)
    for r in runs:
        if not is_implement_run(r):
            continue
        by_week[_monday_of(_parse_ts(r["timestamp"]).date())].append(r)

    buckets: list[WeekBucket] = []
    for ws in sorted(by_week):
        week_runs = by_week[ws]
        m = compute_metrics(week_runs, context=f"week {ws}")
        if m.first_attempt.denominator == 0 and not (include_pending_only and m.pending):
            continue
        cost = m.cost_per_issue
        buckets.append(
            WeekBucket(
                week_start=ws,
                n=m.first_attempt.denominator,
                first_attempt_successes=m.first_attempt.numerator,
                avg_cost_usd=round(cost, 2) if cost is not None else None,
                costs=[r.get("cost_usd", 0.0) for r in week_runs if run_outcome(r) == "resolved"],
                pending=m.pending,
                human_edit=m.human_edit,
            )
        )
    return buckets


# ---------------------------------------------------------------------------
# Rolling 4-week rate
# ---------------------------------------------------------------------------


def rolling_4_week_rates(weeks: list[WeekBucket]) -> list[float | None]:
    """Compute rolling 4-week first-attempt rate for each week."""
    rates: list[float | None] = []
    for i, w in enumerate(weeks):
        cutoff = w.week_start - timedelta(weeks=3)
        window = [wk for wk in weeks[: i + 1] if wk.week_start >= cutoff]
        total_n = sum(wk.n for wk in window)
        if total_n == 0:
            rates.append(None)
        else:
            total_ok = sum(wk.first_attempt_successes for wk in window)
            rates.append(total_ok / total_n)
    return rates


# ---------------------------------------------------------------------------
# Snapshot history (recomputed from cumulative counts)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnapshotRow:
    date: str
    new_merged: int
    new_human_edited: int
    human_edit: Rate


def snapshot_history(snapshots: list[dict]) -> list[SnapshotRow]:
    """Recompute each snapshot's period human-edit rate from count deltas.

    Stored ``period_*_rate`` fields are ignored; a period whose edit delta
    exceeds its merge delta is kept but marked invalid.
    """
    rows: list[SnapshotRow] = []
    for prev, cur in pairwise(snapshots):
        if not all(k in s for s in (prev, cur) for k in ("merged_pr_count", "human_edit_count")):
            continue
        merged = cur["merged_pr_count"] - prev["merged_pr_count"]
        edited = cur["human_edit_count"] - prev["human_edit_count"]
        rate = checked_rate(edited, merged, f"snapshot {cur['date']} human edit rate")
        rows.append(SnapshotRow(cur["date"], merged, edited, rate))
    return rows


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

DEFINITIONS = "\n".join(
    [
        "## Metric Definitions",
        "",
        "| Metric | Numerator | Denominator | Run types | Window |",
        "|--------|-----------|-------------|-----------|--------|",
        "| First-attempt success | Resolved implement runs with `attempts == 1` "
        "| Resolved implement runs | Implement only "
        "| Overall: all history rows. Trend: ISO week (Mon–Sun, UTC) of the run timestamp. "
        "Chart line: trailing 4 weeks |",
        "| Human edit rate | Merged PRs with a human commit (`human_edited`) "
        '| Resolved implement runs whose PR merged (`pr_state == "merged"`) '
        "| Implement only | Same as above |",
        "| Avg cost/issue | Total `cost_usd` of resolved implement runs "
        "| Distinct issues among those runs | Implement only | Same as above |",
        "| Pending | Implement runs with no final outcome "
        "| — (count, never in a denominator) | Implement only | Same as above |",
        "",
        '- **Implement run:** `run_type == "implement"`; rows without `run_type` count '
        "when `issue > 0`. Triage and review runs are excluded.",
        "- **Resolved:** the run succeeded and its PR merged or closed. Rows without "
        "`pr_state` (older history) count as resolved when `success` is true.",
        "- **Pending:** PR still open, PR state recorded but not merged or closed, or no "
        "`success` flag yet. Shown as a separate count per period.",
        "- **Failed:** runs with `success == false` produce no PR and are left out of "
        "every denominator.",
        "- **Bounds:** rates must lie in [0, 100]%. If a numerator exceeds its denominator "
        "or a count is negative, the row shows `invalid`, the value is withheld, and a "
        "warning is logged.",
        "- **Snapshot history:** per-period human edit rate = Δ`human_edit_count` / "
        "Δ`merged_pr_count` between consecutive daily snapshots; stored period rates are "
        "not used.",
        '- **Freshness:** "data as of" is the newest run history timestamp. The report is '
        "flagged stale when that is more than 48 h before generation.",
    ]
)


def render_freshness(runs: list[dict], now: datetime) -> str:
    stamps = [_parse_ts(r["timestamp"]) for r in runs if r.get("timestamp")]
    if not stamps:
        return "Data as of: unknown, 0 history rows.\n\n> **Stale:** no run history rows."
    as_of = max(stamps)
    line = f"Data as of {as_of.strftime('%Y-%m-%d %H:%M')} UTC, {len(runs)} history rows."
    age = now - as_of
    if age > STALE_AFTER:
        hours = int(age.total_seconds() // 3600)
        line += f"\n\n> **Stale:** source data is {hours} h old (threshold 48 h)."
    return line


def _cost(value: float | None) -> str:
    return f"${value:.2f}" if value is not None else "—"


def render_overall(m: PeriodMetrics) -> str:
    fa, he = m.first_attempt, m.human_edit
    return (
        "## Overall\n\n"
        "| Metric | Value |\n"
        "|--------|-------|\n"
        f"| First-attempt success | {fa.render()} "
        f"({fa.numerator}/{fa.denominator} resolved implement runs; pending: {m.pending}) |\n"
        f"| Human edit rate | {he.render()} ({he.numerator}/{he.denominator} merged PRs) |\n"
        f"| Avg cost/issue | {_cost(m.cost_per_issue)} (n={m.issues} issues) |\n"
        f"| Pending | {m.pending} |"
    )


def render_auto_merge_gate(m: PeriodMetrics) -> str:
    fa, he = m.first_attempt.value, m.human_edit.value
    ready = fa is not None and fa > 0.9 and he is not None and he < 0.05 and m.clean_merges >= 10
    return (
        "## Auto-Merge Gate (repo-level)\n\n"
        "| Metric | Value | Threshold |\n"
        "|--------|-------|----------|\n"
        f"| Success rate | {m.first_attempt.render()} | >90% |\n"
        f"| Edit rate | {m.human_edit.render()} | <5% |\n"
        f"| Clean merges | {m.clean_merges} | ≥10 |\n"
        f"| **Ready?** | **{'Yes' if ready else 'No'}** | |"
    )


def render_per_module(snap: dict) -> str:
    lines = [
        "## Per-Module Breakdown\n",
        "| Module | Success | Avg Cost | Impl | Auto-merge ready? |",
        "|--------|---------|----------|------|--------------------|",
    ]
    for mod, info in snap.get("modules", {}).items():
        sr = _fraction_pct(info.get("first_attempt_rate"), f"module {mod} first-attempt success")
        cost = info["avg_cost_usd"]
        impl = info["implementations"]
        ready = "No"
        lines.append(f"| {mod} | {sr} | ${cost:.2f} | {impl} | {ready} |")
    return "\n".join(lines)


def render_trend_table(weeks: list[WeekBucket]) -> str:
    """Render the per-week trend table.

    Weeks with only pending outcomes show "—" rates and their pending count.
    """
    lines = [
        "## Trend\n",
        "| Week | Implementations | First-attempt | Avg Cost | Human Edits | Pending |",
        "|------|----------------|---------------|----------|-------------|---------|",
    ]
    for w in weeks:
        lines.append(
            f"| {w.week_start} | {w.n} | {w.first_attempt.render()} | {_cost(w.avg_cost_usd)} "
            f"| {w.human_edit.render()} | {w.pending} |"
        )
    return "\n".join(lines)


def render_snapshot_history(rows: list[SnapshotRow]) -> str:
    if not rows:
        return ""
    lines = [
        "## Snapshot History\n",
        "| Date | New merged PRs | New human-edited | Human edit rate |",
        "|------|----------------|------------------|-----------------|",
    ]
    for row in rows:
        rate = row.human_edit.render()
        lines.append(f"| {row.date} | {row.new_merged} | {row.new_human_edited} | {rate} |")
    invalid = sum(1 for row in rows if not row.human_edit.valid)
    if invalid:
        lines.append(
            f"\n> {invalid} row(s) marked invalid: human-edit count exceeded merged PRs "
            "for the period (or a count decreased), so the rate is withheld."
        )
    return "\n".join(lines)


def render_success_chart(weeks: list[WeekBucket]) -> str:
    """Render first-attempt success rate bar chart (xychart-beta)."""
    active = [w for w in weeks if w.n > 0]
    if not active:
        return ""

    labels = ", ".join(f'"{w.label_with_n}"' for w in active)
    values = ", ".join(str(round(w.first_attempt_rate * 100)) for w in active)

    rolling = rolling_4_week_rates(active)
    rolling_vals = ", ".join(str(round(r * 100)) if r is not None else "0" for r in rolling)

    return (
        "```mermaid\n"
        "xychart-beta\n"
        '    title "First-Attempt Success Rate per Week (2026)"\n'
        f"    x-axis [{labels}]\n"
        '    y-axis "Success %" 0 --> 100\n'
        f"    bar [{values}]\n"
        f"    line [{rolling_vals}]\n"
        "```"
    )


def render_cost_chart(weeks: list[WeekBucket]) -> str:
    """Render avg cost/issue bar chart."""
    active = [w for w in weeks if w.n > 0 and w.avg_cost_usd is not None]
    if not active:
        return ""

    labels = ", ".join(f'"{w.label_with_n}"' for w in active)
    max_cost = max(w.avg_cost_usd for w in active)
    y_max = max(1, int(max_cost) + 1)
    values = ", ".join(f"{w.avg_cost_usd:.2f}" for w in active)

    return (
        "```mermaid\n"
        "xychart-beta\n"
        '    title "Avg Cost/Issue per Week (2026)"\n'
        f"    x-axis [{labels}]\n"
        f'    y-axis "Cost ($)" 0 --> {y_max}\n'
        f"    bar [{values}]\n"
        "```"
    )


def render_pie_chart(snap: dict) -> str:
    """Render attempt distribution pie chart by module."""
    lines = [
        "```mermaid",
        "%%{init: {'theme': 'base', 'themeVariables': {"
        "'pie1': '#4CAF50', 'pie2': '#2196F3', 'pie3': '#FF9800', "
        "'pie4': '#E91E63', 'pie5': '#9C27B0', 'pie6': '#00BCD4', "
        "'pieTitleTextColor': '#aaa', 'pieLegendTextColor': '#aaa', "
        "'pieSectionTextColor': '#fff'}}}%%",
        "pie title Attempt Distribution by Module",
    ]
    for mod, info in snap.get("modules", {}).items():
        sr = _fraction_pct(info.get("first_attempt_rate"), f"module {mod} first-attempt success")
        impl = info["implementations"]
        lines.append(f'    "{mod} ({sr}, {impl} impl)" : {impl}')
    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------


def generate_report(
    snapshot_dir: Path = SNAPSHOT_DIR,
    run_history_path: Path = RUN_HISTORY,
    config: ReportConfig | None = None,
    now: datetime | None = None,
) -> str:
    """Generate the complete EVAL.md content."""
    config = config or load_config()
    now = now or datetime.now(UTC)
    snapshots = load_snapshots(snapshot_dir)
    latest = snapshots[-1] if snapshots else {}
    runs = load_runs(run_history_path)
    metrics = compute_metrics(runs)
    weeks = bucket_weeks(runs, include_pending_only=True)

    sections = [
        f"# EVAL Report — {config.name}",
        render_freshness(runs, now),
        DEFINITIONS,
        render_overall(metrics),
        render_auto_merge_gate(metrics),
        render_per_module(latest),
        render_trend_table(weeks),
        render_snapshot_history(snapshot_history(snapshots)),
        render_success_chart(weeks),
        render_cost_chart(weeks),
        render_pie_chart(latest),
    ]
    return "\n\n".join(s for s in sections if s) + "\n"


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    content = generate_report()
    EVAL_MD.write_text(content)
    print(f"Wrote {EVAL_MD}")
