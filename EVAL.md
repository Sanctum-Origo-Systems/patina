# EVAL Report

## Overall

| Metric | Value |
|--------|-------|
| First-attempt success | 80% |
| Avg cost/PR | $0.77 |
| Human edit rate | 6% |

## Per-Module Breakdown

| Module | Success | Avg Cost | PRs | Auto-merge ready? |
|--------|---------|----------|-----|--------------------|
| other | 62% | $1.09 | 8 | No |
| src/patina/ | 76% | $1.42 | 17 | No |
| src/patina/adapters/ | 36% | $0.39 | 14 | No |
| src/patina/autonomy/ | 100% | $0.62 | 1 | No |
| src/patina/mcp/ | 71% | $0.46 | 7 | No |
| src/patina/priority/ | 100% | $1.91 | 1 | No |

## Trend

| Date (UTC) | Implementations | First-attempt | Avg Cost | Human Edits |
|------|----------------|---------------|----------|-------------|
| 2026-07-20 | 1 | 100% | $0.59 | 0% |
| 2026-07-27 | 13 | 85% | $1.26 | 0% |
| 2026-08-03 | 3 | 67% | $0.51 | 0% |
| 2026-08-10 | 2 | 100% | $0.77 | 0% |
| 2026-08-24 | 13 | 92% | $1.68 | 0% |
| 2026-08-31 | 2 | 100% | $0.95 | 0% |
| 2026-09-07 | 1 | 100% | $0.64 | 0% |
| 2026-09-19 | 64 | 80% | $0.77 | 6% |

```mermaid
xychart-beta
    title "First-Attempt Success Rate (UTC)"
    x-axis ["2026-07-20", "2026-07-27", "2026-08-03", "2026-08-10", "2026-08-24", "2026-08-31", "2026-09-07", "2026-09-19"]
    y-axis "Success %" 0 --> 100
    line [100, 85, 67, 100, 92, 100, 100, 80]
```

```mermaid
xychart-beta
    title "Avg Cost/PR (UTC)"
    x-axis ["2026-07-20", "2026-07-27", "2026-08-03", "2026-08-10", "2026-08-24", "2026-08-31", "2026-09-07", "2026-09-19"]
    y-axis "Cost ($)"
    line [0.59, 1.26, 0.51, 0.77, 1.68, 0.95, 0.64, 0.77]
```

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'pie1': '#4CAF50', 'pie2': '#2196F3', 'pie3': '#FF9800', 'pie4': '#E91E63', 'pie5': '#9C27B0', 'pie6': '#00BCD4', 'pieTitleTextColor': '#aaa', 'pieLegendTextColor': '#aaa', 'pieSectionTextColor': '#fff'}}}%%
pie title PR Distribution by Module
    "other (62%, 8 PRs)" : 8
    "src/patina/ (76%, 17 PRs)" : 17
    "src/patina/adapters/ (36%, 14 PRs)" : 14
    "src/patina/autonomy/ (100%, 1 PRs)" : 1
    "src/patina/mcp/ (71%, 7 PRs)" : 7
    "src/patina/priority/ (100%, 1 PRs)" : 1
```
