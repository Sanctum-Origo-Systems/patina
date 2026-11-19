"""Store-copy dry run of the Outlook relevance filter (#668).

Copies the store (default ``~/.patina/store.db``) to a temp home, measures
hidden_allies, catch_up and relationships with the filter off, replays the
ingest relevance filter on the copy's stored Outlook emails with the filter
forced on in the copy's config only, and measures again. One report is printed:
the step-1 fixture recall and false drops by reason next to the downstream
before/after table.

The source store is only opened read-only and its config is only read. The
copy is removed at the end unless ``--keep-copy`` is given; its path is in the
report either way.

Replay: an email the filter drops would have created no observation, so on the
copy its observation is deleted, with the decisions and queued actions on it
and the claims and relationships sourced only from dropped emails. Stored
emails keep their source facts but not their thread participants, so only the
sender and recipients are on the thread for the replay.

Usage:
    uv run python scripts/relevance_dry_run.py [--source PATH] [--fixture PATH]
        [--min-recall X] [--keep-copy]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from eval.deterministic.relevance_eval import (
    FIXTURE_PATH,
    evaluate,
    format_report,
    load_fixture,
    resolve_min_recall,
)
from eval.deterministic.store_dry_run import assemble_report, downstream_deltas
from scripts.identity_gate import scratch_copy

import patina.store as store_module
from patina.beliefs.relationships import get_hidden_allies, get_relationship_map
from patina.ingest import (
    _active_objectives,
    _apply_outlook_relevance,
    _outlook_filter_enabled,
    _source_family,
)
from patina.models import EmailMessage, IngestionOutcome
from patina.priority.catch_up import catch_up
from patina.store import connect, delete_observations, get_db_path, init_db

# Count every hidden ally / relationship, not just the default top N.
_UNCAPPED = sys.maxsize


@dataclass
class Replay:
    emails: int = 0
    without_source_facts: int = 0
    dropped_ids: list[str] = field(default_factory=list)
    # Stats key (``relevance_stat_key``) -> count, as ``ingest_live`` reports it.
    decisions: dict[str, int] = field(default_factory=dict)
    sender_unresolved: int = 0
    retain_only: int | None = None


def _retain_only_outcome() -> str | None:
    """The RETAIN_ONLY outcome, or None when this codebase has none."""
    return getattr(IngestionOutcome, "RETAIN_ONLY", None)


class SourceStoreError(Exception):
    """The source store could not be copied (missing, unreadable, not SQLite)."""


def prepare_copy_home(source: Path, copy_home: Path) -> Path:
    """Copy the store into *copy_home* with the filter forced on in its config.

    The source home's config.yaml (owner identifiers etc.) is read, never
    written; only the copy's config has ``ingest.outlook_relevance_filter: true``.
    Raises ``SourceStoreError`` when the source can't be copied.
    """
    try:
        scratch_copy(source, copy_home)
    except (OSError, sqlite3.Error) as exc:
        raise SourceStoreError(f"cannot read source store {source}: {exc}") from exc
    config_path = source.parent / "config.yaml"
    config: dict = {}
    if config_path.is_file():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    config.setdefault("ingest", {})
    if not isinstance(config["ingest"], dict):
        config["ingest"] = {}
    config["ingest"]["outlook_relevance_filter"] = True
    with open(copy_home / "config.yaml", "w") as f:
        yaml.safe_dump(config, f, default_flow_style=False, sort_keys=False)
    # Bring an older copy up to the current schema (outcome column etc.).
    init_db(get_db_path(copy_home))
    return copy_home


def downstream_counts(home: Path) -> dict[str, int]:
    """hidden_allies, catch_up and relationships item counts for the store in *home*."""
    conn = connect(get_db_path(home))
    try:
        allies = len(get_hidden_allies(conn, top_n=_UNCAPPED))
        relationships = len(get_relationship_map(conn, top_n=_UNCAPPED))
    finally:
        conn.close()
    caught_up = catch_up(home=home)
    return {
        "hidden_allies": allies,
        "catch_up": sum(len(items) for items in caught_up.values()),
        "relationships": relationships,
    }


def _stored_email(row: sqlite3.Row) -> EmailMessage:
    meta = json.loads(row["metadata"]) if row["metadata"] else {}
    facts = meta.get("source") or {}
    return EmailMessage(
        id=row["id"],
        sender=str(facts.get("sender_key") or ""),
        subject="",
        text=row["text"] or "",
        timestamp=row["timestamp"],
        conversation_id=row["thread_id"],
        source_facts=facts,
    )


def _sourced_only_from(conn: sqlite3.Connection, table: str, dropped: set[str]) -> list[str]:
    ids = []
    for row in conn.execute(f"SELECT id, source_ids FROM {table} WHERE source_ids IS NOT NULL"):
        sids = json.loads(row["source_ids"] or "[]")
        if sids and all(s in dropped for s in sids):
            ids.append(row["id"])
    return ids


def _remove_dropped(conn: sqlite3.Connection, obs_ids: list[str]) -> None:
    dropped = set(obs_ids)
    for table in ("claims", "relationships"):
        for row_id in _sourced_only_from(conn, table, dropped):
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    for obs_id in obs_ids:
        conn.execute("DELETE FROM decisions WHERE observation_id = ?", (obs_id,))
        conn.execute("DELETE FROM action_queue WHERE target_observation_id = ?", (obs_id,))
    delete_observations(conn, obs_ids)
    conn.commit()


def replay_with_filter(copy_home: Path) -> Replay:
    """Run the ingest relevance filter over the copy's stored Outlook emails.

    Requires the filter to be on in *copy_home*'s config. Dropped emails are
    removed from the copy (see the module docstring).
    """
    if not _outlook_filter_enabled(copy_home):
        raise RuntimeError(f"relevance filter is not on for the store copy in {copy_home}")
    conn = connect(get_db_path(copy_home))
    try:
        rows = [
            r
            for r in conn.execute(
                "SELECT id, source, thread_id, timestamp, text, metadata, outcome"
                " FROM observations WHERE channel_id LIKE 'email:%' ORDER BY timestamp"
            )
            if _source_family(r["source"]) == "outlook"
        ]
        emails = [_stored_email(r) for r in rows]
        replay = Replay(
            emails=len(emails), without_source_facts=sum(1 for e in emails if not e.source_facts)
        )
        kept, replay.sender_unresolved = _apply_outlook_relevance(
            emails,
            objectives=_active_objectives(conn),
            counts=replay.decisions,
            home=copy_home,
            conn=conn,
        )
        kept_ids = {e.id for e in kept}
        dropped = [r for r in rows if r["id"] not in kept_ids]
        replay.dropped_ids = [r["id"] for r in dropped]
        retain_only = _retain_only_outcome()
        if retain_only is not None:
            replay.retain_only = sum(1 for r in dropped if r["outcome"] == retain_only)
        _remove_dropped(conn, replay.dropped_ids)
    finally:
        conn.close()
    return replay


def _replay_lines(source: Path, copy_home: Path, replay: Replay, keep_copy: bool) -> list[str]:
    copy_state = "kept" if keep_copy else "removed after the run"
    lines = [
        f"source: {source} (read-only)",
        f"copy: {get_db_path(copy_home)} ({copy_state})",
        f"relevance filter: {'on' if _outlook_filter_enabled(copy_home) else 'off'} (copy only)",
        f"outlook emails replayed: {replay.emails}",
        f"would-be drops: {len(replay.dropped_ids)}",
    ]
    lines += [f"  {key}: {n}" for key, n in sorted(replay.decisions.items())]
    lines.append(f"sender_unresolved: {replay.sender_unresolved}")
    if replay.without_source_facts:
        lines.append(f"emails without stored source facts: {replay.without_source_facts}")
    return lines


def run_dry_run(
    source: Path,
    *,
    fixture: Path = FIXTURE_PATH,
    min_recall: float | None = None,
    keep_copy: bool = False,
) -> str:
    """Copy, measure, replay, measure again; return the combined report text."""
    relevance = evaluate(load_fixture(fixture))
    copy_home = Path(tempfile.mkdtemp(prefix="patina-relevance-dry-run-"))
    try:
        prepare_copy_home(source, copy_home)
        before = downstream_counts(copy_home)
        replay = replay_with_filter(copy_home)
        after = downstream_counts(copy_home)
        sections = assemble_report(
            relevance,
            downstream_deltas(before, after),
            min_recall=resolve_min_recall(min_recall),
            replay_lines=_replay_lines(source, copy_home, replay, keep_copy),
            retain_only=replay.retain_only,
        )
    finally:
        if not keep_copy:
            shutil.rmtree(copy_home, ignore_errors=True)
    return format_report(sections)


def main(argv: list[str] | None = None) -> int:
    """Print the report; return 1 when the source store can't be read, else 0."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--source", type=Path, default=None, help="store to copy (default ~/.patina/store.db)"
    )
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--min-recall", type=float, default=None)
    parser.add_argument("--keep-copy", action="store_true", help="leave the store copy in place")
    args = parser.parse_args(argv)

    source = args.source if args.source is not None else store_module.DEFAULT_HOME / "store.db"
    if not source.is_file():
        print(f"error: source store not found: {source}", file=sys.stderr)
        return 1
    try:
        report = run_dry_run(
            source, fixture=args.fixture, min_recall=args.min_recall, keep_copy=args.keep_copy
        )
    except SourceStoreError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
