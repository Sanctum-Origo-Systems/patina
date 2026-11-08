# Patina

> A cognitive framework that builds beliefs about a subject, tracks confidence over time, detects contradictions, and acts on what it notices — with governed autonomy and human gates.

Patina is an architecture for building systems that form, hold, decay, and act on beliefs about a subject. It maintains an epistemically honest model with quantified confidence, temporal decay, contradiction detection, and graduated autonomy earned through accuracy. The framework is subject-agnostic: demonstrated at personal scale (one person's Slack and email history), designed for team and organizational scale.

![Patina Demo](patina-demo.gif)

## Quick Start

```bash
# Install (from GitHub; the "patina" package on PyPI is an unrelated project)
uv tool install git+https://github.com/Sanctum-Origo-Systems/patina.git

# Initialize
patina init

# Ingest from a Slack export (immediate value)
patina ingest --from-export ~/Downloads/slack-export.zip

# See what needs your attention
patina catch-up

# See everything ranked by priority quadrant
patina priorities
```

## What It Does

```bash
# Priority + judgment
patina catch-up                    # unified view: needs action / new / waiting
patina priorities                  # grouped by quadrant (Q1-Q4)
patina dismiss <id>                # dismiss noise, trains the model
patina objectives add "Ship v2" --keywords "release,deploy"
patina objectives update <id> --participant jordan@example.com --customer-domain example.com
patina objectives list             # active objectives
patina objectives remove <id>      # remove an objective

# Style + drafting
patina style build                 # build communication profiles from sent messages
patina style show <name>           # view patterns for a person
patina draft --to <name> --context "follow up on the timeline"  # generate a draft message

# Belief graph
patina extract                     # extract beliefs from observations via LLM (calendar items are schedule data, not extracted)
patina extract --history 5         # last N runs: skips + alias collisions by source
patina beliefs --type person       # entities with claim counts
patina stale                       # decayed beliefs below confidence threshold
patina contradictions              # conflicting claims
patina relationships --top 20      # trust level + activity map

# Graduated autonomy (per-domain)
patina autonomy status             # per-domain level, accuracy, anti-patterns
patina autonomy pending            # proposed actions awaiting approval
patina autonomy evaluate           # evaluate one ladder step
patina autonomy anti-patterns      # list stored anti-patterns
patina autonomy clear-pattern <id> # remove an anti-pattern
patina autonomy set-level <N>      # manual override (0-6)
patina approve <id>                # approve a proposed action
patina reject <id>                 # reject (freezes advancement, stores anti-pattern)
patina backfill-decisions          # backfill decisions from your past reactions (--dry-run available)

# Entity & data maintenance
# Commands marked (--confirm) preview by default and only write with --confirm.
patina status                      # database status
patina entity list                 # list all entities
patina entity merge <drop> <keep>  # merge entities, rewire references
patina entity dedup                # preview merges by hard identifiers, with match reasons (--confirm)
patina entity prune                # prune non-person entities (protects senders)
patina entity prune-links          # remove Slack link markup entities
patina entity cleanup              # remove claims/relationships pointing at deleted entities (--dry-run available)
patina entity rekey-references     # strip credential params from reference URLs (--confirm)
patina entity resolve-names        # rename entities still named by a raw Slack ID (--confirm)
patina entity retype               # retype person entities that look like organizations (--confirm)
patina entity fix-senders          # merge or retype junk senders: legacy DNs, raw emails (--confirm)
patina entity clean-slack-aliases  # drop slack: aliases that are not valid Slack IDs (--confirm)
patina entity repair-multi-identity  # repair multi-identity sinks holding a member's name or handle (--confirm)
patina entity repair-sink-handles  # strip member handles left on multi-identity sinks (--confirm)
patina cleanup-meeting-obs         # remove uncited Outlook meeting-message observations, read-only preview (--json, --confirm)
patina owner merge                 # fold duplicate self-entities (--dry-run available)
patina doctor                      # includes dangling reference integrity check

# Live adapters
patina connect slack --token "xoxb-..."
patina connect email --host imap.example.com --username you@example.com --password "..."  # IMAP
patina ingest                      # fetch from configured adapters
patina ingest --dry-run            # Outlook keep/drop counts by reason, writes nothing
                                   # (filter goes live with ingest.outlook_relevance_filter: true)

# Heartbeat (background tasks)
patina heartbeat once              # ingest + decay + escalation check
patina heartbeat start --interval 30

# Interactive conversation (Claude Agent SDK)
patina chat

# HTTP server for gateway integration
patina serve --port 8321

# Telegram gateway (talk to your agent from your phone)
patina gateway
```

## How It Works

```
┌─────────────────────────────────────────────────┐
│ Tier 3: Frontier LLM (Claude, GPT-4o)           │ Synthesis, drafts, contradictions
├─────────────────────────────────────────────────┤
│ Tier 2: Local LLM (Qwen 3.x, Ollama)            │ Entity extraction, classification
├─────────────────────────────────────────────────┤
│ Tier 1: Deterministic (no LLM)                  │ Scoring, decay, graph queries
└─────────────────────────────────────────────────┘
        ↓ all tiers feed ↓
┌─────────────────────────────────────────────────┐
│ Belief Graph (SQLite)                           │
│ Entities → Relationships → Claims               │
│ Confidence decay · Provenance · Contradictions  │
└─────────────────────────────────────────────────┘
```

The system is fully functional at Tier 1 alone (zero LLM calls). Each tier adds capability but never load-bears. Local-first: all data stays in `~/.patina/store.db`.

### One Person, Many IDs

Every app names the same person differently: a Slack user ID, an Exchange DN, email addresses, a display name like `Example, Jordan (Contractor)`. Nothing in the data links them, so Patina has to infer that they're one person. A wrong guess blends two people's beliefs. This entity-resolution problem never fully goes away, so Patina aims to be rarely wrong in the harmful direction, not perfect.

**TL;DR: how Patina stays practical**

- **Identifiers beat names.** A Slack ID, DN or email match always wins over a name match.
- **When unsure, keep them apart.** An ambiguous match never merges. A missed link can be fixed later; a false merge corrupts beliefs.
- **Contain the damage.** An entity already holding several people's IDs (a "sink") can't absorb more.
- **Keep junk out.** Bots, lists and irrelevant mail are dropped at ingest, before they become fake people.
- **Keep the evidence.** Raw source facts and claim provenance mean any merge can be traced and undone.
- **A human approves destructive fixes.** Dedup, repairs and cleanups preview first and write only with `--confirm`.

**[Why it's hard, and how each rule works →](docs/features/identity-resolution.md)**

### The Observer-Builder Loop

The core operational pattern is a two-agent loop with human gates at both ends: the **observer** watches the belief graph, notices drift, staleness, or contradictions, and drafts an issue. A human approves (or edits) the issue. The **builder** picks up the approved issue, ships the fix, and opens a PR. A human reviews and merges. Both agents act; neither ships without a gate.

The observer maintains two belief graphs: beliefs about the world it watches, and beliefs about its own operational reliability — enabling self-correction over time.

**[View live builder performance dashboard (EVAL.md)](EVAL.md)** — first-attempt success rate, cost trends, and per-module breakdown. Updated daily.

**[View the decision-model shadow report (JEV.md)](JEV.md)** — how often Jev agrees with triage and auto-merge decisions, and whether it's ready to act. Updated daily.

## What Makes This Different

1. **Cognitive framework, not an assistant** — an architecture for systems that form, hold, and act on beliefs
2. **Persistent belief model with decay** — not a message archive, a living world model
3. **Graduated autonomy earned by accuracy** — per-domain, not configured, proven
4. **Cognitive layer, not standalone agent** — plugs into any MCP host, provides memory and judgment
5. **Local-first, model-agnostic** — runs offline, no vendor lock-in
6. **Deterministic core** — the intelligence is math and graphs, not LLM calls
7. **Day-one value from export** — no warm-up period

## MCP Server — Cognitive Layer, Not Standalone Agent

Patina is not a standalone agent competing with autonomous agent projects. It is a cognitive layer — 33 MCP tools — that plugs into any host agent (Claude Code, Kiro, Cursor, or any MCP host). The host agent provides the interface; Patina provides the memory, epistemics, and judgment. Tools include `store_search` for full-text message search, `hidden_allies` for surfacing quiet supporters, `session_checkpoint` for graceful context handoff, and `recent_messages` for conversational continuity across stateless sessions.

```json
{
  "mcpServers": {
    "patina-core": {
      "command": "uv",
      "args": ["run", "patina-mcp"],
      "cwd": "/path/to/patina"
    }
  }
}
```

## Configuration

All config lives in `~/.patina/config.yaml`. Credentials never leave your machine.

```yaml
owner:
  user_ids: ["U0ABC123"]
  name: "Your Name"
  emails: ["you@example.com"]        # used to tell direct email from everything else
  display_names: ["Doe, Jane"]       # how Outlook shows you in senders and recipients
adapters:
  chat:
    - provider: slack
      token: "xoxb-..."
  email:
    - provider: imap
      host: imap.example.com
      port: 993
      username: you@example.com
      password: "..."
heartbeat:
  enabled: true
  interval_minutes: 30
ingest:
  outlook_relevance_filter: false    # off by default; check `patina ingest --dry-run` first
```

**Outlook email relevance.** With `ingest.outlook_relevance_filter: true`, Patina keeps an Outlook email only if it is direct (you are a named To recipient, not only through a distribution list, or you are in the thread, and a person sent it) or it belongs to an active objective (one of its participants is on the thread, or the sender is from one of its customer domains; set them with `patina objectives update`). Keywords alone never keep an email. Everything else is dropped at ingest: no observation, no extraction, no entity. Each drop is counted by reason. `patina ingest --dry-run` prints those counts and writes nothing, so you can check the rule before turning it on. Meetings come from the calendar only.

## Development

```bash
git clone https://github.com/Sanctum-Origo-Systems/patina.git
cd patina
uv sync

# Generate demo data and start chatting
uv run python scripts/generate_demo_export.py --output demo-export.zip
uv run patina init
uv run patina ingest --from-export demo-export.zip
uv run patina extract --model sonnet  # re-run if it times out — skips already-processed
uv run python scripts/seed_decisions.py  # demo only — simulates user behavior for trust scoring
uv run patina style build              # build communication style profiles from sent messages
uv run patina chat

# Try asking:
#   "What needs my attention?"
#   "Who do I trust most?"
#   "What do we know about Jordan?"
#   "Draft a message to Alexis about the Atlas timeline"
#   "Any contradictions in my beliefs?"

# Run tests + evals
uv run pytest
uv run pytest eval/deterministic/

# Lint
uv run ruff check && uv run ruff format
```

## Read More

- [The $110/month self-improving pipeline](https://andywidjaja.com/blog/110-pipeline) — how the builder works
- [The observer files the bug. The builder ships the fix.](https://andywidjaja.com/blog/observer-builder) — how the observer and builder work together

## Related

- [autoloop](https://github.com/Sanctum-Origo-Systems/autoloop) — the autonomous builder pipeline that implements issues filed by the observer

## License

Apache 2.0
