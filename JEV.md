# JEV Report

**Verdict:** Jev agreed on 88% (n=16 live) of confident calls

**Band:** 0.15–0.85 (from config); triage.needs_decomposition: 0.35–0.85

## Charts

```mermaid
xychart-beta
    title "Triage: Jev vs Incumbent (n=125 live)"
    x-axis ["Agreed", "Disagreed", "Uncertain (fell back)"]
    y-axis "Decisions" 0 --> 110
    bar [14, 2, 109]
```

```mermaid
xychart-beta
    title "Auto-Merge Confidence by Action Zone (n=134 live)"
    x-axis ["Act: reject (below 0.15)", "Pipeline (0.15-0.85)", "Act: merge (0.85+)"]
    y-axis "Count" 0 --> 131
    bar [0, 130, 4]
```

```mermaid
xychart-beta
    title "Weekly Triage Agreement When Confident"
    x-axis ["9/28 (n=2 live)", "10/5 (n=1 live)", "10/12 (n=3 live)", "10/26 (n=7 live)", "11/2 (n=2 live)", "11/9 (n=1 live)"]
    y-axis "% agreed" 0 --> 100
    bar [100, 100, 100, 100, 50, 0]
```

## Counts

- **Total entries:** 351
- **Live entries:** 279
- **Backfilled entries:** 72
- **Date range:** 2026-07-03 to 2026-11-11

## Triage Agreement

- **Agreed:** 14 of 125
- **Disagreed:** 2 of 125
- **Uncertain (fell back):** 109 of 125
- **When confident, agreed:** 14 of 16 — 88% (n=16 live)
- **Disagreement breakdown:**
  - needs-decomposition-vs-rejected: 2

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

## Auto-Merge Agreement

- **Mean confidence:** 0.551 (n=134 live)
- **Median confidence:** 0.550 (n=134 live)
- **Agreement with incumbent decision:** 44/63 — 70% (n=63 live)

### Per-Zone Agreement

| Zone | Agreed | Total | Agreement |
|------|--------|-------|-----------|
| Act: reject (below 0.15) | — | 0 | no outcomes yet |
| Pipeline (0.15-0.85) | 44 | 63 | 70% (n=63 live) |
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
| 0.65–0.85 | n=21 | 76% |
| 0.85–1 | n=123 | 85% |

- **Band:** 0.15–0.85 (from config)
- **Suggested band edges:** no edge reaches 95% (n=145)
- **Baseline:** always accept: 83%, n=145 vs Jev: 83%, n=145

### triage.needs_decomposition

| Bin | n | % needs-decomposition |
|-----|---|---|
| 0–0.15 | n=7 | 0% |
| 0.15–0.35 | n=36 | 8% |
| 0.35–0.5 | n=22 | 9% |
| 0.5–0.65 | n=30 | 17% |
| 0.65–0.85 | n=39 | 46% |
| 0.85–1 | n=11 | 73% |

- **Band:** 0.35–0.85 (from config)
- **Suggested band edges:** no edge reaches 95% (n=145)
- **Baseline:** never decompose: 75%, n=145 vs Jev: 63%, n=145

### auto-merge.meets_acceptance_criteria

| Bin | n | % approved (incumbent verdict) |
|-----|---|---|
| 0–0.15 | n=0 | — |
| 0.15–0.35 | n=8 | 88% |
| 0.35–0.5 | n=12 | 75% |
| 0.5–0.65 | n=31 | 90% |
| 0.65–0.85 | n=12 | 100% |
| 0.85–1 | n=0 | — |

- **Yardsticks:** **incumbent verdict** (approved), **final outcome** (merged), **7-day human edit** (no human edit). The incumbent's verdict is not ground truth.
- **Band:** 0.15–0.85 (from config)
- **Suggested band edges:** no edge reaches 95% (n=63)
- **Baseline:** always approve: 89%, n=63 vs Jev: 70%, n=63
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

*Generated at 2026-11-12 05:10 UTC*