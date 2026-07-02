# Phase 8 — Eval + Polish

**Goal:** Eval framework, README, install experience, CI readiness.
After this phase: the project is ready for public release.

**Depends on:** All previous phases

---

## New Files

```
eval/
├── deterministic/
│ ├── test_commitment_regex.py
│ ├── test_priority_scoring.py
│ ├── test_severity_detection.py
│ └── test_decay_model.py
├── llm_enhanced/
│ ├── eval_entity_extraction.py
│ └── eval_relevance.py
└── live/
    ├── quadrant_accuracy.py
    └── nudge_false_positive.py

docs/
├── app.md (already exists — update)
└── phases/ (already exists)

README.md
LICENSE
.github/
└── workflows/
    └── ci.yml
```

---

## Step 1 — Deterministic Evals (`eval/deterministic/`)

These run as pytest tests — no LLM needed, fast, CI-safe.

`test_commitment_regex.py`:
- 20+ labeled examples: text → expected (is_commitment: bool, snippet or None)
- Measures precision and recall
- Threshold: precision >= 0.85, recall >= 0.75

`test_priority_scoring.py`:
- 10 scenarios with known inputs → verify quadrant assignment is stable
- Verify score is deterministic (same input = same output every time)
- Verify urgency/importance independently

`test_severity_detection.py`:
- 10 positive examples ("sev2", "production incident", etc.) → detected
- 10 negative examples ("the severity was low", "production ready") → not detected
- Threshold: 100% accuracy on these golden examples

`test_decay_model.py`:
- Mathematical correctness: 0 days → no decay, 30 days at 2% → ~0.545, 60 days → ~0.297
- Verify decay never goes negative
- Verify decay formula matches spec

Tests are assertions — pass/fail, not subjective.

---

## Step 2 — LLM-Enhanced Evals (`eval/llm_enhanced/`)

These require a model (local or API). Run on demand, not in CI.

`eval_entity_extraction.py`:
- 50 labeled messages with expected entities (manually annotated from seed data)
- Run Tier 2 extraction (LLM-based) on each
- Compute F1 score (precision + recall)
- Report: "Entity extraction F1: 0.78" (no pass/fail threshold — just measurement)

`eval_relevance.py`:
- 30 labeled messages: "should this surface in catch-up?" (yes/no labels)
- Run classification
- Compute precision@k
- Report: "Relevance precision@10: 0.85"

Script format: run directly (`uv run python eval/llm_enhanced/eval_entity_extraction.py`), prints results to stdout.

---

## Step 3 — Live Evals (`eval/live/`)

These run on the user's actual data over time. Not CI — user runs manually.

`quadrant_accuracy.py`:
- Looks at items surfaced 24h ago
- Checks: did user act on Q1 items? Did user ignore Q4?
- Reports: "Q1 acted rate: 80%, Q4 ignored rate: 95%"

`nudge_false_positive.py`:
- Queries decisions where action="dismissed" with reason="false_positive"
- Reports: "False positive rate: 3/47 (6.4%)"

Script format: `uv run python eval/live/quadrant_accuracy.py` — reads from store.db, prints report.

---

## Step 4 — README.md

Structure:
```markdown
# {App Name}

> One-line thesis

## What it does (3 bullet points)

## Quick start (5 lines of commands)

## How it works (architecture diagram, 10 lines)

## What makes this different (vs other AI assistants)

## Configuration

## Model support (Tier 1/2/3 explanation)

## Contributing

## License
```

Key points for README:
- Lead with the thesis, not the features
- Show the `ingest --from-export` path (day-one value)
- Show the belief graph in action (query examples)
- Explain tiered inference (works offline, better with LLM)
- Keep it under 200 lines — concise, opinionated, no fluff

---

## Step 5 — CI Workflow (`.github/workflows/ci.yml`)

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run ruff check
      - run: uv run ruff format --check
      - run: uv run pytest tests/ -q
      - run: uv run pytest eval/deterministic/ -q
```

Does NOT run LLM evals or live evals in CI.

---

## Step 6 — LICENSE

Apache 2.0 (permissive, allows commercial use, compatible with future hosted tier).

---

## Step 7 — pyproject.toml Polish

Verify:
- All dependencies declared
- `[project.urls]` has GitHub link
- `[project.readme]` points to README.md
- `[project.license]` set to Apache-2.0
- Version is 0.1.0
- Entry points work: `patina` CLI and `patina-mcp` server

---

## Step 8 — Final Full Verification

```bash
# Clean install test
rm -rf .venv
uv sync

# Generate fixtures
uv run python scripts/generate_fixtures.py

# Full test suite
uv run pytest

# Deterministic evals
uv run pytest eval/deterministic/

# Lint
uv run ruff check
uv run ruff format --check

# End-to-end
uv run patina init
uv run patina ingest --from-export fixtures/demo/slack-export.zip
uv run patina status
uv run patina catch-up
uv run patina priorities
uv run patina beliefs
uv run patina relationships
uv run patina autonomy status
```

All must work without error.

---

## Checklist

- [x] All tests pass (tests/ + eval/deterministic/)
- [x] Lint clean
- [x] README exists and is compelling
- [x] LICENSE is Apache 2.0
- [x] CI workflow passes
- [x] End-to-end demo works from clean install
- [x] pyproject.toml is publishable
- [x] `uv build` produces a wheel
- [x] Merge to main
- [x] Update Status table in app.md
- [ ] Tag v0.1.0
