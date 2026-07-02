# Phase 5 — Graduated Autonomy

**Goal:** Autonomy level system, action queue, level advancement earned by accuracy, proactive nudge delivery.
After this phase: `patina autonomy status`, `patina approve <id>`, `patina reject <id>` work. At Level 3+, the agent proactively nudges the user when items cross urgency thresholds.

**Nudge (agent push):** Uses `detect_urgency_shifts()` from Phase 2's escalation module. When the scheduler/heartbeat runs and finds items that moved from Q3 → Q1, the agent pushes a notification to the user (delivery channel depends on config: terminal message on next session, Slack DM at Level 4+, etc.)

**Depends on:** Phase 2 (decisions, priority scoring, escalation), Phase 3 (drafts)

---

## New Files

```
src/patina/
├── autonomy/
│ ├── __init__.py
│ ├── levels.py
│ ├── actions.py
│ └── tracker.py

tests/
├── autonomy/
│ ├── __init__.py
│ ├── test_levels.py
│ ├── test_actions.py
│ └── test_tracker.py
```

Also update: `cli.py`

---

## Step 1 — Level Definitions (`src/patina/autonomy/levels.py`)

Constants and logic for the 7-level autonomy system.

```
LEVELS:
  0 = observe only (default on install)
  1 = classify + surface (after first ingest)
  2 = propose actions (after 50 confirmed judgments)
  3 = auto-triage: dismiss noise, ack FYIs (after 100 confirmed, <5% error)
  4 = draft + queue: one-tap send (after 20 style-confirmed drafts)
  5 = auto-send routine: acks, scheduling (after 50 auto-sent, <2% reopens)
  6 = full autonomous: escalate only on novel (after 90 days, <1% error)
```

Functions:
- `current_level(conn) -> int` — reads from a config row or defaults to 0
- `can_advance(conn, current: int) -> tuple[bool, str]` — checks if advancement criteria met, returns (can_advance, reason)
- `advance_level(conn) -> int` — advances if criteria met, returns new level
- `freeze_advancement(conn, days: int = 7) -> None` — blocks advancement for N days (called on override)
- `is_frozen(conn) -> bool` — checks if freeze is active
- `level_description(level: int) -> str` — human-readable description

Storage: use a row in a new `autonomy_state` table (level INT, frozen_until TEXT, last_advanced TEXT) or store in schema_version table as config.

Tests:
- Default level is 0
- Cannot advance from 0 without ingest data
- Can advance from 0 to 1 after observations exist
- Freeze blocks advancement
- Freeze expires after duration
- Level descriptions are all defined

---

## Step 2 — Action Queue (`src/patina/autonomy/actions.py`)

Functions:
- `propose_action(conn, *, action_type: str, target_observation_id: str | None, target_entity_id: str | None, payload: dict, confidence: float, autonomy_level: int) -> str`
  - Inserts into action_queue with status="proposed"
  - Returns action ID

- `list_pending(conn) -> list[dict]`
  - Returns action_queue items where status="proposed"

- `approve_action(conn, action_id: str) -> bool`
  - Sets status="approved", resolved_at=now
  - Records as a "confirmed" decision for autonomy tracking

- `reject_action(conn, action_id: str) -> bool`
  - Sets status="rejected", resolved_at=now
  - Triggers freeze_advancement (user override = trust signal)

- `execute_action(conn, action_id: str) -> bool`
  - Sets status="executed"
  - Only valid if status is "approved" or if autonomy level >= action's level

- `auto_execute_eligible(conn, current_level: int) -> int`
  - Finds proposed actions where autonomy_level <= current_level AND confidence >= threshold
  - Auto-approves and executes them
  - Returns count executed

Tests:
- Propose creates pending item
- Approve changes status
- Reject changes status and freezes advancement
- List pending returns only proposed items
- Auto-execute respects level threshold

---

## Step 3 — Accuracy Tracker + Demotion (`src/patina/autonomy/tracker.py`)

Functions:
- `get_accuracy_stats(conn, *, since_days: int = 30) -> dict`
  - Counts: total_decisions, correct (approved + acted), incorrect (rejected + user overrides)
  - Returns: {total, correct, incorrect, accuracy_rate, error_rate}

