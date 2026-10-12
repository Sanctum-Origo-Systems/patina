"""Generate EVAL.md from autoloop run history and eval snapshots.

Reads run_history.jsonl for per-week chart/table data and the latest
eval snapshot for cumulative overall/module stats.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_DIR = PROJECT_ROOT / "autoloop" / "eval_snapshots"
RUN_HISTORY = PROJECT_ROOT / "autoloop" / "run_history.jsonl"
EVAL_MD = PROJECT_ROOT / "EVAL.md"


@dataclass
class WeekBucket:
    week_start: date
    n: int
    first_attempt_successes: int
    avg_cost_usd: float
    costs: list[float] = field(default_factory=list, repr=False)

    @property
    def first_attempt_rate(self) -> float:
        return self.first_attempt_successes / self.n if self.n else 0.0

    @property
    def label(self) -> str:
        return f"{self.week_start.month}/{self.week_start.day}"

    @property
    def label_with_n(self) -> str:
        return f"{self.label} (n={self.n})"


def _monday_of(dt: date) -> date:
    """Return the Monday of the ISO week containing *dt*."""
    return dt - timedelta(days=dt.weekday())


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


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


def bucket_weeks(runs: list[dict]) -> list[WeekBucket]:
    """Group completed implementations by ISO week.

    Each successful run entry with ``issue > 0`` counts as one completed
    implementation.  ``first_attempt`` means ``attempts == 1``.
    """
    week_data: dict[date, dict] = defaultdict(lambda: {"n": 0, "first_attempt": 0, "costs": []})

    for r in runs:
        if r.get("issue", 0) <= 0:
            continue
        if not r.get("success", False):
            continue
        ts = datetime.fromisoformat(r["timestamp"])
        ws = _monday_of(ts.date())
        week_data[ws]["n"] += 1
        if r.get("attempts", 0) == 1:
            week_data[ws]["first_attempt"] += 1
        week_data[ws]["costs"].append(r.get("cost_usd", 0.0))

    buckets: list[WeekBucket] = []
    for ws in sorted(week_data):
        d = week_data[ws]
        if d["n"] == 0:
            continue
        avg_cost = sum(d["costs"]) / d["n"]
        buckets.append(
            WeekBucket(
                week_start=ws,
                n=d["n"],
                first_attempt_successes=d["first_attempt"],
                avg_cost_usd=round(avg_cost, 2),
                costs=d["costs"],
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
# Markdown rendering
# ---------------------------------------------------------------------------


def render_overall(snap: dict) -> str:
    rate = round(snap["first_attempt_rate"] * 100)
    cost = snap["avg_cost_usd"]
    human = round(snap.get("human_edit_rate", 0) * 100)
    return (
        "## Overall\n\n"
        "| Metric | Value |\n"
        "|--------|-------|\n"
        f"| First-attempt success | {rate}% |\n"
        f"| Avg cost/PR | ${cost:.2f} |\n"
        f"| Human edit rate | {human}% |"
    )


def render_auto_merge_gate(snap: dict) -> str:
    rate = round(snap["first_attempt_rate"] * 100)
    human = round(snap.get("human_edit_rate", 0) * 100)
    merged = sum(m.get("merged_clean_count", 0) for m in snap.get("modules", {}).values())
    ready = rate > 90 and human < 5 and merged >= 10
    return (
        "## Auto-Merge Gate (repo-level)\n\n"
        "| Metric | Value | Threshold |\n"
        "|--------|-------|----------|\n"
        f"| Success rate | {rate}% | >90% |\n"
        f"| Edit rate | {human}% | <5% |\n"
        f"| Clean merges | {merged} | ≥10 |\n"
        f"| **Ready?** | **{'Yes' if ready else 'No'}** | |"
    )


def render_per_module(snap: dict) -> str:
    lines = [
        "## Per-Module Breakdown\n",
        "| Module | Success | Avg Cost | Impl | Auto-merge ready? |",
        "|--------|---------|----------|------|--------------------|",
    ]
    for mod, info in snap.get("modules", {}).items():
        sr = round(info["first_attempt_rate"] * 100)
        cost = info["avg_cost_usd"]
        impl = info["implementations"]
        ready = "No"
        lines.append(f"| {mod} | {sr}% | ${cost:.2f} | {impl} | {ready} |")
    return "\n".join(lines)


def render_trend_table(weeks: list[WeekBucket]) -> str:
    """Render the per-week trend table.

    Only weeks with finished outcomes (n > 0) appear.
    """
    lines = [
        "## Trend\n",
        "| Week | Implementations | First-attempt | Avg Cost |",
        "|------|----------------|---------------|----------|",
    ]
    for w in weeks:
        rate_pct = round(w.first_attempt_rate * 100)
        lines.append(f"| {w.week_start} | {w.n} | {rate_pct}% | ${w.avg_cost_usd:.2f} |")
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
    """Render avg cost/PR bar chart."""
    active = [w for w in weeks if w.n > 0]
    if not active:
        return ""

    labels = ", ".join(f'"{w.label_with_n}"' for w in active)
    max_cost = max(w.avg_cost_usd for w in active if w.avg_cost_usd is not None)
    y_max = max(1, int(max_cost) + 1)
    values = ", ".join(f"{w.avg_cost_usd:.2f}" for w in active)

    return (
        "```mermaid\n"
        "xychart-beta\n"
        '    title "Avg Cost/PR per Week (2026)"\n'
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
        sr = round(info["first_attempt_rate"] * 100)
        impl = info["implementations"]
        lines.append(f'    "{mod} ({sr}%, {impl} impl)" : {impl}')
    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------


def generate_report(
    snapshot_dir: Path = SNAPSHOT_DIR,
    run_history_path: Path = RUN_HISTORY,
) -> str:
    """Generate the complete EVAL.md content."""
    snapshots = load_snapshots(snapshot_dir)
    latest = snapshots[-1] if snapshots else {}
    runs = load_runs(run_history_path)
    weeks = bucket_weeks(runs)

    sections = [
        "# EVAL Report",
        render_overall(latest),
        render_auto_merge_gate(latest),
        render_per_module(latest),
        render_trend_table(weeks),
        render_success_chart(weeks),
        render_cost_chart(weeks),
        render_pie_chart(latest),
        "",
    ]
    return "\n\n".join(sections)


if __name__ == "__main__":
    content = generate_report()
    EVAL_MD.write_text(content)
    print(f"Wrote {EVAL_MD}")
