# Cognitive App That Compounds — Build Spec

> Build spec for the open-source release. Self-contained: any LLM agent (Claude Opus, GPT Codex, Qwen via Ollama) should be able to read this document and build the system from scratch.

---

## Build Protocol

**Phase file guidance:**

- `docs/phases/phase-N.md` — implementation guides with file paths, function signatures, and behavior specs
- `docs/phases/phase-N-detailed.md` — full code for models that cannot reason (copy-paste level)

**When to use phase files:**
- If you can implement directly from this document's architecture spec → skip phase files
- If you find yourself guessing at file structure, function signatures, or step order → read `phase-N.md`
- If you still struggle after reading `phase-N.md` → read `phase-N-detailed.md` (if available)

**Per-session workflow:**

1. Read this document (`docs/app.md`) at session start
2. Identify the next incomplete phase from the Status table below
3. Read `docs/phases/phase-N.md` if needed for implementation guidance
4. Create feature branch: `git checkout -b phase-N-<slug>`
5. Build src + tests together. Commit each logical unit.
6. `uv run pytest` must pass before any commit
7. `uv run ruff check` + `uv run ruff format` must be clean
8. Stay under 70% context usage. If approaching, commit progress, write handoff notes, and stop.
9. Phase 1 only: manual test `patina ingest --from-export fixtures/demo/` before merge
10. All other phases: `uv run pytest` passing = merge-ready
11. Merge to main: `git checkout main && git merge --no-ff phase-N-<slug>`
12. Delete feature branch: `git branch -d phase-N-<slug>`
13. Update Status table in this file (mark complete, record actual line count)
14. Add lessons learned if anything was surprising
15. Commit the updated `app.md` on main

**README.md:**
- Create in Phase 1 with: project name, one-line thesis, quick start (install + ingest from export)
- Update after each phase: add new CLI commands and capabilities as they ship
- Final polish in Phase 8: compelling narrative, architecture diagram, model support, contributing guide

**Scripts:**
- `scripts/generate_fixtures.py` — generates seed data (Phase 1)
- The CLI itself is the manual test. Verify each phase's features by running them:
  - Phase 1: `uv run patina init && uv run patina ingest --from-export fixtures/demo/slack-export.zip && uv run patina status`
  - Phase 2: `uv run patina catch-up && uv run patina priorities` (catch-up = unified view: new + slipping + escalated)
  - Phase 3: `uv run patina style build && uv run patina style show <name> && uv run patina draft --to <name> --context "..."`
  - Phase 4: `uv run patina beliefs && uv run patina stale && uv run patina relationships`
  - Phase 5: `uv run patina autonomy status`
  - Phase 6: Start MCP server, connect from Claude Code, call tools conversationally
  - Phase 7: `uv run patina connect slack && uv run patina ingest`

**If stopping mid-phase (context limit or end of session):**
- Commit all progress on the feature branch
- Write handoff notes at the bottom of this document
- Next session resumes from the feature branch + handoff notes

**Stack:**
- Python 3.13+, `uv`, `pytest`, `ruff`, `pydantic`
- Package layout: `src/patina/` (src-layout)
- CLI entrypoint: `patina`
- SQLite for all storage (no external DB dependencies)
- **Schema rule:**: ALL tables must be created in `store.py`'s `init_db()` function. Never create table lazily in the module that uses them. This ensures any existing `store.db` gets new tables on `patina init` and prevents "no such table" errors when running against a DB created by an earlier phase.
- Logging: Python `logging` module, configured in CLI entrypoint. Each module uses `log = logging.getLogger(__name__)`. Default level INFO, `--verbose` flag for DEBUG. Log to `~/.patina/logs/patina.log` (rotating, 5MB max, 3 backups).
  - INFO: operation summaries (e.g., "Ingested 47 messages, 3 new entities, 2 skipped").
  - WARNING: recoverable issues (e.g., "Failed to parse message ts=1234, skipping")
  - ERROR: operation failures (e.g., "Slack API returned 401 — token expired")
  - DEBUG: per-item detail (e.g., "Entity U02TS upserted, confidence 0.7→0.85")
  - Every log line includes: timestamp, module name, level. No PII in logs (no message text, only IDs and counts).
