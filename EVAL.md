# EVAL Report

Report date 2026-11-18: data as of 2026-11-18T03:07:50.978633+00:00, 300 history rows.

## Overall

| Metric | Value | Pending |
|--------|-------|---------|
| Total PRs | 170 | — |
| First-attempt success | 90% (n=159 implement runs) | pending: 5 |
| Avg cost/run | $1.74 (n=164 implement runs) | included |
| Avg review cost/run | $0.26 (n=52 implement runs) | included |
| Human edit rate | 35% (n=165 merged PRs; edited by a human PR within 7 days) | pending: 5 |

## Charts

```mermaid
xychart-beta horizontal
    title "Weekly First-Attempt Success Rate (2026)"
    x-axis ["7/20 (n=0)", "7/27 (n=1)", "8/3 (n=24)", "8/10 (n=2)", "8/24 (n=23)", "8/31 (n=8)", "9/7 (n=4)", "9/20 (n=3)", "10/4 (n=27)", "10/11 (n=2)", "10/18 (n=7)", "10/25 (n=2)", "11/1 (n=4)", "11/8 (n=12)", "11/15 (n=16)"]
    y-axis "Success %" 0 --> 100
    bar [0, 100, 71, 100, 87, 75, 100, 67, 74, 0, 43, 50, 100, 83, 100]
```

> bars before 10/26 count triage runs as implementations (#400)

```mermaid
xychart-beta horizontal
    title "Weekly Avg Cost/PR (2026)"
    x-axis ["7/20 (n=0)", "7/27 (n=1)", "8/3 (n=24)", "8/10 (n=2)", "8/24 (n=23)", "8/31 (n=8)", "9/7 (n=4)", "9/20 (n=3)", "10/4 (n=27)", "10/11 (n=2)", "10/18 (n=7)", "10/25 (n=2)", "11/1 (n=4)", "11/8 (n=12)", "11/15 (n=16)"]
    y-axis "Cost ($)" 0 --> 2
    bar [0.00, 0.59, 0.80, 0.38, 0.83, 0.86, 0.64, 0.36, 0.94, 0.35, 0.38, 0.27, 1.24, 1.04, 1.40]
```

> bars before 10/26 count triage runs as implementations (#400)

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'pie1': '#4CAF50', 'pie2': '#2196F3', 'pie3': '#FF9800', 'pie4': '#E91E63', 'pie5': '#9C27B0', 'pie6': '#00BCD4', 'pieTitleTextColor': '#aaa', 'pieLegendTextColor': '#aaa', 'pieSectionTextColor': '#fff'}}}%%
pie title Attempt Distribution by Module
    "other (80%, 22 impl)" : 22
    "src/patina/ (96%, 113 impl)" : 113
    "src/patina/adapters/ (78%, 15 impl)" : 15
    "src/patina/autonomy/ (67%, 3 impl)" : 3
    "src/patina/beliefs/ (80%, 12 impl)" : 12
    "src/patina/mcp/ (100%, 9 impl)" : 9
    "src/patina/priority/ (100%, 2 impl)" : 2
