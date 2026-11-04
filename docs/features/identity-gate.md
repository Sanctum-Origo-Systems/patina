# Identity Gate

`scripts/identity_gate.py` checks identity resolution on a scratch copy of a
store. It replays the fixture messages in `tests/fixtures/identity_gate/` (one
per ingest adapter, plus the #561 sink shape and the 10/30 name-only shape)
through the real ingest path: `_ingest_messages` → `extract_sender_entity` →
`upsert_entity`. It then checks these invariants:

| Invariant                 | Fails when                                                        |
|---------------------------|-------------------------------------------------------------------|
| `identifier-precedence`   | an identifier match lost to a name-only match                     |
| `sink-preserved`          | a multi-identity sink was merged into a single-person entity or deleted |
| `sink-no-member-identity` | a sink gained a member handle, email or DN from a routed message  |
| `source-unchanged`        | the source store's SHA-256 changed                                |

See [Identity Precedence](identity-precedence.md) for the resolution rules
that these invariants enforce.

## Release rule

Any ingest release that follows an identity-critical change must attach the
`scripts/identity_gate.py` report before it ships. The report must come from a
run against a scratch copy of the live store. A `RESULT: FAIL` report names
each failing invariant, and the release waits until that failure is cleared.

A change is identity-critical if it touches any of:

- `resolve_entity_id`, `upsert_entity`, `IDENTIFIER_PRECEDENCE` or
  `identifier_type` (`graph.py`)
- `extract_sender_entity` (`extraction.py`), or the sender fields an adapter
  passes to ingest
- entity merge, dedup, sink split or multi-identity repair (`maintenance.py`)

The Observer runs the gate and posts the report on the current relay thread.
This is the standing clearance gate before an identity-critical release.

## Running against the live store

```bash
uv run python scripts/identity_gate.py --source ~/.patina/store.db
```

The script never writes to the store passed to `--source`:

1. It opens the source read-only and copies it to a temp directory
   (`patina-identity-gate-*`) with SQLite's backup API.
2. It records the source's SHA-256 before and after the copy, and again after
   the replay. If the hash changes, `source-unchanged` fails.
3. It runs pending migrations and replays the fixtures on the scratch copy
   only. The scratch copy is deleted when the run ends.

Stop any running ingest before the run. If the store changes during the copy,
the run fails with `source-unchanged`.

The report has four sections: identifier precedence (how each fixture sender
was matched), the sink alias diff (with `sink_handles` before and after),
provenance rows added during the replay, and identity counts. Then comes one
`PASS`/`FAIL` line per invariant, and the source hashes. The exit code is 0
when every invariant holds and 1 otherwise.

Other modes:

```bash
uv run python scripts/identity_gate.py                    # seed store built from the fixtures
uv run python scripts/identity_gate.py --force-violation  # self-check: disables the #561 sink guard
```

`--force-violation` must exit 1 with `FAIL sink-no-member-identity`. This
shows the gate can still fail.

## CI coverage

`tests/scripts/test_identity_gate.py` runs the same gate in CI. It uses a
fixture store built from the real schema, so the private store is not needed.
It asserts, per adapter, that identifier matches outrank name-only matches,
and that the sink is neither merged nor given a member's identity. It also
forces the pre-10/30 `upsert_entity` path with monkeypatches (a name-only
re-resolve that overrides the identifier match, plus an unguarded merge), and
asserts that the gate then fails `identifier-precedence` and `sink-preserved`.