- Heartbeat: a configurable periodic scheduler that runs background tasks. Configured in `~/.patina/config.yaml`:
  ```yaml
  heartbeat:
    enabled: true
    interval_minutes: 30 # how often the heartbeat fires
    tasks:
    ingest: true # fetch new messages from live adapters
      decay: true # run belief confidence decay
      escalation_check: true # detect urgency shifts (feeds nudge at Level 3+)
      profile_refresh: false # regenerate PROFILE.md from graph (default: weekly only)
  ```
  - `patina heartbeat once` — run all enabled tasks once and exit (manual/development use)
  - `patina heartbeat start` — run continuously at configured interval (foreground, daemon use)
  - Can also integrate with system scheduler (cron/launchd/systemd) calling `heartbeat once`
  - Each task runs independently — one failing doesn't block others
  - Skips tasks if no live adapters configured (e.g., export-only users don't need ingest heartbeat)
- Replace `patina` with chosen product name throughout the codebase

---

## Thesis

Every AI assistant gives you the same experience on day 90 as day 1. This is the first one that learns you — and the longer you use it, the less you need to tell it.

**The problem:** Your cognitive ceiling isn't set by your intelligence. It's set by your cognitive load. You juggle 50-200+ messages/day across 20-50 relationships with competing priorities. You miss connections, forget commitments, respond to noise, and operate at 60% of your capability because context-switching fragments your working memory.

**The insight:** Existing tools reduce load by doing tasks *for* you (sort inbox, schedule meeting, draft reply). The app reduces load by being a persistent extension *of* your cognition — it holds your context, tracks your beliefs about your world, mirrors your judgment, and improves with every interaction.

**The paradigm shift:**

| What others do | What the app does |
|---|---|
| Stateless — resets every session | Stateful — compounds daily |
| Universal rules (oldest first, boss first) | Learned judgment (trained on YOUR decisions) |
| Always-on or always-ask | Graduated autonomy — earned by accuracy |
| Cloud SaaS, your data on their servers | Local-first. Your model is yours. |
| Locked to one LLM provider | Model-agnostic. Bring your own LLM or run fully offline. |
| Same experience day 1 and day 90 | Day 90 is categorically different — it KNOWS you |

**Day-one hook:** Export your Slack. In 5 minutes, see everything you've missed, forgotten, or let slip — across every conversation you've had this month.

**Day-90 reality:** It predicts what you'd do, drafts in your voice per recipient, auto-dismisses noise, catches contradictions across conversations, and surfaces synthesis no human would find across 200 messages. The silence is the product working.

---

## Architecture

### The Graph — Not a Message Database

The core data structure is a **belief graph**: entities connected by relationships, with claims that have confidence, decay, and provenance.

```
┌─────────────────────────────────────────────┐
│ Entities: people, projects, topics,         │
│           commitments, events               │
├─────────────────────────────────────────────┤
│ Relationships: owns, reports-to, works-on,  │
│                blocked-by, committed-to     │
├─────────────────────────────────────────────┤
│ Claims: "Alex owns ProjectX" (conf=0.92)    │
│         Decay: unconfirmed beliefs weaken   │
│         Provenance: links to source msgs    │
└─────────────────────────────────────────────┘
```

Everything builds on this. Priority scoring queries the graph. Style profiles attach to entities. Judgments train against entity-linked decisions. The graph IS the model of you.

### Storage: SQLite (12 Tables)

Not a graph database. Regular SQLite tables queried like a graph via JOINs. Zero dependencies, single file, fast at our scale (<100K entities), portable (`cp store.db backup/`).

```sql
-- CORE GRAPH (4 tables)
CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,           -- person, project, topic, commitment, event
    name TEXT NOT NULL,
    aliases TEXT,                 -- JSON array of alternate names/IDs
    metadata TEXT,                -- JSON: provider-specific fields
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    decay_rate REAL DEFAULT 0.02
);

CREATE TABLE relationships (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL REFERENCES entities(id),
    predicate TEXT NOT NULL,       -- owns, reports-to, works-on, committed-to, etc.
    object_id TEXT NOT NULL REFERENCES entities(id),
    confidence REAL DEFAULT 0.5,
    first_seen TEXT NOT NULL,
    last_confirmed TEXT NOT NULL,
    source_ids TEXT                -- JSON array of observation IDs that support this
);

CREATE TABLE claims (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL REFERENCES entities(id),
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,          -- free text or entity reference
    confidence REAL DEFAULT 0.5,
    first_asserted TEXT NOT NULL,
    last_confirmed TEXT NOT NULL,
    decay_rate REAL DEFAULT 0.02,
    source_ids TEXT                -- JSON array of observation IDs
);

CREATE TABLE observations (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,          -- slack_export, slack_live, outlook, calendar, manual
    channel_id TEXT,
    thread_id TEXT,
    timestamp REAL NOT NULL,       -- unix float
    sender_entity_id TEXT REFERENCES entities(id),
    text TEXT,
    metadata TEXT,                 -- JSON: permalink, subject, channel_name, etc.
    ingested_at TEXT NOT NULL,
    processed INTEGER DEFAULT 0    -- 0=raw, 1=entities extracted, 2=claims derived
);

-- JUDGMENT + DECISIONS (3 tables)
CREATE TABLE decisions (
    id TEXT PRIMARY KEY,
    observation_id TEXT REFERENCES observations(id),
    action TEXT NOT NULL,          -- acted, ignored, dismissed, deferred, delegated
    acted_at TEXT NOT NULL,
    latency_seconds REAL,          -- time from surfaced to action
    context TEXT                   -- JSON: what quadrant it was in, what was competing
);

CREATE TABLE objectives (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    keywords TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE predictions (
    id TEXT PRIMARY KEY,
    entity_id TEXT REFERENCES entities(id),
    prediction_type TEXT NOT NULL,  -- priority, response_time, will_act, style_match
    prediction TEXT NOT NULL,
    confidence REAL NOT NULL,
    outcome TEXT DEFAULT 'pending', -- confirmed, wrong, pending
    outcome_at TEXT,
    created_at TEXT NOT NULL
);

-- STYLE (2 tables)
CREATE TABLE style_exemplars (
    id TEXT PRIMARY KEY,
    sender_entity_id TEXT REFERENCES entities(id),
    recipient_entity_id TEXT REFERENCES entities(id),
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    timestamp REAL NOT NULL,
    metadata TEXT                   -- JSON: channel, formality score, length, etc.
);

CREATE TABLE style_profiles (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id),
    profile TEXT NOT NULL,          -- JSON: greeting, sign-off, formality, verbosity, patterns
    sample_count INTEGER DEFAULT 0,
    last_updated TEXT NOT NULL
);

-- OPERATIONAL (3 tables)
CREATE TABLE action_queue (
    id TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,       -- reply, dismiss, acknowledge, escalate, decline
    target_observation_id TEXT REFERENCES observations(id),
    target_entity_id TEXT REFERENCES entities(id),
    payload TEXT,                    -- JSON: draft text, reason, etc.
    confidence REAL NOT NULL,
    status TEXT DEFAULT 'proposed',  -- proposed, approved, executed, rejected
    autonomy_level INTEGER NOT NULL, -- which level proposed this
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE journal (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    body TEXT NOT NULL,
    entry_type TEXT DEFAULT 'note',
    processed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE anti_patterns (
    id TEXT PRIMARY KEY,
    from_level INTEGER NOT NULL,
    pattern_type TEXT NOT NULL,
    text_keywords TEXT,
    sender_tier TEXT,
    context TEXT,
    wrong_action TEXT NOT NULL,
    correct_action TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE schema_version (
    version INTEGER NOT NULL PRIMARY KEY
);
```

**FTS5 virtual tables** (created alongside):
```sql
CREATE VIRTUAL TABLE observations_fts USING fts5(text, content=observations, content_rowid=rowid);
CREATE VIRTUAL TABLE journal_fts USING fts5(body, content=journal, content_rowid=rowid);
CREATE VIRTUAL TABLE claims_fts USING fts5(predicate, object, content=claims, content_rowid=rowid);
```

---

### Home Directory (`~/.patina/`)

```
~/.patina/
├── store.db # All 13 tables — the belief graph + everything else
├── config.yaml # Adapter config, LLM settings, objectives
├── SOUL.md # Agent personality — tone, guardrails, behavioral rules
├── PROFILE.md # User identity summary (auto-generated from graph)
├── journal/ # Daily session notes (markdown files)
└── style/
    └── self.md # User's observed communication patterns
```

**SOUL.md** defines how the agent communicates. It is:
- User-authored (written during `patina init` or manually edited)
- Read-only to the agent (the agent cannot modify its own personality)
- Loaded into every LLM prompt that generates user-facing output
- Optional — system works without it (defaults to neutral tone)

Contents: voice/tone preferences, behavioral rules (e.g., "be direct", "no emojis", "push back when I'm stalling"), relationship to user, level of autonomy the user is comfortable with.

**PROFILE.md** is a materialized summary of the user — derived from the belief graph, not manually maintained. It is:
- Auto-generated from the user's entity + claims + relationships in the graph
- Regenerated periodically (or on demand via `patina profile refresh`)
- Loaded into every LLM prompt alongside SOUL.md (so the agent knows who it's talking to without querying the graph each time)
- User can review and edit (edits feed back as high-confidence claims into the graph)
- The graph is the source of truth; PROFILE.md is the cached view

**Sync triggers:**
- End of ingestion: if new claims about user entity were added → regenerate
- Weekly heartbeat: auto-regenerate regardless (catch gradual drift)
- Manual: `patina profile refresh`
- User edit detected: treat edits as claims (confidence=1.0, source=user_direct) → write to graph → regenerate

**Session journaling + checkpointing:**

The agent loses all in-session learning if the host crashes. To prevent this:

- **Auto-journal:** Every MCP tool call that modifies state (dismiss, acknowledge, approve, reject, objective_add) is already persisted to the DB — these survive crashes by design.
- **Learning checkpoint:** When the agent learns something new about the user during conversation (user corrects a belief, states a fact, reveals a preference), the LLM host should call `journal_write` immediately — not at end of session. The journal is the write-ahead log for insights that haven't yet been processed into the belief graph.
- **Session recovery:** On next session start, the agent reads recent journal entries to recover context from prior sessions. If the last session crashed mid-conversation, the journal contains whatever was persisted up to that point.
- **Heartbeat processing:** The heartbeat converts journal entries into graph claims (entity extraction on journal text). So even a quick `journal_write("User graduated from State University")` eventually becomes a claim in the belief graph with confidence=1.0 and source=journal.

**Principle:** Anything worth remembering must be written to disk the moment it's learned — not batched at end of session. Sessions are fragile. The DB is durable.

---

### Tiered Inference Architecture

The system operates at three tiers. Each tier adds capability. The system is fully functional at Tier 1 alone.

```
┌─────────────────────────────────────────────────┐
│ Tier 3: Frontier LLM (Claude Opus, GPT-4o)      │ Synthesis, drafts, contradiction detection
│ On-demand, cloud API, $2-5/day when active      │ Requires 100K+ context reasoning
├─────────────────────────────────────────────────┤
│ Tier 2: Local LLM (Qwen 3.x 27-35B, Ollama)     │ Entity extraction, classification, topic assignment
│ Always-on, RTX 3090/4090, $0                    │ Requires ~30B quality, 64K context
├─────────────────────────────────────────────────┤
│ Tier 1: Deterministic (no LLM)                  │ Regex, math, graph queries, statistics
│ Instant, zero cost, zero latency                │ Python standard library + SQLite
└─────────────────────────────────────────────────┘
```

**Tier 1 — Deterministic (always available):**
- Commitment detection: regex patterns
- Severity keyword escalation: regex
- Priority scoring: sigmoid + weighted signals formula
- Belief confidence decay: `confidence * (1 - decay_rate) ^ days`
- Relationship strength: interaction frequency + recency decay
- Act-on rate: `COUNT(acted) / COUNT(surfaced)` per pattern
- Nudge escalation: threshold tiers (3d/7d/10d)
- Completion detection: thread reply check, emoji reaction check
- Communication rhythm: median response latency per person
- Deduplication: hash(source + channel + thread + ts)

**Tier 2 — Local LLM (improves accuracy):**
- Entity extraction from messages: "Priya had a sev2 about platform v2.0.1" -> entities + claims
- Topic assignment: clustering messages by subject
- Nuanced commitment detection: "I'll try to get back to you" — real commitment or hedging?
- Relevance classification: is this message worth surfacing?
- Style classification: formal vs casual, per message

**Tier 3 — Frontier LLM (premium experience):**
- Cross-message synthesis: "3 people independently mentioned infra costs"
- Contradiction detection: "You told James X but told Derek Y"
- Draft generation: writing in user's voice, tuned per recipient
- Diplomatic declines: nuanced "no" that preserves relationship
- Self-improvement proposals: "Your commitment regex misses X pattern"

**LLMPort Interface:**

```python
    class LLMPort(Protocol):
    """Model-agnostic LLM interface. Implementations: OllamaLLM, ClaudeLLM, OpenAILLM."""

    @property
    def tier(self) -> Literal[2, 3]:
        """Capability tier of this model."""
        ...

    @property
    def context_window(self) -> int:
        """Maximum tokens this model supports."""
        ...

    def complete(self, prompt: str, *, max_tokens: int = 1024) -> str:
        """Single completion."""
        ...

    def extract_entities(self, text: str) -> list[Entity]:
        """Extract entities from text. Tier 2+."""
        ...

    def classify(self, text: str, categories: list[str]) -> str:
        """Classify text into one of the categories. Tier 2+."""
        ...

    def synthesize(self, texts: list[str], question: str) -> str:
        """Cross-document synthesis. Tier 3 only."""
        ...

    def draft(self, context: str, style_profile: str, recipient_profile: str) -> str:
        """Generate a draft in user's voice for recipient. Tier 3 only."""
        ...
```

---

### Observation Ports (Data Sources)

Platform-agnostic interfaces. Users bring their own adapters.

```python
class ChatPort(Protocol):
    """Any chat system: Slack, Teams, Discord, iMessage."""

    @property
    def platform(self) -> str: ...
    def list_dm_messages(self, since: float) -> list[ChatMessage]: ...
    def list_mentions(self, since: float) -> list[ChatMessage]: ...
    def list_channel_messages(self, channel_id: str, since: float) -> list[ChatMessage]: ...
    def get_thread(self, channel_id: str, thread_id: str) -> list[ChatMessage]: ...

class EmailPort(Protocol):
    """Any email system: Outlook, Gmail."""

    @property
    def platform(self) -> str: ...
    def list_inbox(self, since: float) -> list[EmailMessage]: ...
    def search_sent(self, query: str) -> list[EmailMessage]: ...

class CalendarPort(Protocol):
    """Any calendar: Outlook, Google, Apple."""

    @property
    def platform(self) -> str: ...
    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]: ...

class ExportPort(Protocol):
    """Bulk import from export files (Slack export zip, mbox, etc.)."""

    @property
    def platform(self) -> str: ...
    def load(self, path: Path) -> list[ChatMessage]: ...
```

---

### Graduated Autonomy

Trust is earned, not configured.

| Level | Behavior | Earned when |
|-------|----------|-------------|
| 0 | Observe only | Default on install |
| 1 | Classify + surface | After first ingest |
| 2 | Propose actions | After 50 confirmed judgments |
| 3 | Auto-triage (dismiss noise, ack FYIs) | After 100 confirmed, <5% error |
| 4 | Draft + queue (one-tap send) | After style confirmed on 20 drafts |
| 5 | Auto-send routine (acks, scheduling) | After 50 auto-sent with <2% reopens |
| 6 | Full autonomous (escalate only on novel) | After 90 days, <1% error rate |

**Training signals (all implicit):**
- Catch-up item acted on within 1 hour -> high priority for that pattern
- Catch-up item ignored across 3 sessions -> low priority
- Nudge dismissed as false_positive -> judgment correction
- Draft sent as-is -> style confirmed
- Draft edited before sending -> style correction
- Auto-completed item reopened by user -> overcorrection signal

**Override protocol:**
- Any human override blocks level advancement for 7 days
- Override is ALWAYS a training signal (never ignored)
- User can manually promote/demote levels per category

---

### Priority Quadrant Engine

Every incoming observation is scored on two orthogonal axes:

**Urgency** (time-sensitivity): staleness, escalation tier, sender expectation, deadline signals
**Importance** (strategic alignment): objective keyword overlap, sender tier, severity keywords, act-on rate

```
Q1 (Urgent + Important) -> DO NOW
Q2 (Urgent + Not Important) -> DELEGATE/DECLINE
Q3 (Not Urgent + Important) -> SCHEDULE
Q4 (Not Urgent + Not Important) -> DROP (auto-dismiss)
```

**Core insight:** Other people's urgency != your importance. Most of what feels urgent is Q2 — their priorities wearing your attention.

**Scoring is deterministic (Tier 1):**
```python
urgency = sigmoid(staleness_days, midpoint=3.0) * 0.4
        + escalation_score * 0.3
        + commitment_weight * 0.2
        + deadline_weight * 0.3

importance = sender_tier_score * 0.35
            + objective_alignment * 0.45
            + act_on_rate * 0.20
            + severity_boost * 0.50 # if severity keywords present
```

---

### Belief Decay

Beliefs weaken without confirmation. This is a feature, not a bug.

```python
effective_confidence = confidence * (1 - decay_rate) ** days_since_confirmed
```

- Default decay: 2% per day (beliefs become unreliable after ~30 days unconfirmed)
- Behavioral patterns: 0.5% per day (habits are sticky)
- Explicit knowledge (user stated directly): 0% (never decays)
- Contradicted beliefs: immediately deprecated (kept for provenance, not used for decisions)

---

## Build Phases

### Phase 1 — Foundation (~2,000 lines)
**The schema + observation layer. Value: "export Slack, see your world as a graph."**

Deliverables:
- SQLite schema (13 tables + FTS5 + indexes)
- `ExportPort` implementation: Slack export zip -> observations
- Entity extraction pipeline (Tier 1: regex NER for @mentions, channel names, URLs; Tier 2: LLM extraction)
- Claim derivation: observations -> entities + relationships + claims
- Basic queries: "who do I talk to most?", "what topics are active?", "what have I committed to?"
- Seed data generator: `scripts/generate_fixtures.py` — produces `fixtures/demo/slack-export.zip`
  - Deterministic (seeded random) — same output every run
  - Realistic patterns: ~1,000 messages, 20 people, 30 days, 5 channels
  - Encodes workload patterns: 24% DM, 14% group DM, ~1% severity events, commitment density ~0.8%
  - Relationship topology: 1 manager, 3 close peers, 10 team members, 6 external contacts
  - Includes: topic co-occurrence, response latency curves, temporal clustering (weekday peaks, late nights)
  - All names, companies, and message text are fictional
  - Output format matches Slack export JSON structure (channels/*.json)
- CLI: `patina init`, `patina ingest --from-export <path>`

Tests:
- Schema creation + migration
- Export parsing (Slack JSON format)
- Entity extraction (regex golden files)
- Claim derivation (observation -> claim pipeline)
- Deduplication
- Seed data loads without error

### Phase 2 — Priority + Judgment (~1,500 lines)
**Deterministic scoring + decision tracking. Value: "catch me up, sorted by what matters to ME."**

Deliverables:
- Priority scoring engine (urgency x importance, deterministic)
- Objectives table + keyword alignment
- Decision log (track every user action with timestamp)
- Catch-up: surfaces open observations, sorted by quadrant
- Nudge engine: escalation tiers based on staleness
- Severity keyword detection + escalation
- CLI: `patina catch-up` (unified view: needs action now + new + waiting), `patina priorities` (quadrant grouped)
- Nudge is NOT a user command — it's the agent proactively pushing critical items when urgency threshold is crossed (Phase 5+ autonomy feature)

Tests:
- Scoring determinism (same input -> same output)
- Quadrant assignment correctness
- Decision logging + act-on rate calculation
- Nudge escalation tiers
- Severity boost behavior

### Phase 3 — Style + Drafting (~2,000 lines)
**Per-entity communication fingerprints. Value: "draft a reply in my voice, tuned for this person."**

Deliverables:
- Style observation pipeline: sent messages -> pattern extraction
- Style profile per entity: greeting, sign-off, formality, verbosity, emoji usage
- Style consolidation: raw observations -> stable profile
- Draft generation (Tier 3): given context + style + recipient, produce draft
- Recipient profiling: builds behavioral fingerprint from interaction history
- CLI: `patina draft <entity>`, `patina style show <entity>`

Tests:
- Pattern extraction from example messages
- Profile consolidation (multiple observations -> stable profile)
- Draft uses correct style markers (golden file tests with mock LLM)
- Recipient profile accuracy

### Phase 4 — Belief Graph Intelligence (~1,200 lines)
**Decay, contradictions, synthesis. Value: "your world model, alive and self-correcting."**

Deliverables:
- Confidence decay engine (cron job or on-query)
- Stale belief detection + surfacing
- Contradiction detection (Tier 1: same subject+predicate, different object; Tier 3: semantic)
- Cross-observation synthesis (Tier 3): "3 people mentioned X independently"
- Relationship rhythm tracking: interaction frequency, response latency per entity
- Capacity model: commitment count + calendar density -> overcommitment signal
- CLI: `patina beliefs`, `patina stale`, `patina contradictions`

Tests:
- Decay math correctness
- Contradiction detection (graph query tests)
- Synthesis pipeline (mock LLM, verify prompt structure)
- Rhythm calculation accuracy

### Phase 5 — Graduated Autonomy (~800 lines)
**Earned trust system. Value: "the system gets quieter as it proves itself."**

Deliverables:
- Autonomy level tracker (per category)
- Level advancement logic (accuracy thresholds)
- Action queue: propose -> approve/reject -> execute
- Auto-dismiss at Level 3 (proven noise patterns)
- Auto-draft at Level 4 (proven style accuracy)
- Override detection + level freeze
- CLI: `patina autonomy status`, `patina approve <id>`, `patina reject <id>`

Tests:
- Level advancement conditions
- Override freezes advancement
- Action queue lifecycle (propose -> approve -> execute)
- Accuracy tracking

### Phase 6 — MCP Server (~1,500 lines)
**The conversational interface. Value: "talk to your cognitive partner, not a CLI."**

Deliverables:
- patina-core MCP server (stdio transport)
- Tools: catch_up, priorities, draft_reply, journal_write, journal_search
- Tools: beliefs, contradictions, ask (natural language graph query)
- Tools: style_load, profile_read, objectives
- Tools: approve, reject, dismiss (action queue management)
- Guardrails: SOUL.md is read-only (agent cannot modify its own personality), profile changes are proposal-only

Tests:
- Server starts, responds to tools/list
- Each tool produces correct output against seeded database
- Guardrail enforcement

### Phase 7 — Live Adapters (~1,200 lines)
**Real-time ingestion. Value: "always watching, always learning."**

Deliverables:
- Slack live adapter (ChatPort implementation via Slack API/SDK)
- Email adapter (EmailPort implementation via IMAP or provider API)
- Calendar adapter (CalendarPort implementation)
- Ingestion scheduler (periodic or on-demand)
- Completion detection: thread replies, reactions
- CLI: `patina connect slack`, `patina connect email`, `patina ingest`

Tests:
- Adapter protocol conformance
- Mock API responses -> correct observations
- Completion detection logic
- Deduplication across live + export

### Phase 8 — Eval + Polish (~800 lines)
**Proving the system works. Value: "measurable, improving, trustworthy."**

Deliverables:
- Eval framework: deterministic (unit tests), LLM (quality tests), live (accuracy tracking)
- Quadrant accuracy eval: predicted Q vs user action after 24h
- Draft quality eval: edit distance of sent vs generated
- False positive tracking: items user dismisses as irrelevant
- Prediction calibration: confidence vs actual outcome
- README, install docs, architecture guide
- `pyproject.toml` for `uv tool install patina`

Tests:
- Eval suite runs on seed data
- CI pipeline definition
- Install from PyPI works end-to-end

---

## Estimated Scale

| Phase | Lines (source) | Lines (tests) | Total |
|-------|---------------|---------------|-------|
| 1 | 2,000 | 1,200 | 3,200 |
| 2 | 1,500 | 900 | 2,400 |
| 3 | 2,000 | 1,000 | 3,000 |
| 4 | 1,200 | 700 | 1,900 |
| 5 | 800 | 500 | 1,300 |
| 6 | 1,500 | 800 | 2,300 |
| 7 | 1,200 | 600 | 1,800 |
| 8 | 800 | 500 | 1,300 |
| **Total** | **~11,000** | **~6,200** | **~17,200** |

---

## Install Experience

```bash
# Install
uv tool install patina

# Bootstrap
patina init

# Ingest from export (immediate value)
patina ingest --from-export ~/Downloads/slack-export.zip

# Or connect live (ongoing value)
patina connect slack
patina connect email

# Use
patina catch-up
patina priorities
patina draft reply --to james
patina beliefs --about "atlas project"
patina ask "who mentioned infra costs this week?"
```

---

## Model Recommendations

**For building this codebase:**
- Claude Opus 4.6+ (1M context) via Claude Code — optimal
- GPT-5.x via Codex CLI — viable if 200K+ context
- Qwen 3.6 27B+ via Ollama + Claude Code harness — viable for mechanical phases

**For running the app (Tier 2):**
- Qwen 3.6 35B-A3B (MoE, 3B active) — fast, fits 24GB VRAM with room for embeddings
- Qwen3-Coder 30B (Q4) — purpose-built for structured extraction
- DeepSeek-R1 14B (FP16) — strong reasoning, smaller

**For running the app (Tier 3):**
- Claude Opus 4.6+ — best reasoning, 1M context for synthesis
- GPT-4o / GPT-5.x — strong alternative
- Claude Sonnet 4.6 — cost-effective if synthesis quality is acceptable

---

## Security + Privacy

- **No telemetry.** The app never phones home. No usage tracking, no analytics, no crash reports.
- **No cloud calls without explicit user configuration.** LLM API calls only happen if user configures an API key in config.yaml. Tier 1 (deterministic) works fully offline.
- **Tokens/credentials in config.yaml only.** Never committed to git. The repo `.gitignore` must exclude `config.yaml` and `*.db`.
- **No PII in logs.** Logs contain operation summaries, IDs, and counts — never message text, names, or credentials.
- **Local-first by design.** All data stays in `~/.patina/`. No sync, no backup to cloud, no shared state.
- **Export is user-initiated.** The user controls what data enters the system (via export files or configured adapters). The app never scrapes or discovers data sources without explicit configuration.

---

## Agent Configuration Files

The repo should include instruction files for multiple coding agents so any tool can build/contribute:

```
CLAUDE.md # Claude Code
AGENTS.md # OpenAI Codex
.github/copilot-instructions.md # GitHub Copilot
.cursorrules # Cursor
```

All contain the same content (~10 lines):

```markdown
# Patina

Read `docs/app.md` for the full build spec, architecture, and protocol.
Check the Status table at the bottom for the next incomplete phase.
Read `docs/phases/phase-N.md` if you need step-by-step implementation guidance.

Stack: Python 3.13+, uv, pytest, ruff, pydantic, SQLite.
Run `uv run pytest` before committing. Run `uv run ruff check && uv run ruff format`.
```

Create these files in Phase 1 (project scaffold).

---

## Config.yaml Schema

```yaml
# ~/.patina/config.yaml

# Adapters — which data sources are connected
adapters:
  chat:
    - provider: slack
      token: "xoxb-..." # bot or user token
  email:
    - provider: imap
      host: "imap.gmail.com"
      port: 993
      username: "user@gmail.com"
      password: "app-password"
      use_ssl: true

# LLM — which models to use per tier
llm:
  tier2:
    provider: ollama # ollama, anthropic, openai
    model: "qwen3-coder:30b"
    base_url: "http://localhost:11434"
  tier3:
    provider: anthropic
    model: "claude-sonnet-4-6"
    api_key: "sk-ant-..."

# Heartbeat — background scheduler
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

# Display
display:
  timezone: "America/Chicago"
```

This file is user-created (via `patina init` prompts or manual editing). Never committed to git.

---

## Design Principles

1. **Deterministic first.** The system works with zero LLM calls. LLM enriches, never load-bears.
2. **Local first.** Your data never leaves your machine. No cloud sync. No telemetry.
3. **Compound daily.** Day 90 must feel categorically different from day 1.
4. **Earn trust.** Autonomy is graduated by demonstrated accuracy, not configured.
5. **Every override teaches.** No human intervention is wasted.
6. **Silence is success.** The system working well means you hear less from it.
7. **Model agnostic.** Claude today, Qwen tomorrow. The graph survives.
8. **Beliefs over facts.** Store confidence and provenance, not assertions.
9. **Decay is a feature.** Stale information loses influence automatically.
10. **Graph, not tables.** Entities and relationships are first-class. Messages are evidence.

---

## What Makes This Different

No other system does all of these simultaneously:

1. **Persistent belief model with decay** — not a message archive, a living world model
2. **Judgment learned from your decisions** — not universal rules, YOUR priorities
3. **Graduated autonomy earned by accuracy** — not configured, proven
4. **Local-first, model-agnostic** — runs on a consumer GPU, no vendor lock-in
5. **Deterministic core** — the intelligence is math and graphs, not LLM calls
6. **Day-one value from export** — no 2-week warm-up period
7. **Separation of urgency from importance** — the core insight most tools miss

---

## Status

| Phase | Status | Lines (est) | Lines (actual) | Notes |
|-------|--------|-------------|----------------|-------|
| 1 — Foundation | complete | 3,200 | 1,700 | 49 tests, schema+export+ingest+CLI |
| 2 — Priority + Judgment | complete | 2,400 | 1,190 | 36 tests, scoring+catch-up+priorities+objectives |
| 3 — Style + Drafting | complete | 3,000 | 860 | 33 tests, patterns+profiles+draft (MockLLM) |
| 4 — Belief Graph Intelligence | complete | 1,900 | 840 | 23 tests, decay+contradictions+relationships+synthesis |
| 5 — Graduated Autonomy | complete | 1,300 | 930 | 22 tests, levels+actions+tracker+anti-patterns |
| 6 — MCP Server | complete | 2,300 | 680 | 13 tests, 19 tools, FastMCP stdio server |
| 7 — Live Adapters | complete | 1,800 | 640 | 14 tests, ports+slack+imap+heartbeat+connect CLI |
| 8 — Eval + Polish | complete | 1,300 | 450 | 16 eval tests, CI workflow, README polish, wheel builds |

---

## Lessons Learned

(Append here after each phase — what worked, what didn't, what to do differently next time.)

---

## Handoff Notes

(If a session stops mid-phase due to context limits, write what's done, what's next, and any decisions made but not yet implemented. Next session reads this to resume.)
