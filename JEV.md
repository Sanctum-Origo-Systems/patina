# JEV Report

**Verdict:** Jev agreed on 85% (n=20 live) of confident calls

**Band:** 0.15–0.85 (from config); triage.needs_decomposition: 0.35–0.85

## Charts

```mermaid
xychart-beta
    title "Triage: Jev vs Incumbent (n=145 live)"
    x-axis ["Agreed", "Disagreed", "Uncertain (fell back)"]
    y-axis "Decisions" 0 --> 126
    bar [17, 3, 125]
```

```mermaid
xychart-beta
    title "Auto-Merge Confidence by Action Zone (n=139 live)"
    x-axis ["Act: reject (below 0.15)", "Pipeline (0.15-0.85)", "Act: merge (0.85+)"]
    y-axis "Count" 0 --> 136
    bar [0, 135, 4]
```

```mermaid
xychart-beta
    title "Weekly Triage Agreement When Confident"
    x-axis ["9/28 (n=2 live)", "10/5 (n=1 live)", "10/12 (n=3 live)", "10/26 (n=7 live)", "11/2 (n=2 live)", "11/9 (n=1 live)", "11/16 (n=4 live)"]
    y-axis "% agreed" 0 --> 100
    bar [100, 100, 100, 100, 50, 0, 75]
```

## Counts

- **Total entries:** 376
- **Live entries:** 304
- **Backfilled entries:** 72
- **Date range:** 2026-07-03 to 2026-11-18

## Triage Agreement

- **Agreed:** 17 of 145
- **Disagreed:** 3 of 145
- **Uncertain (fell back):** 125 of 145
- **When confident, agreed:** 17 of 20 — 85% (n=20 live)
- **Disagreement breakdown:**
  - needs-decomposition-vs-rejected: 2
  - ready-vs-rejected: 1

### Weekly Trends

| Week | Agreed | Disagreed | Uncertain | n |
|------|--------|-----------|-----------|---|
| 9/28 | 2 | 0 | 9 | 11 |
| 10/5 | 1 | 0 | 7 | 8 |
| 10/12 | 3 | 0 | 24 | 27 |
| 10/19 | 0 | 0 | 3 | 3 |
| 10/26 | 7 | 0 | 31 | 38 |
| 11/2 | 1 | 1 | 30 | 32 |
| 11/9 | 0 | 1 | 5 | 6 |
| 11/16 | 3 | 1 | 16 | 20 |

## Auto-Merge Agreement

- **Mean confidence:** 0.551 (n=139 live)
- **Median confidence:** 0.550 (n=139 live)
- **Agreement with incumbent decision:** 48/68 — 71% (n=68 live)

### Per-Zone Agreement

| Zone | Agreed | Total | Agreement |
|------|--------|-------|-----------|
| Act: reject (below 0.15) | — | 0 | no outcomes yet |
| Pipeline (0.15-0.85) | 48 | 68 | 71% (n=68 live) |
| Act: merge (0.85+) | — | 0 | no outcomes yet |

## Calibration

Live rows only; shadow and backfilled rows are excluded. A suggested band edge needs Jev to match the incumbent on at least 95% of the calls beyond it, with at least n=30 calls.

### triage.well_formed

| Bin | n | % not rejected |
|-----|---|---|
| 0–0.15 | n=1 | 0% |
| 0.15–0.35 | n=0 | — |
| 0.35–0.5 | n=0 | — |
| 0.5–0.65 | n=0 | — |
| 0.65–0.85 | n=22 | 77% |
| 0.85–1 | n=142 | 84% |

- **Band:** 0.15–0.85 (from config)
- **Suggested band edges:** no edge reaches 95% (n=165)
- **Baseline:** always accept: 82%, n=165 vs Jev: 83%, n=165

### triage.needs_decomposition

| Bin | n | % needs-decomposition |
|-----|---|---|
| 0–0.15 | n=7 | 0% |
| 0.15–0.35 | n=38 | 8% |
| 0.35–0.5 | n=23 | 9% |
| 0.5–0.65 | n=32 | 16% |
| 0.65–0.85 | n=53 | 47% |
| 0.85–1 | n=12 | 75% |

- **Band:** 0.35–0.85 (from config)
- **Suggested band edges:** no edge reaches 95% (n=165)
- **Baseline:** never decompose: 73%, n=165 vs Jev: 62%, n=165

### auto-merge.meets_acceptance_criteria

| Bin | n | % approved (incumbent verdict) |
|-----|---|---|
| 0–0.15 | n=0 | — |
| 0.15–0.35 | n=8 | 88% |
| 0.35–0.5 | n=13 | 77% |
| 0.5–0.65 | n=34 | 91% |
| 0.65–0.85 | n=13 | 100% |
| 0.85–1 | n=0 | — |

- **Yardsticks:** **incumbent verdict** (approved), **final outcome** (merged), **7-day human edit** (no human edit). The incumbent's verdict is not ground truth.
- **Band:** 0.15–0.85 (from config)
- **Suggested band edges:** no edge reaches 95% (n=68)
- **Baseline:** always approve: 90%, n=68 vs Jev: 71%, n=68
- **Baseline (final outcome):** no data (no live rows with a merged or closed-unmerged final_outcome)
- **Baseline (7-day human edit):** no data (run history has no 7-day human-edit signal)

## Backfill

```mermaid
xychart-beta
    title "Auto-Merge Confidence by Action Zone (n=57 backfill)"
    x-axis ["Act: reject (below 0.15)", "Pipeline (0.15-0.85)", "Act: merge (0.85+)"]
    y-axis "Count" 0 --> 53
    bar [3, 52, 2]
```

### Backfill Auto-Merge Agreement

- **Mean confidence:** 0.465 (n=57 backfill)
- **Median confidence:** 0.360 (n=57 backfill)
- **Agreement with incumbent decision:** 14/45 — 31% (n=45 backfill)

### Per-Zone Agreement

| Zone | Agreed | Total | Agreement |
|------|--------|-------|-----------|
| Act: reject (below 0.15) | 0 | 3 | 0% (n=3 backfill) |
| Pipeline (0.15-0.85) | 14 | 42 | 33% (n=42 backfill) |
| Act: merge (0.85+) | — | 0 | no outcomes yet |

## Legend

- **Incumbent decision:** the human/pipeline decision that was actually used
- **Fell back:** Jev returned an uncertain result and deferred to the incumbent
- **Pipeline:** confidence too close to call; Jev defers to the incumbent
  - triage.well_formed: 0.15–0.85
  - triage.needs_decomposition: 0.35–0.85
  - auto-merge.meets_acceptance_criteria: 0.15–0.85
- **Backfilled:** a decision reconstructed from historical data, not made live
- **n=… live / n=… backfill:** the sample behind a number; live and backfilled decisions are never pooled

---

*Generated at 2026-11-18 05:10 UTC*