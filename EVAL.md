# EVAL Report

## Overall

| Metric | Value |
|--------|-------|
| First-attempt success | 76% |
| Avg cost/PR | $0.81 |
| Human edit rate | 28% |

## Auto-Merge Gate (repo-level)

| Metric | Value | Threshold |
|--------|-------|----------|
| Success rate | 76% | >90% |
| Edit rate | 28% | <5% |
| Clean merges | 71 | ≥10 |
| **Ready?** | **No** | |

## Per-Module Breakdown

| Module | Success | Avg Cost | Impl | Auto-merge ready? |
|--------|---------|----------|------|--------------------|
| other | 45% | $0.79 | 11 | No |
| src/patina/ | 33% | $0.70 | 55 | No |
| src/patina/adapters/ | 36% | $0.39 | 14 | No |
| src/patina/autonomy/ | 50% | $1.94 | 2 | No |
| src/patina/beliefs/ | 0% | $0.00 | 9 | No |
| src/patina/mcp/ | 75% | $0.52 | 8 | No |
| src/patina/priority/ | 100% | $1.91 | 1 | No |

## Trend

| Week | Implementations | First-attempt | Avg Cost |
|------|----------------|---------------|----------|
| 2026-07-20 | 1 | 100% | $0.59 |
| 2026-07-27 | 13 | 85% | $1.26 |
| 2026-08-03 | 2 | 50% | $0.55 |
| 2026-08-10 | 2 | 100% | $0.77 |
| 2026-08-24 | 13 | 92% | $1.68 |
| 2026-08-31 | 2 | 100% | $0.95 |
| 2026-09-07 | 1 | 100% | $0.64 |
| 2026-09-21 | 8 | 75% | $2.34 |
| 2026-09-28 | 23 | 83% | $2.11 |
| 2026-10-05 | 20 | 100% | $2.39 |
| 2026-10-12 | 3 | 100% | $1.93 |

```mermaid
xychart-beta
    title "First-Attempt Success Rate per Week (2026)"
    x-axis ["7/20 (n=1)", "7/27 (n=13)", "8/3 (n=2)", "8/10 (n=2)", "8/24 (n=13)", "8/31 (n=2)", "9/7 (n=1)", "9/21 (n=8)", "9/28 (n=23)", "10/5 (n=20)", "10/12 (n=3)"]
    y-axis "Success %" 0 --> 100
    bar [100, 85, 50, 100, 92, 100, 100, 75, 83, 100, 100]
    line [100, 86, 81, 83, 88, 94, 94, 82, 81, 88, 89]
```

```mermaid
xychart-beta
    title "Avg Cost/PR per Week (2026)"
    x-axis ["7/20 (n=1)", "7/27 (n=13)", "8/3 (n=2)", "8/10 (n=2)", "8/24 (n=13)", "8/31 (n=2)", "9/7 (n=1)", "9/21 (n=8)", "9/28 (n=23)", "10/5 (n=20)", "10/12 (n=3)"]
    y-axis "Cost ($)" 0 --> 3
    bar [0.59, 1.26, 0.55, 0.77, 1.68, 0.95, 0.64, 2.34, 2.11, 2.39, 1.93]
```

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'pie1': '#4CAF50', 'pie2': '#2196F3', 'pie3': '#FF9800', 'pie4': '#E91E63', 'pie5': '#9C27B0', 'pie6': '#00BCD4', 'pieTitleTextColor': '#aaa', 'pieLegendTextColor': '#aaa', 'pieSectionTextColor': '#fff'}}}%%
pie title Attempt Distribution by Module
    "other (45%, 11 impl)" : 11
    "src/patina/ (33%, 55 impl)" : 55
    "src/patina/adapters/ (36%, 14 impl)" : 14
    "src/patina/autonomy/ (50%, 2 impl)" : 2
    "src/patina/beliefs/ (0%, 9 impl)" : 9
    "src/patina/mcp/ (75%, 8 impl)" : 8
    "src/patina/priority/ (100%, 1 impl)" : 1
```
