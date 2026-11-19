from __future__ import annotations

import json
import sqlite3

import pytest

from patina.extraction import CALENDAR_CHANNEL_PREFIX
from patina.graph import insert_observation
from patina.ingest import _obs_id
from patina.models import IngestionOutcome, Observation
from patina.store import connect, record_drop, run_pending_migrations
from tests.conftest import _clear_migration_markers

_NOW = "2025-01-01T00:00:00+00:00"
_OUTCOMES = {"DROP", "RETAIN_ONLY", "RETAIN_AND_EXTRACT"}

# (source, channel_id, thread_id, timestamp, text, metadata). Canonical ids, so
# the observation re-key migration leaves the rows in place.
_LEGACY_ROWS = [
    (
        "outlook_mcp_calendar",
        "calendar:AAMkSYNC1",
        None,
        1781600000.0,
        "[Meeting: Accepted: Weekly sync with Dana Brook] Organizer: Dana Brook",
        {"subject": "Accepted: Weekly sync with Dana Brook", "body": ""},
    ),
    (
        "outlook_mcp_calendar",
        "calendar:AAMkSYNC2",
        None,
        1781686400.0,
        "",
        {"subject": "Accepted: Weekly sync with Dana Brook", "body": ""},
    ),
    (
        "outlook_mcp_email",
        "conv-fox-1",
        None,
        1781610000.0,
        "Re: Quarterly plan — the quick brown fox jumps over the lazy dog",
        {"subject": "Re: Quarterly plan"},
    ),
    (
        "slack_mcp",
        "C0EXAMPLE",
        "1781620000.000100",
        1781620000.0,
        "Jordan Example: sounds good, très bien",
        {},
    ),
]


def _columns(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _legacy_store(db_path, rows=_LEGACY_ROWS):
    """Open a store whose observations predate the outcome column and drop_log."""
    conn = connect(db_path)
    _clear_migration_markers(conn)
    conn.execute("ALTER TABLE observations DROP COLUMN outcome")
    conn.execute("DROP TABLE drop_log")
    for source, channel_id, thread_id, ts, text, metadata in rows:
        conn.execute(
            "INSERT INTO observations"
            " (id, source, channel_id, thread_id, timestamp, text, metadata, ingested_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                _obs_id(source, channel_id, thread_id, ts),
                source,
                channel_id,
                thread_id,
                ts,
                text,
                json.dumps(metadata),
                _NOW,
            ),
        )
    conn.commit()
    return conn


def _is_calendar(row):
    # The #619 predicate (CALENDAR_CHANNEL_PREFIX), not a second definition.
    return row["channel_id"] is not None and row["channel_id"].startswith(CALENDAR_CHANNEL_PREFIX)


def _snapshot(conn):
    return [tuple(r) for r in conn.execute("SELECT * FROM observations ORDER BY rowid")]


def test_observation_defaults_to_retain_and_extract():
    obs = Observation(
        id="obs-1",
        source="test",
        channel_id=None,
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=None,
        text="The quick brown fox",
    )
    assert obs.outcome == IngestionOutcome.RETAIN_AND_EXTRACT


def test_outcome_enum_values():
    assert {o.value for o in IngestionOutcome} == _OUTCOMES


def test_insert_without_outcome_reads_back_retain_and_extract(db_conn):
    db_conn.execute(
        "INSERT INTO observations (id, source, timestamp, text, ingested_at)"
        " VALUES ('obs-raw', 'test', 1.0, 'The quick brown fox', ?)",
        (_NOW,),
    )
    insert_observation(
        db_conn,
        Observation(
            id="obs-model",
            source="test",
            channel_id=None,
            thread_id=None,
            timestamp=2.0,
            sender_entity_id=None,
            text="The quick brown fox",
        ),
    )
    outcomes = dict(db_conn.execute("SELECT id, outcome FROM observations").fetchall())
    assert outcomes == {"obs-raw": "RETAIN_AND_EXTRACT", "obs-model": "RETAIN_AND_EXTRACT"}


