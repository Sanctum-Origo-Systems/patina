# EVAL Report

## Overall

| Metric | Value |
|--------|-------|
| First-attempt success | 78% |
| Avg cost/PR | $0.93 |
| Human edit rate | 9% |

## Auto-Merge Gate (repo-level)

| Metric | Value | Threshold |
|--------|-------|-----------|
| Success rate | 78% | >90% |
| Edit rate | 9% | <5% |
| Clean merges | 52 | ≥10 |
| **Ready?** | **No** | |

## Per-Module Breakdown

| Module | Success | Avg Cost | Impl | Auto-merge ready? |
|--------|---------|----------|------|--------------------|
| other | 62% | $1.09 | 8 | No |
| src/patina/ | 71% | $1.56 | 24 | No |
| src/patina/adapters/ | 36% | $0.38 | 11 | No |
| src/patina/autonomy/ | 75% | $1.68 | 4 | No |
| src/patina/beliefs/ | 0% | $0.00 | 1 | No |
| src/patina/mcp/ | 75% | $0.49 | 8 | No |
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

```mermaid
xychart-beta
    title "First-Attempt Success Rate (UTC)"
    x-axis ["2026-07-20", "2026-07-27", "2026-08-03", "2026-08-10", "2026-08-24", "2026-08-31", "2026-09-07", "2026-09-19", "2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-26", "2026-09-28", "2026-09-29"]
    y-axis "Success %" 0 --> 100
    line [0, 100, 68, 70, 78, 78, 79, 80, 78, 78, 78, 78, 78, 78, 78, 77, 78]
```

```mermaid
xychart-beta
    title "Avg Cost/PR (UTC)"
    x-axis ["2026-07-20", "2026-07-27", "2026-08-03", "2026-08-10", "2026-08-24", "2026-08-31", "2026-09-07", "2026-09-19", "2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-26", "2026-09-28", "2026-09-29"]
    y-axis "Cost ($)"
    line [0.00, 0.59, 0.79, 0.76, 0.79, 0.80, 0.79, 0.77, 0.77, 0.77, 0.77, 0.77, 0.77, 0.77, 0.77, 0.94, 0.93]
```

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'pie1': '#4CAF50', 'pie2': '#2196F3', 'pie3': '#FF9800', 'pie4': '#E91E63', 'pie5': '#9C27B0', 'pie6': '#00BCD4', 'pieTitleTextColor': '#aaa', 'pieLegendTextColor': '#aaa', 'pieSectionTextColor': '#fff'}}}%%
pie title Attempt Distribution by Module
    "other (62%, 8 impl)" : 8
    "src/patina/ (71%, 24 impl)" : 24
    "src/patina/adapters/ (36%, 11 impl)" : 11
    "src/patina/autonomy/ (75%, 4 impl)" : 4
    "src/patina/beliefs/ (0%, 1 impl)" : 1
    "src/patina/mcp/ (75%, 8 impl)" : 8
    "src/patina/priority/ (100%, 1 impl)" : 1
```
