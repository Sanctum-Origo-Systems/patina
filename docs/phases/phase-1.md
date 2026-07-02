# Phase 1 — Foundation

**Goal:** Database schema + Slack export parser + entity extraction + working CLI.
After this phase: `patina ingest --from-export fixtures/demo/slack-export.zip` works end-to-end.

---

## Directory Structure

```
src/patina/
├── __init__.py
├── cli.py
├── store.py
├── models.py
├── export_parser.py
├── extraction.py
├── graph.py
└── ingest.py

tests/
├── __init__.py
├── conftest.py
├── test_store.py
├── test_models.py
├── test_export_parser.py
├── test_extraction.py
├── test_graph.py
├── test_ingest.py
└── test_cli.py

scripts/
└── generate_fixtures.py
```

---

## Step 1 — Store (`src/patina/store.py`)

Functions:
- `get_db_path(home: Path | None = None) -> Path` — returns `~/.patina/store.db`, creates dir if needed
- `connect(db_path: Path) -> sqlite3.Connection` — opens with row_factory=Row, WAL mode, foreign keys ON
- `init_db(db_path: Path) -> None` — executes CREATE TABLE statements for all 12 tables

Tables to create (all with IF NOT EXISTS):
- `entities` (id TEXT PK, type, name, aliases JSON, metadata JSON, first_seen, last_seen, decay_rate REAL)
- `relationships` (id TEXT PK, subject_id FK, predicate, object_id FK, confidence REAL, first_seen, last_confirmed, source_ids JSON)
- `claims` (id TEXT PK, subject_id FK, predicate, object, confidence REAL, first_asserted, last_confirmed, decay_rate REAL, source_ids JSON)
- `observations` (id TEXT PK, source, channel_id, thread_id, timestamp REAL, sender_entity_id FK, text, metadata JSON, ingested_at, processed INT)
- `decisions` (id TEXT PK, observation_id FK, action, acted_at, latency_seconds REAL, context JSON)
- `objectives` (id TEXT PK, label, keywords, active INT, created_at, updated_at)
- `predictions` (id TEXT PK, entity_id FK, prediction_type, prediction, confidence REAL, outcome, outcome_at, created_at)
- `style_exemplars` (id TEXT PK, sender_entity_id FK, recipient_entity_id FK, text, source, timestamp REAL, metadata JSON)
- `style_profiles` (entity_id TEXT PK FK, profile JSON, sample_count INT, last_updated)
- `action_queue` (id TEXT PK, action_type, target_observation_id FK, target_entity_id FK, payload JSON, confidence REAL, status, autonomy_level INT, created_at, resolved_at)
- `journal` (id TEXT PK, date, body, created_at)
- `schema_version` (version INT PK)

FTS5 virtual tables: `observations_fts` (text), `journal_fts` (body), `claims_fts` (predicate, object)

Indexes: on entities(type, name), relationships(subject_id, object_id, predicate), claims(subject_id, predicate), observations(source, timestamp, sender_entity_id, processed), decisions(observation_id, action), action_queue(status)

Tests:
- init_db creates all 12 tables
- init_db is idempotent (call twice, no error)
- get_db_path creates parent directory
- schema_version is set to 1

---

## Step 2 — Models (`src/patina/models.py`)

Dataclasses (not Pydantic — keep lightweight):

- `Entity` (id, type, name, aliases: list[str], metadata: dict, first_seen, last_seen, decay_rate=0.02)
  - `__post_init__` sets first_seen/last_seen to now if empty

- `Relationship` (id, subject_id, predicate, object_id, confidence=0.5, first_seen, last_confirmed, source_ids: list[str])

- `Claim` (id, subject_id, predicate, object, confidence=0.5, first_asserted, last_confirmed, decay_rate=0.02, source_ids: list[str])

- `Observation` (id, source, channel_id, thread_id, timestamp, sender_entity_id, text, metadata: dict, ingested_at, processed=0)

- `ChatMessage` (user_id, text, timestamp, channel_id, thread_id, user_name, channel_name, reactions: list[dict], is_bot=False)

Tests:
- Entity auto-sets timestamps
- Entity preserves explicit timestamps
- Defaults are correct on all models
- ChatMessage defaults (thread_id=None, is_bot=False, reactions=[])

---

## Step 3 — Export Parser (`src/patina/export_parser.py`)

Function:
- `parse_slack_export(zip_path: Path) -> tuple[list[ChatMessage], dict[str, str], dict[str, str]]`
  - Returns (messages sorted by timestamp, users {id: name}, channels {id: name})

