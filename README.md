# Patina

> A cognitive framework that builds beliefs about a subject, tracks confidence over time, detects contradictions, and acts on what it notices — with governed autonomy and human gates.

Patina is an architecture for building systems that form, hold, decay, and act on beliefs about a subject. It maintains an epistemically honest model with quantified confidence, temporal decay, contradiction detection, and graduated autonomy earned through accuracy. The framework is subject-agnostic: demonstrated at personal scale (one person's Slack history), designed for team and organizational scale.

![Patina Demo](patina-demo.gif)

## Quick Start

```bash
# Install
uv tool install patina

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

# Style + drafting
patina style build                 # build communication profiles from sent messages
patina style show <name>           # view patterns for a person
patina draft --to <name> --context "follow up on the timeline"

# Belief graph
patina extract                     # extract beliefs from observations via LLM
patina beliefs --type person       # entities with claim counts
patina stale                       # decayed beliefs below confidence threshold
patina contradictions              # conflicting claims
patina relationships --top 20      # trust level + activity map

# Graduated autonomy
patina autonomy status             # current level, accuracy, anti-patterns
patina approve <id>                # approve a proposed action
patina reject <id>                 # reject (freezes advancement, stores anti-pattern)
patina autonomy set-level <N>      # manual override (0-6)

# Live adapters
patina connect slack --token "xoxb-..."
patina ingest                      # fetch from configured adapters

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

### The Observer-Builder Loop

The core operational pattern is a two-agent loop with human gates at both ends: the **observer** watches the belief graph, notices drift, staleness, or contradictions, and drafts an issue. A human approves (or edits) the issue. The **builder** picks up the approved issue, ships the fix, and opens a PR. A human reviews and merges. Both agents act; neither ships without a gate.

The observer maintains two belief graphs: beliefs about the world it watches, and beliefs about its own operational reliability — enabling self-correction over time.

## What Makes This Different

1. **Cognitive framework, not an assistant** — an architecture for systems that form, hold, and act on beliefs
2. **Persistent belief model with decay** — not a message archive, a living world model
3. **Graduated autonomy earned by accuracy** — not configured, proven
4. **Cognitive layer, not standalone agent** — plugs into any MCP host, provides memory and judgment
5. **Local-first, model-agnostic** — runs offline, no vendor lock-in
6. **Deterministic core** — the intelligence is math and graphs, not LLM calls
7. **Day-one value from export** — no warm-up period

## MCP Server — Cognitive Layer, Not Standalone Agent

Patina is not a standalone agent competing with autonomous agent projects. It is a cognitive layer — 31 MCP tools — that plugs into any host agent (Claude Code, Kiro, Cursor, or any MCP host). The host agent provides the interface; Patina provides the memory, epistemics, and judgment. Tools include `store_search` for full-text message search, `hidden_allies` for surfacing quiet supporters, `session_checkpoint` for graceful context handoff, and `recent_messages` for conversational continuity across stateless sessions.

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
adapters:
  chat:
    - provider: slack
      token: "xoxb-..."
heartbeat:
  enabled: true
  interval_minutes: 30
```

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
