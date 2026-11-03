"""Scratch-store identity gate (#577).

Builds a seed store from the fixtures in tests/fixtures/identity_gate/ and
copies a store to a scratch path so identity resolution can be replayed
without touching the source. The source store is only ever opened read-only.

The fixture messages are replayed on the scratch copy through the real ingest
path (adapter message -> extract_sender_entity -> upsert_entity -> store). One
report is printed and the exit code is non-zero, naming the invariant, if an
identity invariant fails.

Usage:
    uv run python scripts/identity_gate.py                  # fixture seed store
    uv run python scripts/identity_gate.py --source PATH    # copy of PATH
    uv run python scripts/identity_gate.py --force-violation
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import TextIO
from unittest import mock

import patina.graph as graph_module
import patina.store as store_module
from patina.extraction import extract_sender_entity
from patina.graph import (
    IDENTIFIER_PRECEDENCE,
    _is_multi_identity,
    _strong_identifiers,
    identifier_type,
)
from patina.ingest import _ingest_messages, _obs_id, _source_family
from patina.maintenance import repair_multi_identity_names
from patina.models import ChatMessage
from patina.owner import normalize_alias
from patina.store import connect, init_db, run_pending_migrations

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "identity_gate"

_SEED_TIMESTAMP = "2025-10-30T00:00:00+00:00"

INVARIANTS: dict[str, str] = {
    "identifier-precedence": "an identifier match lost to a name-only match",
    "sink-preserved": "a multi-identity sink was merged into a single-person entity or deleted",
    "sink-no-member-identity": "a sink gained a member handle, email or DN from a routed message",
    "source-unchanged": "the source store's SHA-256 changed",
}

_OPAQUE_TYPES = frozenset({"slack_id", "dn"})


def load_fixtures(fixtures_dir: Path = FIXTURES_DIR) -> dict:
    """Read the fixture set: ``{"entities": [...], "messages": [...]}``."""
    seed = json.loads((fixtures_dir / "seed.json").read_text())
    messages = json.loads((fixtures_dir / "messages.json").read_text())
    return {"entities": seed["entities"], "messages": messages["messages"]}


def build_seed_store(db_path: Path, fixtures_dir: Path = FIXTURES_DIR) -> Path:
    """Create a store at *db_path* with the real schema and the fixture seed entities."""
    fixtures = load_fixtures(fixtures_dir)
    init_db(db_path)
    conn = connect(db_path)
    try:
        run_pending_migrations(conn)
        for ent in fixtures["entities"]:
            conn.execute(
                "INSERT INTO entities"
                " (id, type, name, aliases, metadata, first_seen, last_seen, is_owner)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ent["id"],
                    ent["type"],
                    ent["name"],
                    json.dumps(ent.get("aliases", [])),
                    json.dumps(ent.get("metadata", {})),
                    _SEED_TIMESTAMP,
                    _SEED_TIMESTAMP,
                    int(ent.get("is_owner", 0)),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scratch_copy(source: Path | None = None, dest_dir: Path | None = None) -> Path:
    """Copy *source* (default ``~/.patina/store.db``) to a scratch path via SQLite's backup API.

    The source is opened read-only. Its SHA-256 is recorded before and after
    the copy; a RuntimeError is raised if it changed.
    """
    source = source if source is not None else store_module.DEFAULT_HOME / "store.db"
    if not source.is_file():
        raise FileNotFoundError(f"Source store not found: {source}")
    if dest_dir is None:
        dest_dir = Path(tempfile.mkdtemp(prefix="patina-identity-gate-"))
    dest = dest_dir / "store.db"

    before = sha256_file(source)
    src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    after = sha256_file(source)

    if after != before:
        raise RuntimeError(f"Source store changed during scratch copy: {source}")
    return dest


def to_chat_message(msg: dict) -> ChatMessage:
    """Rebuild the adapter's ChatMessage from a fixture message."""
    meta = msg.get("metadata", {})
    return ChatMessage(
        user_id=msg["user_id"],
        text=msg["text"],
        timestamp=msg["timestamp"],
        channel_id=msg["channel_id"],
        thread_id=msg.get("thread_id"),
        user_name=msg.get("user_name"),
        channel_name=msg.get("channel_name"),
        reactions=meta.get("reactions", []),
        sender_dn=meta.get("sender_dn"),
        sender_slack_id=meta.get("sender_slack_id"),
    )