def test_invalid_outcome_rejected(db_conn):
    with pytest.raises(sqlite3.IntegrityError):
        db_conn.execute(
            "INSERT INTO observations (id, source, timestamp, text, ingested_at, outcome)"
            " VALUES ('obs-bad', 'test', 1.0, 'The quick brown fox', ?, 'KEEP_MAYBE')",
            (_NOW,),
        )
    obs = Observation(
        id="obs-bad-model",
        source="test",
        channel_id=None,
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=None,
        text="The quick brown fox",
        outcome="retain_only",
    )
    with pytest.raises(sqlite3.IntegrityError):
        insert_observation(db_conn, obs)


def test_drop_log_schema_has_no_content_column(db_conn):
    cols = set(_columns(db_conn, "drop_log"))
    assert {"source", "adapter", "reason_code", "timestamp"} <= cols
    assert not cols & {"content", "body", "text", "message", "subject"}


def test_record_drop_logs_without_observation(db_conn):
    drops_before = db_conn.execute("SELECT COUNT(*) FROM drop_log").fetchone()[0]
    obs_before = db_conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]

    record_drop(
        db_conn,
        source="outlook_mcp_email",
        adapter="outlook_mcp",
        reason_code="auto_reply",
    )

    assert db_conn.execute("SELECT COUNT(*) FROM drop_log").fetchone()[0] == drops_before + 1
    assert db_conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == obs_before
    row = db_conn.execute("SELECT * FROM drop_log ORDER BY id DESC LIMIT 1").fetchone()
    assert (row["source"], row["adapter"], row["reason_code"]) == (
        "outlook_mcp_email",
        "outlook_mcp",
        "auto_reply",
    )
    assert row["timestamp"]


def test_migration_backfills_calendar_rows_retain_only(db_path):
    conn = _legacy_store(db_path)
    assert "outcome" not in _columns(conn, "observations")

    run_pending_migrations(conn)

    rows = conn.execute("SELECT channel_id, outcome FROM observations").fetchall()
    assert len(rows) == len(_LEGACY_ROWS)
    calendar = [r for r in rows if _is_calendar(r)]
    other = [r for r in rows if not _is_calendar(r)]
    assert len(calendar) == 2
    assert len(other) == 2
    assert all(r["outcome"] == "RETAIN_ONLY" for r in calendar)
    assert all(r["outcome"] == "RETAIN_AND_EXTRACT" for r in other)
    conn.close()


def test_migration_preserves_existing_columns_and_rows(db_path):
    conn = _legacy_store(db_path)
    cols_before = _columns(conn, "observations")
    before = _snapshot(conn)

    run_pending_migrations(conn)

    assert _columns(conn, "observations") == [*cols_before, "outcome"]
    after = [
        tuple(r)
        for r in conn.execute(
            f"SELECT {', '.join(cols_before)} FROM observations ORDER BY rowid"
        ).fetchall()
    ]
    assert after == before
    conn.close()


def test_second_run_changes_nothing_and_does_not_rebackfill(db_path):
    conn = _legacy_store(db_path)
    run_pending_migrations(conn)
    calendar_id = _obs_id("outlook_mcp_calendar", "calendar:AAMkSYNC1", None, 1781600000.0)
    conn.execute(
        "UPDATE observations SET outcome = 'RETAIN_AND_EXTRACT' WHERE id = ?", (calendar_id,)
    )
    conn.commit()
    first = _snapshot(conn)
    changes_before = conn.total_changes

    run_pending_migrations(conn)

    assert conn.total_changes == changes_before
    assert _snapshot(conn) == first
    outcome = conn.execute(
        "SELECT outcome FROM observations WHERE id = ?", (calendar_id,)
    ).fetchone()[0]
    assert outcome == "RETAIN_AND_EXTRACT"
    conn.close()


def test_migration_on_empty_store(db_path):
    conn = _legacy_store(db_path, rows=[])
    assert "drop_log" not in _tables(conn)

    run_pending_migrations(conn)

    assert "outcome" in _columns(conn, "observations")
    assert "drop_log" in _tables(conn)
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
    conn.close()


def test_fresh_store_has_outcome_and_drop_log(db_conn):
    assert "outcome" in _columns(db_conn, "observations")
    assert "drop_log" in _tables(db_conn)
