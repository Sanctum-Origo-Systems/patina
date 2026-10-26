# EVAL Report

## Overall

| Metric | Value |
|--------|-------|
| Total PRs | 115 |
| First-attempt success | 87% (n=108 implement runs) |
| Avg cost/run | $1.98 (n=108 implement runs) |
| Human edit rate | 43% (n=115 merged PRs) |

## Auto-Merge Gate (repo-level)

| Metric | Value | Threshold |
|--------|-------|-----------|
| Success rate | 87% | >90% |
| Edit rate | 43% | <5% |
| Clean merges | 65 | ≥10 |
| **Ready?** | **No** | |

## Per-Module Breakdown

| Module | Success | Avg Cost | Impl | Auto-merge ready? |
|--------|---------|----------|------|--------------------|
| other | insufficient data (n=11 runs) | insufficient data (n=11 runs) | 12 | No |
| src/patina/ | 93% (n=72 runs) | $2.18 (n=72 runs) | 77 | No |
| src/patina/adapters/ | insufficient data (n=7 runs) | insufficient data (n=7 runs) | 13 | No |
| src/patina/autonomy/ | insufficient data (n=1 runs) | insufficient data (n=1 runs) | 1 | No |
| src/patina/beliefs/ | insufficient data (n=6 runs) | insufficient data (n=6 runs) | 7 | No |
| src/patina/mcp/ | insufficient data (n=7 runs) | insufficient data (n=7 runs) | 9 | No |
| src/patina/priority/ | insufficient data (n=1 runs) | insufficient data (n=1 runs) | 1 | No |

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
| 2026-10-17 | 1 | 100% | $0.00 | 333% |
| 2026-10-18 | 1 | 50% | $0.28 | 100% |
| 2026-10-19 | 4 | 0% | $0.78 | 0% |
| 2026-10-20 | 0 | — | — | — |
| 2026-10-21 | 1 | 100% | $0.00 | — |
| 2026-10-22 | 0 | — | — | — |
| 2026-10-23 | 0 | — | — | — |
| 2026-10-24 | 0 | — | — | — |
| 2026-10-25 | 0 | — | — | — |
| 2026-10-26 (baseline break) | 1 | 87% | $1.98 | 43% |

> Baseline break at 2026-10-26: earlier snapshots counted triage runs as implementations (#400), so their first-attempt and cost values are not comparable with later rows.

```mermaid
xychart-beta
    title "Weekly First-Attempt Success Rate (2026)"
    x-axis ["7/20 (n=0)", "7/27 (n=1)", "8/3 (n=24)", "8/10 (n=2)", "8/24 (n=23)", "8/31 (n=8)", "9/7 (n=4)", "9/20 (n=3)", "10/4 (n=27)", "10/11 (n=2)", "10/18 (n=7)", "10/25 (n=2)", "10/26 (n=108)"]
    y-axis "Success %" 0 --> 100
    bar [0, 100, 71, 100, 87, 75, 100, 67, 74, 0, 43, 50, 87]
```

```mermaid
xychart-beta
    title "Weekly Avg Cost/PR (2026)"
    x-axis ["7/20 (n=0)", "7/27 (n=1)", "8/3 (n=24)", "8/10 (n=2)", "8/24 (n=23)", "8/31 (n=8)", "9/7 (n=4)", "9/20 (n=3)", "10/4 (n=27)", "10/11 (n=2)", "10/18 (n=7)", "10/25 (n=2)", "10/26 (n=108)"]
    y-axis "Cost ($)" 0 --> 2
    bar [0.00, 0.59, 0.80, 0.38, 0.83, 0.86, 0.64, 0.36, 0.94, 0.35, 0.38, 0.27, 1.98]
```

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'pie1': '#4CAF50', 'pie2': '#2196F3', 'pie3': '#FF9800', 'pie4': '#E91E63', 'pie5': '#9C27B0', 'pie6': '#00BCD4', 'pieTitleTextColor': '#aaa', 'pieLegendTextColor': '#aaa', 'pieSectionTextColor': '#fff'}}}%%
pie title Attempt Distribution by Module
    "other (82%, 12 impl)" : 12
    "src/patina/ (93%, 77 impl)" : 77
    "src/patina/adapters/ (71%, 13 impl)" : 13
    "src/patina/autonomy/ (100%, 1 impl)" : 1
    "src/patina/beliefs/ (67%, 7 impl)" : 7
    "src/patina/mcp/ (100%, 9 impl)" : 9
    "src/patina/priority/ (100%, 1 impl)" : 1
```