def _snapshot(conn: sqlite3.Connection) -> dict[str, dict]:
    return {
        r["id"]: {
            "name": r["name"],
            "aliases": json.loads(r["aliases"] or "[]"),
            "is_owner": bool(r["is_owner"]),
        }
        for r in conn.execute("SELECT id, name, aliases, is_owner FROM entities")
    }


def _tokens(entity: dict) -> list[str]:
    return [entity["name"], *entity["aliases"]]


def _sinks(snapshot: dict[str, dict]) -> set[str]:
    return {
        eid
        for eid, e in snapshot.items()
        if not e["is_owner"] and _is_multi_identity(e["name"], e["aliases"])
    }


def _identity_counts(snapshot: dict[str, dict]) -> dict[str, int]:
    return {
        "entities": len(snapshot),
        "aliases": sum(len(e["aliases"]) for e in snapshot.values()),
        "entities with >1 ID": sum(
            1 for e in snapshot.values() if _is_multi_identity(e["name"], e["aliases"])
        ),
    }


def _held_opaque_ids(entity: dict) -> set[str]:
    """Bare Slack IDs and DNs *entity* holds, upper-cased."""
    return {
        normalize_alias(t).upper()
        for t in _tokens(entity)
        if t and identifier_type(normalize_alias(t)) in _OPAQUE_TYPES
    }


def _sink_guard_disabled():
    """Simulate a #561 regression: a sink keeps every alias a routed message offers."""
    return mock.patch.object(
        graph_module, "_sink_held_id_aliases", lambda _name, _held, incoming: list(incoming)
    )


def _replay_message(conn: sqlite3.Connection, msg: dict, home: Path) -> dict:
    """Ingest one fixture message and classify how its sender was matched."""
    before = _snapshot(conn)
    family = _source_family(msg["source"])
    incoming = extract_sender_entity(msg["user_id"], msg.get("user_name"), source_family=family)
    incoming_ids = _strong_identifiers(
        _tokens({"name": incoming.name, "aliases": incoming.aliases})
    )

    id_holders: dict[str, set[str]] = {}
    for eid, e in before.items():
        if e["is_owner"]:
            continue
        for token in _strong_identifiers(_tokens(e)) & incoming_ids:
            id_holders.setdefault(token, set()).add(eid)

    chat = to_chat_message(msg)
    inserted, *_ = _ingest_messages(conn, [chat], msg["source"], home=home)
    obs_id = _obs_id(msg["source"], chat.channel_id, chat.thread_id, chat.timestamp)
    row = conn.execute(
        "SELECT sender_entity_id FROM observations WHERE id = ?", (obs_id,)
    ).fetchone()
    matched = row["sender_entity_id"] if row else None

    lost: dict[str, list[str]] = {}
    if not inserted or matched is None:
        kind = "skipped (observation already in store)"
    elif matched not in before:
        kind = "new entity"
    else:
        shared = incoming_ids & _strong_identifiers(_tokens(before[matched]))
        if shared:
            strongest = min(
                shared, key=lambda t: (IDENTIFIER_PRECEDENCE.index(identifier_type(t)), t)
            )
            kind = f"identifier ({identifier_type(strongest)})"
        else:
            kind = "name only"
            lost = {token: sorted(ids) for token, ids in sorted(id_holders.items())}

    return {"case": msg.get("case", obs_id), "matched": matched, "kind": kind, "lost": lost}


