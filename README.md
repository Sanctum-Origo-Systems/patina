# Patina

A cognitive app that compounds — learns you, mirrors your judgment, and improves with every interaction.

## Quick Start

```bash
# Install
uv tool install patina

# Initialize
patina init

# Ingest from a Slack export
patina ingest --from-export ~/Downloads/slack-export.zip

# Check what was ingested
patina status

# See what needs your attention (unified view)
patina catch-up

# See items grouped by priority quadrant
patina priorities

# Dismiss an item
patina dismiss <item-id>

# Manage objectives (keywords boost importance scoring)
patina objectives add "Ship v2" --keywords "release,deploy,ship"
patina objectives list
patina objectives remove <id>

# Build style profiles from your sent messages
patina style build

# Show communication patterns for a person
patina style show <name>

# Generate a draft message in your voice
patina draft --to <name> --context "follow up on the project timeline"

# List entities and their belief counts
patina beliefs --type person

# Show beliefs that have decayed below confidence threshold
patina stale --threshold 0.3

# Find contradictory claims in the belief graph
patina contradictions

# Show relationship map (trust level + activity)
patina relationships --top 20

# Check autonomy level and accuracy stats
patina autonomy status

# List proposed actions awaiting approval
patina autonomy pending

# Approve or reject a proposed action
patina approve <action-id>
patina reject <action-id>

# Manually set autonomy level (0-6)
patina autonomy set-level <N>

# View/clear learned anti-patterns
patina autonomy anti-patterns
patina autonomy clear-pattern <id>

# Connect live data sources
patina connect slack --token "xoxb-..."
patina connect email --host imap.gmail.com --username user@gmail.com --password app-pass

# Ingest from configured live adapters
patina ingest

# Run heartbeat (ingest + decay + escalation check)
patina heartbeat once
patina heartbeat start --interval 30
```

## MCP Server

Patina exposes all features as MCP tools for conversational use from Claude Code, Cline, or any MCP-compatible host.

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

19 tools available: catch_up, priorities, dismiss, acknowledge, done, beliefs, stale, contradictions, relationships, style_show, draft_reply, journal_write, journal_search, profile_read, soul_read, objective_list, objective_add, objective_remove, autonomy_status, approve, reject.

## Development

```bash
# Clone and install
git clone https://github.com/Sanctum-Origo-Systems/patina.git
cd patina
uv sync

# Generate test fixtures
uv run python scripts/generate_fixtures.py

# Run tests
uv run pytest

# Lint and format
uv run ruff check && uv run ruff format
```
