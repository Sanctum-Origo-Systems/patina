# EVAL Report

## Overall

| Metric | Value |
|--------|-------|
| First-attempt success | 73% |
| Avg cost/PR | $0.80 |
| Human edit rate | 35% |

## Auto-Merge Gate (repo-level)

| Metric | Value | Threshold |
|--------|-------|-----------|
| Success rate | 73% | >90% |
| Edit rate | 35% | <5% |
| Clean merges | 70 | ≥10 |
| **Ready?** | **No** | |

## Per-Module Breakdown

| Module | Success | Avg Cost | Impl | Auto-merge ready? |
|--------|---------|----------|------|--------------------|
| other | 42% | $0.73 | 12 | No |
| src/patina/ | 27% | $0.59 | 64 | No |
| src/patina/adapters/ | 36% | $0.39 | 14 | No |
| src/patina/autonomy/ | 50% | $1.94 | 2 | No |
| src/patina/beliefs/ | 0% | $0.00 | 9 | No |
| src/patina/mcp/ | 78% | $0.56 | 9 | No |
| src/patina/priority/ | 100% | $1.91 | 1 | No |

## Trend

| Date (UTC) | Implementations | First-attempt | Avg Cost | Human Edits |
|------|----------------|---------------|----------|-------------|
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
| 2026-10-16 | 0 | — | — | — |

```mermaid
xychart-beta
    title "Weekly First-Attempt Success Rate (2026)"
    x-axis ["7/20 (n=0)", "7/27 (n=1)", "8/3 (n=24)", "8/10 (n=2)", "8/24 (n=23)", "8/31 (n=8)", "9/7 (n=4)", "9/20 (n=3)", "10/4 (n=27)", "10/11 (n=2)", "10/16 (n=4)"]
    y-axis "Success %" 0 --> 100
    bar [0, 100, 71, 100, 87, 75, 100, 67, 74, 0, 25]
```

```mermaid
xychart-beta
    title "Weekly Avg Cost/PR (2026)"
    x-axis ["7/20 (n=0)", "7/27 (n=1)", "8/3 (n=24)", "8/10 (n=2)", "8/24 (n=23)", "8/31 (n=8)", "9/7 (n=4)", "9/20 (n=3)", "10/4 (n=27)", "10/11 (n=2)", "10/16 (n=4)"]
    y-axis "Cost ($)" 0 --> 1
    bar [0.00, 0.59, 0.80, 0.38, 0.83, 0.86, 0.64, 0.36, 0.94, 0.35, 0.57]
```

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'pie1': '#4CAF50', 'pie2': '#2196F3', 'pie3': '#FF9800', 'pie4': '#E91E63', 'pie5': '#9C27B0', 'pie6': '#00BCD4', 'pieTitleTextColor': '#aaa', 'pieLegendTextColor': '#aaa', 'pieSectionTextColor': '#fff'}}}%%
pie title Attempt Distribution by Module
    "other (42%, 12 impl)" : 12
    "src/patina/ (27%, 64 impl)" : 64
    "src/patina/adapters/ (36%, 14 impl)" : 14
    "src/patina/autonomy/ (50%, 2 impl)" : 2
    "src/patina/beliefs/ (0%, 9 impl)" : 9
    "src/patina/mcp/ (78%, 9 impl)" : 9
    "src/patina/priority/ (100%, 1 impl)" : 1
```