def _check_invariants(
    matches: list[dict],
    before: dict[str, dict],
    after: dict[str, dict],
    merged_away: set[str],
    source_hashes: tuple[str, str],
) -> list[tuple[str, str]]:
    violations: list[tuple[str, str]] = []

    for m in matches:
        for token, holders in m["lost"].items():
            violations.append(
                (
                    "identifier-precedence",
                    f"{m['case']}: matched {m['matched']} by name only, but "
                    f"{identifier_type(token)} {token} is held by {', '.join(holders)}",
                )
            )

    for sid in sorted(_sinks(before)):
        if sid not in after:
            how = "merged away" if sid in merged_away else "deleted"
            violations.append(("sink-preserved", f"{sid} was {how}"))
            continue
        if not _is_multi_identity(after[sid]["name"], after[sid]["aliases"]):
            violations.append(("sink-preserved", f"{sid} collapsed into a single-person entity"))
        held = _held_opaque_ids(before[sid])
        gained = sorted(
            t
            for t in set(_tokens(after[sid])) - set(_tokens(before[sid]))
            if normalize_alias(t).upper() not in held
        )
        if gained:
            violations.append(("sink-no-member-identity", f"{sid} gained {gained}"))

    if source_hashes[0] != source_hashes[1]:
        violations.append(("source-unchanged", f"sha256 {source_hashes[0]} -> {source_hashes[1]}"))
    return violations


def _print_report(
    out: TextIO,
    *,
    matches: list[dict],
    before: dict[str, dict],
    after: dict[str, dict],
    sink_handles: tuple[dict, dict],
    provenance: list[sqlite3.Row],
) -> None:
    def emit(line: str = "") -> None:
        print(line, file=out)

    emit("== 1. Identifier precedence ==")
    width = max((len(m["case"]) for m in matches), default=0)
    for m in matches:
        emit(f"{m['case']:<{width}}  -> {m['matched']}  [{m['kind']}]")
        for token, holders in m["lost"].items():
            emit(f"{'':<{width}}     {identifier_type(token)} {token} held by {', '.join(holders)}")

    emit()
    emit("== 2. Sink alias diff ==")
    sinks = sorted(_sinks(before) | _sinks(after))
    if not sinks:
        emit("(no multi-identity entities)")
    for sid in sinks:
        old = sorted(before[sid]["aliases"]) if sid in before else None
        new = sorted(after[sid]["aliases"]) if sid in after else None
        emit(sid)
        emit(f"  before: {json.dumps(old) if old is not None else '(absent)'}")
        emit(f"  after:  {json.dumps(new) if new is not None else '(absent)'}")
        emit(f"  added:  {json.dumps(sorted(set(new or []) - set(old or [])))}")
        emit(f"  removed: {json.dumps(sorted(set(old or []) - set(new or [])))}")
    emit(f"sink_handles before: {json.dumps(sink_handles[0], sort_keys=True)}")
    emit(f"sink_handles after:  {json.dumps(sink_handles[1], sort_keys=True)}")

    emit()
    emit("== 3. Provenance ==")
    if not provenance:
        emit("(no entity_alias_provenance rows added)")
    by_entity: dict[str, list[sqlite3.Row]] = {}
    for r in provenance:
        by_entity.setdefault(r["entity_id"], []).append(r)
    for eid, rows in sorted(by_entity.items()):
        emit(f"{eid}: {len(rows)} row(s)")
        for r in rows:
            emit(
                f"  {r['action']} {r['alias']!r}"
                f" (adapter={r['adapter']}, observation={r['observation_id']})"
            )

    emit()
    emit("== 4. Identity counts ==")
    counts_before = _identity_counts(before)
    counts_after = _identity_counts(after)
    label_width = max(len(k) for k in counts_before)
    emit(f"{'':<{label_width}}  {'before':>6}  {'after':>6}")
    for key in counts_before:
        emit(f"{key:<{label_width}}  {counts_before[key]:>6}  {counts_after[key]:>6}")


