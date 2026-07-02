# Phase 4 — Belief Graph Intelligence

**Goal:** Confidence decay, stale belief detection, contradiction detection, relationship rhythm tracking.
After this phase: `patina beliefs`, `patina stale`, `patina contradictions` work.

**Depends on:** Phase 1 (entities, claims, relationships), Phase 2 (objectives)

---

## New Files

```
src/patina/
├── beliefs/
│ ├── __init__.py
│ ├── decay.py
│ ├── contradictions.py
│ ├── relationships.py
│ └── synthesis.py

tests/
├── beliefs/
│ ├── __init__.py
│ ├── test_decay.py
│ ├── test_contradictions.py
│ ├── test_relationships.py
│ └── test_synthesis.py
```

Also update: `cli.py`

---

## Step 1 — Belief Decay (`src/patina/beliefs/decay.py`)

Functions:
- `compute_effective_confidence(confidence: float, decay_rate: float, days_since_confirmed: float) -> float`
  - Formula: `confidence * (1 - decay_rate) ** days_since_confirmed`

- `run_decay_pass(conn) -> int`
  - Queries all claims and relationships
  - Computes effective confidence based on days since last_confirmed
  - Does NOT modify stored confidence (that's the original)
  - Returns count of beliefs now below threshold (0.3)

- `get_stale_beliefs(conn, threshold: float = 0.3) -> list[dict]`
  - Returns claims/relationships whose effective confidence < threshold
  - Each item: {id, subject_name, predicate, object, effective_confidence, days_since_confirmed}

Tests:
- Fresh belief (0 days) → confidence unchanged
- 30 days at 2% decay → confidence ~0.55 (from 1.0)
- 60 days at 2% decay → confidence ~0.30
- Stale beliefs returned when below threshold
- Beliefs above threshold not returned

---

## Step 2 — Contradiction Detection (`src/patina/beliefs/contradictions.py`)

Functions:
- `find_contradictions_tier1(conn) -> list[dict]`
  - Graph query: find claims with same subject + same predicate but different object
  - Example: subject="James", predicate="owns", object="Project A" vs object="Project B"
  - Returns list of {claim_id_1, claim_id_2, subject, predicate, object_1, object_2, confidence_1, confidence_2}

- `find_contradictions_tier3(conn, llm: LLMPort) -> list[dict]`
  - For claims that share a subject but different predicates, ask LLM if they contradict
  - Only call if LLM is tier 3 (has synthesis capability)
  - Returns same format with added "explanation" field

Tests:
- Tier 1: same subject+predicate with different objects → detected
- Tier 1: same subject+predicate with same object → NOT a contradiction
- Tier 1: different subjects → NOT a contradiction
- Returns empty list when no contradictions exist

---

## Step 3 — Relationship Tracking (`src/patina/beliefs/relationships.py`)

**Key principle:** Interaction frequency ≠ relationship strength. They are two separate dimensions:
- **Activity** = how often you communicate (observational, changes with silence)
- **Trust** = how much you value this person (only changes on explicit signals, NOT on silence)

A college friend you haven't messaged in 6 months still has high trust. A vendor you email weekly has low trust. Silence means work doesn't overlap — not that the relationship degraded.

Functions:
- `compute_interaction_stats(conn, entity_id: str) -> dict`
  - Queries observations involving this entity (as sender or mentioned)
  - Returns: {message_count, last_interaction, first_interaction, avg_messages_per_week, days_since_last}

- `compute_trust_level(conn, entity_id: str) -> float`
  - Based on: response latency to this person (fast = high trust), act-on rate for their messages, explicit user designation (inner_circle/team/colleague)
  - Does NOT factor in recency or frequency of interaction
  - Returns 0.0-1.0

- `get_relationship_map(conn, *, top_n: int = 20) -> list[dict]`
  - For each person entity, compute activity stats + trust level
  - Returns sorted by trust_level descending
  - Each: {entity_id, name, trust_level, activity_status, avg_per_week, days_since_last, response_latency_hours}

- `_classify_activity(avg_per_week: float, days_since_last: float) -> str`
  - "active": avg > 1/week and days_since_last < 7
  - "low-frequency": avg < 1/week or days_since_last 7-60
  - "dormant": days_since_last > 60
  - NOTE: this is informational only — does NOT imply relationship quality

Trust level signals (what changes trust):
- User responds fast to this person (latency < user's median) → trust ↑
- User consistently ignores this person's messages → trust ↓
- User explicitly sets tier (inner_circle, team, etc.) → trust = tier score
- Silence alone → trust UNCHANGED

Tests:
- Stats computed correctly from observation data
- Activity classified correctly
- Trust level uses response latency, not recency
- High trust + dormant activity = valid combination (no contradiction)
- Returns top_n limit
- Empty graph returns empty list

---

## Step 4 — Synthesis (Tier 3 stub) (`src/patina/beliefs/synthesis.py`)

Functions:
- `find_convergence(conn, llm: LLMPort | None = None) -> list[dict]`
  - Tier 1 (no LLM): find topics mentioned by 3+ different entities in last 7 days
  - Tier 3 (with LLM): pass those messages to llm.synthesize() for natural language insight
  - Returns: {topic, entities_involved: list[str], message_count, insight: str | None}

Tests:
- Tier 1: detects topic with 3+ participants
- Tier 1: returns empty if no convergence
- With MockLLM: insight field is populated

---

## Step 5 — CLI Updates

New commands:
- `patina beliefs [--type person|topic|all]` — list entities with claim count and confidence
- `patina stale [--threshold 0.3]` — shows beliefs below confidence threshold
- `patina contradictions` — runs tier 1 contradiction detection, displays results
- `patina relationships [--top 20]` — shows relationship rhythms table

Tests:
- Each command produces output on seeded data
- Stale command respects threshold flag
- Relationships shows trend column

---

## Checklist

- [x] All tests pass
- [x] Lint clean
- [x] `patina beliefs` shows entity list
- [x] `patina stale` identifies decayed beliefs
- [x] `patina contradictions` finds conflicting claims (if any in seed data)
- [x] `patina relationships` shows rhythm table
- [x] Merge to main
- [x] Update Status table in app.md
