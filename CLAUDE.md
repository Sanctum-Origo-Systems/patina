# Patina

Cognitive assistant that learns you — persistent belief model, graduated autonomy, local-first.

## Quick reference

Stack: Python 3.13+, uv, pytest, ruff, pydantic, SQLite.
Architecture: three-tier LLM (deterministic → local → frontier), all data in ~/.patina/store.db.

## Project structure

src/patina/          # core package (cli, store, ingest, extraction, graph, mcp/, agent/)
tests/               # mirrors src/ structure (adapters/, mcp/, style/, autonomy/, beliefs/)
eval/deterministic/  # deterministic eval tests (run in CI)
scripts/             # app utilities (demo data, belief extraction, decision seeding)
autoloop/            # automated issue triage + implementation pipeline (config-driven)
docs/                # app.md (full spec), phases/, features/, roadmap/

## Before committing

uv run pytest                        # all unit tests
uv run pytest eval/deterministic/    # eval tests (also in CI)
uv run ruff check && uv run ruff format

## Conventions

- Commit messages: `<type>: <description> (#<issue>)` — types: fix, feat, refactor, docs, test
- No real person or company names in test data — use fictitious names only
- No real message content or user data in GitHub issues — use anonymized examples (e.g. "The quick brown fox" not actual ingested messages)
- Follow existing patterns in the repo — read before writing
- Reference files and function names in issues, not line numbers — lines shift as PRs land

## Spec and roadmap

- Read `docs/app.md` for the full build spec and architecture
- Check the Status table at the bottom of app.md for the next incomplete phase
- Read `docs/phases/phase-N.md` for step-by-step implementation guidance