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
```

## Development

```bash
# Clone and install
git clone https://github.com/youruser/patina.git
cd patina
uv sync

# Generate test fixtures
uv run python scripts/generate_fixtures.py

# Run tests
uv run pytest

# Lint and format
uv run ruff check && uv run ruff format
```
