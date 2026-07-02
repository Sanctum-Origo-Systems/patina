# Phase 2 — Priority + Judgment

**Goal:** Deterministic priority scoring + decision tracking + unified catch-up view.
After this phase: `patina catch-up` and `patina priorities` show ranked items from the ingested data.

**Key concept:**
- `catch-up` = unified user-facing view: "what needs my attention?" (new + slipping + escalated, all in one sorted list)
- `priorities` = same items grouped by quadrant (Q1/Q2/Q3/Q4)
- Nudge = NOT a user command. It's the agent proactively pushing items when urgency crosses a threshold. Implemented in Phase 5 (graduated autonomy) as a push mechanism.

**Depends on:** Phase 1 (store, models, observations, entities)

---

## New Files

```
src/patina/
├── priority/
│ ├── __init__.py
│ ├── scoring.py
│ ├── objectives.py
│ ├── escalation.py
│ ├── catch_up.py
│ └── engine.py
└── decisions.py

tests/
├── test_scoring.py
├── test_objectives.py
├── test_escalation.py
├── test_decisions.py
└── test_catch_up.py
```

Also update: `cli.py` (add new commands)

---

## Step 1 — Priority Scoring (`src/patina/priority/scoring.py`)

Functions:
- `score_urgency(*, staleness_days: float, escalation: str | None, is_commitment: bool, has_deadline: bool) -> tuple[float, list[str]]`
  - Sigmoid curve on staleness (midpoint=3.0, steepness=0.8), weight 0.4
  - Escalation tiers: gentle=0.2, firm=0.5, urgent=0.9, weight 0.3
  - Commitment flag: 0.7, weight 0.2
  - Deadline flag: 0.9, weight 0.3
  - Returns (score 0.0-1.0, list of reason strings)

- `score_importance(*, text: str, sender_tier: str, objectives: list[Objective] | None, act_on_rate: float | None) -> tuple[float, list[str]]`
  - Sender tier lookup: inner_circle=0.9, team=0.6, colleague=0.3, unknown=0.1, weight 0.35
  - Objective keyword overlap (word intersection / keyword count), weight 0.45
  - Act-on rate (historical), weight 0.20
  - Severity keyword boost: regex for sev1/sev2/incident/outage/regression/production issue → 0.95, weight 0.50
  - Returns (score 0.0-1.0, list of reason strings)

- `assign_quadrant(urgency: float, importance: float) -> str`
  - Q1: urgency >= 0.5 AND importance >= 0.5
  - Q2: urgency >= 0.5 AND importance < 0.5
  - Q3: urgency < 0.5 AND importance >= 0.5
  - Q4: both < 0.5

- `score_item(*, item_id, text, staleness_days, escalation, is_commitment, has_deadline, sender_tier, objectives, act_on_rate) -> QuadrantScore`
  - Combines urgency + importance → quadrant + confidence

Dataclass:
- `QuadrantScore` (item_id, urgency, importance, quadrant, confidence, urgency_reasons, importance_reasons)

Tests:
- Low staleness → low urgency
- High staleness → high urgency
- Escalation boosts urgency
- Inner circle → high importance
- Severity keywords → importance >= 0.5
- Quadrant boundaries correct
- Score capped at 1.0

---

## Step 2 — Objectives (`src/patina/priority/objectives.py`)

Functions:
- `add_objective(label: str, keywords: str, *, home: Path | None) -> Objective`
- `list_objectives(*, active_only: bool = True, home: Path | None) -> list[Objective]`
- `remove_objective(obj_id: str, *, home: Path | None) -> bool`
- `update_objective(obj_id: str, *, label: str | None, keywords: str | None, home: Path | None) -> bool`

Dataclass:
- `Objective` (id, label, keywords, active, created_at, updated_at)

Uses the `objectives` table in store.db.

Tests:
- Add and list objectives
- Remove sets active=0
- Update changes label/keywords
- list with active_only=True filters inactive

---

