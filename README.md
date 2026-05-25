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
```

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