Slack export zip structure:
- `users.json` — list of `{"id": "U...", "real_name": "...", "name": "..."}`
- `channels.json` — list of `{"id": "C...", "name": "..."}`
- `<channel_name>/<date>.json` — list of messages `{"user": "U...", "text": "...", "ts": "1234.56", "thread_ts": "...", "reactions": [...]}`

Behavior:
- Skip messages with subtype `bot_message`, `channel_join`, `channel_leave`
- Skip messages with empty user or empty text
- Set thread_id=None if thread_ts equals ts (top-level message, not a reply)
- Resolve channel_id from channels.json by matching folder name to channel name
- Sort output by timestamp ascending

Tests:
- Parses messages correctly (create test zip in fixture)
- Returns user dict and channel dict
- Messages sorted by timestamp
- Thread replies have thread_id set
- Top-level messages have thread_id=None
- Reactions are captured
- Bot messages are skipped
- Empty user/text messages are skipped

---

## Step 4 — Entity Extraction (`src/patina/extraction.py`)

Functions:
- `extract_entities_from_text(text: str) -> list[Entity]`
  - Regex for @mentions: `<@([UW][A-Z0-9]+)>` → person entity
  - Regex for #channels: `<#(C[A-Z0-9]+)\|([^>]+)>` → topic entity
  - Regex for URLs: `https?://[^\s>]+` → reference entity

- `extract_sender_entity(user_id: str, user_name: str | None = None) -> Entity`
  - Creates person entity for message sender

- `_make_id(entity_type: str, key: str) -> str`
  - Deterministic: `sha256(f"{type}:{key}")[:16]`

Tests:
- Single mention → 1 person entity
- Multiple mentions → multiple entities
- Channel reference → topic entity with correct name
- URL → reference entity
- Plain text → empty list
- Sender entity sets name correctly
- IDs are deterministic (same input = same output)
- IDs are unique (different input = different output)

---

## Step 5 — Graph Operations (`src/patina/graph.py`)

Functions:
- `upsert_entity(conn, entity: Entity) -> None` — INSERT OR UPDATE (update last_seen + name on conflict)
- `upsert_relationship(conn, rel: Relationship) -> None` — INSERT OR UPDATE (max confidence, update last_confirmed)
- `insert_claim(conn, claim: Claim) -> None` — INSERT OR IGNORE
- `insert_observation(conn, obs: Observation) -> bool` — INSERT, return True if new, False if duplicate (IntegrityError)
- `get_entity(conn, entity_id: str) -> Entity | None`
- `count_entities(conn, entity_type: str | None = None) -> int`
- `count_observations(conn) -> int`

Tests:
- upsert_entity inserts new entity
- upsert_entity updates last_seen on existing
- insert_observation returns False on duplicate
- count_entities filters by type correctly
- upsert_relationship stores edge
- insert_claim stores claim with confidence

---

## Step 6 — Ingest Pipeline (`src/patina/ingest.py`)

Function:
- `ingest_from_export(zip_path: Path, *, home: Path | None = None) -> dict`
  - Calls parse_slack_export to get messages + users + channels
  - For each message:
    1. Create observation (deterministic ID from channel+thread+ts)
    2. insert_observation — if duplicate, skip
    3. Create sender entity via extract_sender_entity (resolve name from users dict)
    4. upsert_entity for sender
    5. Update observation's sender_entity_id
    6. Extract text entities via extract_entities_from_text
    7. Resolve person entity names from users dict
    8. upsert_entity for each extracted entity
  - Returns: `{"messages_inserted": int, "messages_skipped": int, "entities_created": int, "total_observations": int, "total_entities": int}`

Tests:
- Creates observations from export
- Creates entities (senders + mentioned)
- Is idempotent (second run = all skipped)
- Links sender_entity_id to observations
- Returns correct counts

---

## Step 7 — Templates (`src/patina/templates/`)

Templates copied to user's home directory during `init`. Stored as plain text files in the package.

**`src/patina/templates/SOUL.md`:**
```markdown
# SOUL

## Voice
- (How should the agent speak? Direct? Warm? Formal? Casual?)
- (Example: "Direct and concise. No filler. Matches my pace.")

## Personality
- (What character traits? Proactive? Cautious? Witty? Serious?)
- (Example: "Volunteers what it's thinking. Flags its own mistakes.")

## Autonomy
- (What can the agent do without asking?)
- (Example: "Auto on read-only ops. Confirm on writes.")
- At ~70% context usage, journal a session summary and suggest a fresh session

## Red lines
- Never modify SOUL.md without explicit approval.
- Never send messages without approval.
```