def _print_verdict(
    out: TextIO, violations: list[tuple[str, str]], source_hashes: tuple[str, str]
) -> int:
    print(file=out)
    print("== Invariants ==", file=out)
    failed = {name for name, _ in violations}
    for name in INVARIANTS:
        if name not in failed:
            print(f"PASS {name}", file=out)
    for name, detail in violations:
        print(f"FAIL {name} ({INVARIANTS[name]}): {detail}", file=out)
    print(f"source sha256 before: {source_hashes[0]}", file=out)
    print(f"source sha256 after:  {source_hashes[1]}", file=out)
    if violations:
        names = ", ".join(n for n in INVARIANTS if n in failed)
        print(f"RESULT: FAIL ({names})", file=out)
        return 1
    print("RESULT: PASS", file=out)
    return 0


def run_gate(
    source: Path | None = None,
    *,
    fixtures_dir: Path = FIXTURES_DIR,
    force_violation: bool = False,
    out: TextIO | None = None,
) -> int:
    """Replay the fixture messages on a scratch copy of *source*, print the report.

    *source* defaults to a seed store built from the fixtures. Returns 0 when
    every invariant holds and 1 otherwise. With *force_violation*, the #561
    sink guard is disabled during replay, so a sink gains a member handle.
    """
    out = out if out is not None else sys.stdout
    fixtures = load_fixtures(fixtures_dir)

    with tempfile.TemporaryDirectory(prefix="patina-identity-gate-") as tmp:
        tmp_dir = Path(tmp)
        if source is None:
            (tmp_dir / "source").mkdir()
            source = build_seed_store(tmp_dir / "source" / "store.db", fixtures_dir)
        source_before = sha256_file(source)

        scratch_dir = tmp_dir / "scratch"
        scratch_dir.mkdir()
        try:
            scratch = scratch_copy(source, scratch_dir)
        except RuntimeError as exc:
            hashes = (source_before, sha256_file(source))
            return _print_verdict(out, [("source-unchanged", str(exc))], hashes)

        conn = connect(scratch)
        try:
            run_pending_migrations(conn)
            before = _snapshot(conn)
            handles_before = repair_multi_identity_names(conn, dry_run=True)["sink_handles"]
            baseline = conn.execute(
                "SELECT COALESCE(MAX(rowid), 0) FROM entity_alias_provenance"
            ).fetchone()[0]

            guard = _sink_guard_disabled() if force_violation else contextlib.nullcontext()
            with guard:
                matches = [_replay_message(conn, msg, scratch_dir) for msg in fixtures["messages"]]

            after = _snapshot(conn)
            handles_after = repair_multi_identity_names(conn, dry_run=True)["sink_handles"]
            provenance = conn.execute(
                "SELECT entity_id, alias, adapter, observation_id, action"
                " FROM entity_alias_provenance WHERE rowid > ? ORDER BY rowid",
                (baseline,),
            ).fetchall()
        finally:
            conn.close()
        source_hashes = (source_before, sha256_file(source))

    merged_away = {r["entity_id"] for r in provenance if r["action"] == "merge"}
    _print_report(
        out,
        matches=matches,
        before=before,
        after=after,
        sink_handles=(handles_before, handles_after),
        provenance=provenance,
    )
    violations = _check_invariants(matches, before, after, merged_away, source_hashes)
    return _print_verdict(out, violations, source_hashes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay identity fixtures on a scratch store copy and check invariants."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="store to copy (default: a seed store built from the fixtures)",
    )
    parser.add_argument(
        "--force-violation",
        action="store_true",
        help="disable the #561 sink guard during replay so sink-no-member-identity fails",
    )
    args = parser.parse_args(argv)
    if args.source is not None and not args.source.is_file():
        parser.error(f"source store not found: {args.source}")
    return run_gate(args.source, force_violation=args.force_violation)


if __name__ == "__main__":
    sys.exit(main())