## Step 3 — Decisions (`src/patina/decisions.py`)

Functions:
- `record_decision(conn, observation_id: str, action: str, latency_seconds: float | None = None) -> None`
  - action: "acted", "ignored", "dismissed", "deferred", "delegated"
  - Inserts into decisions table with acted_at=now

- `get_act_on_rate(conn, *, sender_entity_id: str | None = None, source: str | None = None) -> float`
  - COUNT(action='acted') / COUNT(*) for matching observations
  - Returns 0.5 if no data (neutral prior)

Tests:
- Record decision inserts row
- Act-on rate calculation is correct
- Default rate is 0.5 with no data

---

## Step 4 — Escalation Tiers (`src/patina/priority/escalation.py`)

Determines urgency escalation level based on staleness. Used by catch-up to label items.

Functions:
- `escalation_tier(staleness_days: float) -> str | None`
  - < 3 days: None (no escalation label — it's just "new")
  - 3-7 days: "gentle"
  - 7+ days: "urgent"

- `detect_urgency_shifts(conn, *, since_days: int = 1) -> list[dict]`
  - Finds items that crossed from Q3 → Q1 (important, was not urgent, now urgent) since last check
  - Returns: {item_id, text, sender, previous_quadrant, new_quadrant, reason}
  - This data feeds Phase 5's proactive nudge delivery (agent pushes to user)

Tests:
- escalation_tier thresholds correct
- None returned for fresh items
- detect_urgency_shifts finds items that crossed threshold
- Items that haven't shifted are not returned

---

## Step 5 — Catch-Up (`src/patina/priority/catch_up.py`)

The unified "what needs my attention?" view. Groups items into three sections:

1. **NEEDS ACTION NOW** — items where urgency crossed threshold (Q1 + escalation=urgent)
2. **NEW** — items from last 24h that haven't been triaged
3. **WAITING** — open items that aren't urgent yet (Q3, gentle escalation)

Function:
- `catch_up(*, home: Path | None = None, days: int = 3) -> dict`
  - Gets open observations from last N days
  - Scores each with priority engine
  - Groups into three sections based on quadrant + escalation tier
  - Returns: {"needs_action": [...], "new": [...], "waiting": [...]}
  - Each item: {id, text, sender_name, channel_name, timestamp, quadrant, urgency, importance, staleness_days, escalation}

Grouping logic:
- needs_action: quadrant == "Q1" OR escalation == "urgent"
- new: staleness_days < 1.0 AND not in needs_action
- waiting: everything else that's still open

Tests:
- Returns three groups
- Urgent items appear in needs_action
- Fresh items appear in new
- Old-but-not-urgent items appear in waiting
- Respects days parameter
- Empty store returns empty groups

---

## Step 6 — CLI Updates (`src/patina/cli.py`)

New commands:
- `patina catch-up [--days 3]` — unified view with three sections: NEEDS ACTION NOW / NEW / WAITING
- `patina priorities [--days 7]` — same items grouped by quadrant (Q1/Q2/Q3/Q4 headers)
- `patina dismiss <item_id>` — marks item as dismissed, records decision
- `patina objectives add <label> [--keywords "..."]`
- `patina objectives list`
- `patina objectives remove <id>`

Output format for catch-up:
```
── NEEDS ACTION NOW ──────────────────────────────
  ⚠ [id] sender: text preview (Xd overdue)

── NEW ───────────────────────────────────────────
  • [id] sender: text preview (Xh ago)

── WAITING ───────────────────────────────────────
  • [id] sender: text preview (Xd, gentle)
```

Tests:
- catch-up shows three sections
- priorities groups by quadrant
- dismiss records a decision
- objectives CRUD works via CLI

---

## Checklist

- [x] All tests pass
- [x] Lint clean
- [x] `patina catch-up` shows three sections (needs action / new / waiting)
- [x] `patina priorities` shows quadrant grouping
- [x] `patina dismiss <id>` works
- [x] Merge to main
- [x] Update Status table in app.md