```

## Auto-Merge Gate (repo-level)

| Metric | Value | Threshold |
|--------|-------|-----------|
| Success rate | 90% | >90% |
| Edit rate | 35% | <5% |
| Clean merges | 107 | ≥10 |
| **Ready?** | **No** | |

## Per-Module Breakdown

| Module | Success | Avg Cost | Impl | Auto-merge ready? |
|--------|---------|----------|------|--------------------|
| other | 80% (n=20 runs) | $1.80 (n=21 runs) | 22 | No |
| src/patina/ | 96% (n=105 runs) | $1.85 (n=108 runs) | 113 | No |
| src/patina/adapters/ | insufficient data (n=9 runs) | insufficient data (n=9 runs) | 15 | No |
| src/patina/autonomy/ | insufficient data (n=3 runs) | insufficient data (n=3 runs) | 3 | No |
| src/patina/beliefs/ | insufficient data (n=10 runs) | insufficient data (n=11 runs) | 12 | No |
| src/patina/mcp/ | insufficient data (n=7 runs) | insufficient data (n=7 runs) | 9 | No |
| src/patina/priority/ | insufficient data (n=2 runs) | insufficient data (n=2 runs) | 2 | No |

## Trend

| Date (UTC) | New PRs | First-attempt | Avg Cost | Human Edits |
|------|---------|---------------|----------|-------------|
| 2026-07-20 | 14 | 0% | $0.00 | 0% |
| 2026-07-27 | 1 | 100% | $0.59 | 0% |
| 2026-08-03 | 14 | 71% | $0.80 | 21% |
| 2026-08-10 | 1 | 100% | $0.38 | 100% |
| 2026-08-24 | 9 | 87% | $0.83 | 0% |
| 2026-08-31 | 6 | 75% | $0.86 | 0% |
| 2026-09-07 | 2 | 100% | $0.64 | 50% |
| 2026-09-19 | 1 | 100% | $0.15 | 0% |
| 2026-09-20 | 0 | 0% | $0.77 | — |
| 2026-09-21 | 0 | — | — | — |
| 2026-09-22 | 0 | — | — | — |
| 2026-09-23 | 0 | — | — | — |
| 2026-09-24 | 0 | — | — | — |
| 2026-09-25 | 0 | — | — | — |
| 2026-09-26 | 0 | — | — | — |
| 2026-09-28 | 8 | 70% | $2.04 | 0% |
| 2026-09-29 | 1 | 100% | $0.18 | 0% |
| 2026-09-30 | 0 | — | — | — |
| 2026-10-01 | 0 | — | — | — |
| 2026-10-03 | 11 | 92% | $0.18 | 0% |
| 2026-10-04 | 10 | 0% | $0.82 | 0% |
| 2026-10-05 | 2 | 0% | $0.00 | 0% |
| 2026-10-06 | 3 | 0% | $0.81 | 0% |
| 2026-10-07 | 0 | — | — | — |
| 2026-10-08 | 2 | — | — | — |
| 2026-10-09 | 9 | — | — | — |
| 2026-10-10 | 4 | — | — | — |
| 2026-10-11 | 0 | — | — | — |
| 2026-10-12 | 4 | 0% | $0.81 | — |
| 2026-10-13 | 1 | — | — | — |
| 2026-10-14 | 2 | 50% | $0.33 | 0% |
| 2026-10-15 | 3 | 0% | $0.80 | 0% |
| 2026-10-17 | 1 | 100% | $0.00 | invalid |
| 2026-10-18 | 1 | 50% | $0.28 | 100% |
| 2026-10-19 | 4 | 0% | $0.78 | 0% |
| 2026-10-20 | 0 | — | — | — |
| 2026-10-21 | 1 | 100% | $0.00 | — |
| 2026-10-22 | 0 | — | — | — |
| 2026-10-23 | 0 | — | — | — |
| 2026-10-24 | 0 | — | — | — |
| 2026-10-25 | 0 | — | — | — |
| 2026-10-26 (baseline break) | 1 | 87% | $1.98 | 43% |
| 2026-10-27 | 3 | 100% | $1.70 | — |
| 2026-10-28 (baseline break) | 9 | 100% | $1.57 | 28% |
| 2026-10-29 | 2 | 100% | $1.33 | 0% |
| 2026-10-30 | 4 | 100% | $0.66 | 0% |
| 2026-10-31 | 2 | 100% | $1.89 | 0% |
| 2026-11-01 | 2 | 100% | $0.58 | invalid |
| 2026-11-02 | 2 | 100% | $0.54 | 0% |
| 2026-11-03 | 4 | — | $0.48 | — |
| 2026-11-04 | 3 | 80% | $2.28 | 0% |
| 2026-11-05 | 0 | — | — | — |
| 2026-11-06 | 0 | — | — | — |
| 2026-11-07 | 2 | — | $1.11 | — |
| 2026-11-08 | 1 | 100% | $0.38 | 0% |
| 2026-11-09 | 15 | 100% | $1.48 | 27% |
| 2026-11-10 | 0 | — | — | — |
| 2026-11-11 | 1 | — | $0.18 | — |
| 2026-11-12 | 0 | — | — | — |
| 2026-11-13 | 0 | — | — | — |
| 2026-11-14 | 0 | — | — | — |
| 2026-11-15 | 0 | — | — | — |
| 2026-11-16 | 0 | — | — | — |
| 2026-11-17 | 0 | — | — | — |
| 2026-11-18 | 5 | — | $1.10 | — |

> Baseline break at 2026-10-26: earlier snapshots counted triage runs as implementations (#400), so their first-attempt and cost values are not comparable with later rows.

> Baseline break at 2026-10-28: human edits are counted under a 7-day window from this row on, so earlier human edit rates are not comparable with later rows.

## Definitions

| Metric | Numerator | Denominator | Counts | Window |
|--------|-----------|-------------|--------|--------|
| First-attempt success | implement runs that succeeded with attempts == 1 | implement runs with an outcome (pending runs excluded) | `run_history` rows with type "implement" and a non-zero issue (triage, review and issue-0 rows are excluded) | Overall: lifetime. Trend: change since the previous snapshot (snapshots without outcome counts use the attempt distribution) |
| Human edit rate | merged PRs with a non-autoloop PR merged within the fixup window that touches the same files (bookkeeping files, release and eval-report PRs are ignored) | merged PRs (open PRs are pending; closed unmerged PRs excluded) | PRs from `autoloop/` branches, up to the 500 most recent | Overall: lifetime. Trend: new edits / new merges since the previous snapshot; invalid when edits exceed merges (older PRs flagged late) |
| Avg cost/run | sum of implementation cost over implement runs: `impl_cost_usd` when logged, else `cost_usd` (rows before #451 never included review cost) | implement runs, pending included (cost is known when a run ends) | `run_history` rows with type "implement" and a non-zero issue (triage, review and issue-0 rows are excluded) | Overall: lifetime. Trend: change in total cost / change in implement runs |
| Avg review cost/run | sum of `review_cost_usd` over implement runs that logged it | implement runs with `review_cost_usd` (none is imputed for older rows) | `run_history` rows with type "implement" and a non-zero issue (triage, review and issue-0 rows are excluded); logged from #451 onward only | Overall: lifetime, shown only when n > 0 |

Pending: a successful implement run whose PR is still open, or an open PR. Pending items are left out of outcome-dependent denominators and shown as a separate pending count. Any rate whose numerator exceeds its denominator renders as invalid.
