# Patina

> The first AI assistant that learns you — and the longer you use it, the less you need to tell it.

Your cognitive ceiling isn't set by your intelligence. It's set by your cognitive load. Patina is a persistent extension of your cognition: it holds your context, tracks your beliefs about your world, mirrors your judgment, and improves with every interaction.

- **Day 1:** Export your Slack. In 5 minutes, see everything you've missed, forgotten, or let slip.
- **Day 30:** It knows your priorities, drafts in your voice, and dismisses noise automatically.
- **Day 90:** It predicts what you'd do, catches contradictions across conversations, and operates silently.

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
```

## How It Works

```
┌─────────────────────────────────────────────────┐
│ Tier 3: Frontier LLM (Claude, GPT-4o)          │ Synthesis, drafts, contradictions
├─────────────────────────────────────────────────┤
│ Tier 2: Local LLM (Qwen 3.x, Ollama)           │ Entity extraction, classification
├─────────────────────────────────────────────────┤
│ Tier 1: Deterministic (no LLM)                  │ Scoring, decay, graph queries
└─────────────────────────────────────────────────┘
        ↓ all tiers feed ↓
┌─────────────────────────────────────────────────┐
│ Belief Graph (SQLite)                           │
│ Entities → Relationships → Claims               │
│ Confidence decay · Provenance · Contradictions   │
└─────────────────────────────────────────────────┘
```

The system is fully functional at Tier 1 alone (zero LLM calls). Each tier adds capability but never load-bears. Local-first: all data stays in `~/.patina/store.db`.

## What Makes This Different

1. **Persistent belief model with decay** — not a message archive, a living world model
2. **Judgment learned from your decisions** — not universal rules, YOUR priorities
3. **Graduated autonomy earned by accuracy** — not configured, proven
4. **Local-first, model-agnostic** — runs offline, no vendor lock-in
5. **Deterministic core** — the intelligence is math and graphs, not LLM calls
6. **Day-one value from export** — no warm-up period

## MCP Server

Patina runs as an MCP server for conversational use from Claude Code, Cline, or any MCP host. 21 tools including `session_checkpoint` for graceful context handoff and `recent_messages` for conversational continuity across stateless sessions.

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
adapters:
  chat:
    - provider: slack
      token: "xoxb-..."
llm:
  tier2:
    provider: ollama
    model: "qwen3-coder:30b"
  tier3:
    provider: anthropic
    api_key: "sk-ant-..."
heartbeat:
  enabled: true
  interval_minutes: 30
```

## Development

```bash
git clone https://github.com/Sanctum-Origo-Systems/patina.git
cd patina
uv sync

# Generate test fixtures
uv run python scripts/generate_fixtures.py

# Run tests + evals
uv run pytest
uv run pytest eval/deterministic/

# Lint
uv run ruff check && uv run ruff format
```

## License

Apache 2.0