- `get_draft_acceptance_rate(conn) -> float`
  - Drafts sent as-is / total drafts proposed
  - Returns 0.0 if no drafts yet

- `get_override_count(conn, *, since_days: int = 7) -> int`
  - Number of rejections in the window

- `check_demotion(conn, current_level: int) -> tuple[bool, str | None]`
  - Checks if error rate exceeds threshold for current level
  - Level 3: demote if error_rate > 5% (over last 30 days)
  - Level 4: demote if draft rejection rate > 20% (over last 20 drafts)
  - Level 5: demote if reopen rate > 2% (over last 50 auto-sent)
  - Returns: (should_demote, reason)

- `demote_level(conn, *, reason: str, items: list[dict]) -> int`
  - Drops level by 1
  - Stores anti-pattern record with: items that caused demotion, action taken, correct action, text patterns
  - Returns new level

- `get_anti_patterns(conn) -> list[dict]`
  - Returns all stored anti-patterns (never expire)
  - Each: {pattern_type, text_keywords, sender_tier, context, wrong_action, correct_action}

- `matches_anti_pattern(item: dict, anti_patterns: list[dict]) -> bool`
  - Checks if an item matches any stored anti-pattern
  - Used by action queue to prevent repeating past mistakes

- `should_auto_act(conn, item: dict, current_level: int) -> bool`
  - Returns False if item matches any anti-pattern (force propose instead)
  - Returns True only if confidence >= level threshold AND no anti-pattern match

Storage — add table:
```sql
CREATE TABLE IF NOT EXISTS anti_patterns (
    id TEXT PRIMARY KEY,
    from_level INTEGER NOT NULL,
    pattern_type TEXT NOT NULL, -- "dismiss_error", "draft_rejected", "send_reopened"
    text_keywords TEXT, -- keywords that identify this pattern (JSON list)
    sender_tier TEXT,
    context TEXT, -- JSON: what was happening
    wrong_action TEXT NOT NULL,
    correct_action TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

**Principle:** Anti-patterns never expire. If the agent got it wrong once, that specific pattern is permanently excluded from autonomous action — unless the user explicitly clears it.

**Asymmetry:**
- Earning trust (advancement): slow — weeks of sustained accuracy
- Losing trust (demotion): fast — one bad streak triggers it
- User manual override: instant demotion to any level via `patina autonomy set-level N`

Tests:
- Accuracy calculated correctly
- Zero data returns neutral (0.5 accuracy or 0 counts)
- Override count respects time window
- Demotion triggers when error rate exceeds threshold
- Anti-pattern stored on demotion with correct fields
- should_auto_act returns False when anti-pattern matches
- should_auto_act returns True when no pattern match and confidence sufficient
- Manual set-level works

---

## Step 4 — CLI Updates

New commands:
- `patina autonomy status` — shows current level, description, frozen status, accuracy stats, anti-pattern count, next advancement criteria
- `patina autonomy pending` — lists proposed actions awaiting approval
- `patina autonomy set-level <N>` — manually set level (immediate, no earning required)
- `patina autonomy anti-patterns` — list all stored anti-patterns (what the agent learned NOT to do)
- `patina autonomy clear-pattern <id>` — remove an anti-pattern (re-allow that behavior)
- `patina approve <action_id>` — approves an action
- `patina reject <action_id>` — rejects an action (triggers freeze + stores anti-pattern)

Tests:
- Status shows level + anti-pattern count
- Pending lists items
- Approve/reject change status
- Reject stores anti-pattern
- set-level changes level immediately
- anti-patterns lists stored patterns
- clear-pattern removes a pattern

---

## Checklist

- [x] All tests pass
- [x] Lint clean
- [x] `patina autonomy status` shows Level 0 on fresh install
- [x] After ingesting Phase 1 data: level advances to 1
- [x] Reject freezes advancement + stores anti-pattern
- [x] Demotion triggers when error rate exceeds threshold
- [x] Anti-patterns prevent repeating past mistakes
- [x] `patina autonomy set-level` works
- [x] Merge to main
- [x] Update Status table in app.md