**`src/patina/templates/PROFILE.md`:**
```markdown
# PROFILE

## Identity
- **Name**:
- **Role**:
- **Team**:

## Responsibilities
-

## Current focus
-

## Key people
-
```

**`src/patina/templates/config.yaml`:**
```yaml
# Adapters — configure with: patina connect slack / patina connect email
adapters:
  chat: []
  email: []

# Heartbeat — background tasks
heartbeat:
  enabled: true
  interval_minutes: 30
  tasks:
    ingest: true
    decay: true
    escalation_check: true
    profile_refresh: false

# Belief decay rates
decay_rates:
  user_stated: 0.0
  behavioral_pattern: 0.005
  situational_claim: 0.02
  stale_threshold: 0.3
```

**`src/patina/templates/CLAUDE.md`:**
```markdown
# Patina

Load `~/.patina/SOUL.md` for your personality.
Load `~/.patina/PROFILE.md` for who the user is.
You have access to patina-core MCP tools. Use them proactively:
- Call `catch_up` when user asks what needs attention
- Call `journal_write` immediately when you learn something new about the user
- Call `beliefs` to ground your responses — hedge on stale claims
- Call `draft_reply` when user asks you to write something
At ~70% context usage, call `journal_write` with a session summary and suggest starting a fresh session.
```

---

## Step 8 — CLI (`src/patina/cli.py`)

Commands (using typer):
- `patina init` — creates the full home directory structure:
  - `~/.patina/store.db` (via init_db)
  - `~/.patina/SOUL.md` (copied from templates/SOUL.md)
  - `~/.patina/PROFILE.md` (copied from templates/PROFILE.md)
  - `~/.patina/config.yaml` (copied from templates/config.yaml)
  - `~/.patina/CLAUDE.md` (copied from templates/CLAUDE.md — user can copy to their project root)
  - `~/.patina/journal/` (empty directory)
  - `~/.patina/style/self.md` (empty file)
  - If files already exist, do NOT overwrite them (idempotent)
  - Prints confirmation with path to home directory and next steps
- `patina ingest --from-export <path>` — calls ingest_from_export, prints summary
- `patina status` — shows observation count, entity count (people/topics breakdown)

Tests (using typer.testing.CliRunner):
- init creates database AND all home directory files from templates
- init is idempotent (second run doesn't overwrite existing SOUL.md)
- SOUL.md template contains expected sections (Voice, Personality, Autonomy, Red lines)
- PROFILE.md template contains expected sections (Identity, Responsibilities, Key people)
- config.yaml template contains heartbeat config
- ingest requires --from-export flag
- ingest with valid zip works and prints "Done"
- status on uninitialized DB gives helpful error

---

## Step 8 — Test Config (`tests/conftest.py`)

Shared fixtures:
- `db_path(tmp_path)` — creates temp store.db, returns path
- `db_conn(db_path)` — returns connection, closes after test

---

## Step 9 — Fixture Generator (`scripts/generate_fixtures.py`)

Script that generates `fixtures/demo/slack-export.zip`:
- 20 users (1 manager, 3 close peers, 10 team, 6 external) + 1 self user
- 5 channels (general, 2 project, 1 team, 1 external)
- ~1000 messages over 30 days
- Patterns: 24% from self, ~1% severity events, ~0.8% commitments, ~8% @mentions, ~15% thread replies, ~10% reactions
- Temporal: weekday-heavy, business hours weighted, some late night
- Deterministic: `random.seed(42)` — same output every run
- Output format: valid Slack export zip (users.json, channels.json, channel_name/date.json)

Run: `uv run python scripts/generate_fixtures.py` → produces `fixtures/demo/slack-export.zip`

---

## Step 10 — Final Verification

```bash
uv run python scripts/generate_fixtures.py
uv run pytest
uv run ruff check
uv run ruff format --check
uv run patina init
uv run patina ingest --from-export fixtures/demo/slack-export.zip
uv run patina status
```

Expected: ~1000 messages inserted, ~25-40 entities, all tests pass.

---

## Checklist

- [x] All tests pass
- [x] Lint clean
- [x] Manual ingest works
- [x] Merge to main
- [x] Update Status table in app.md
