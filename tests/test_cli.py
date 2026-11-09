from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import zipfile
from datetime import UTC, datetime

import pytest
import yaml
from typer.testing import CliRunner

import patina.cleanup_meeting_obs as cleanup_meeting_obs
from patina.adapters.outlook_mcp import _email_from_raw
from patina.cli import _bootstrap_home, app
from patina.graph import insert_claim, insert_observation, upsert_entity
from patina.models import Claim, Entity, Observation
from patina.store import connect, get_db_path, init_db, run_pending_migrations

runner = CliRunner()


def test_bootstrap_home_soul_context_persistence(tmp_path):
    _bootstrap_home(tmp_path)
    soul_text = (tmp_path / "SOUL.md").read_text()
    assert "## Context Persistence" in soul_text
    assert "## Journal Search" in soul_text


def test_bootstrap_home_soul_references_journal_tools(tmp_path):
    _bootstrap_home(tmp_path)
    soul_text = (tmp_path / "SOUL.md").read_text()
    persistence, _, search = soul_text.partition("## Journal Search")
    assert "journal_write" in persistence.partition("## Context Persistence")[2]
    assert "journal_search" in search


def test_bootstrap_home_does_not_overwrite_existing_soul(tmp_path):
    soul = tmp_path / "SOUL.md"
    soul.write_text("custom soul content")
    _bootstrap_home(tmp_path)
    assert soul.read_text() == "custom soul content"


def test_init_creates_database(tmp_path):
    result = runner.invoke(app, ["init", "--home", str(tmp_path)], input="\n")
    assert result.exit_code == 0
    assert "Initialized" in result.output
    assert (tmp_path / "store.db").exists()


def test_ingest_no_adapters_shows_message(tmp_path):
    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "No adapters configured" in result.output


def test_ingest_with_valid_zip(tmp_path):
    zip_path = tmp_path / "export.zip"
    users = [{"id": "U001", "real_name": "Alice", "name": "alice"}]
    channels = [{"id": "C001", "name": "general"}]
    messages = [{"user": "U001", "text": "Hello!", "ts": "1700000100.000"}]

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("users.json", json.dumps(users))
        zf.writestr("channels.json", json.dumps(channels))
        zf.writestr("general/2023-11-15.json", json.dumps(messages))

    home = tmp_path / "patina_home"
    result = runner.invoke(app, ["ingest", "--from-export", str(zip_path), "--home", str(home)])
    assert result.exit_code == 0
    assert "Done" in result.output


def test_ingest_lookback_days_default(tmp_path, monkeypatch):
    called_with = {}

    def fake_ingest_all(*, home=None, lookback_days=3):
        called_with["lookback_days"] = lookback_days
        return {
            "messages_inserted": 0,
            "messages_skipped": 0,
            "entities_created": 0,
            "total_observations": 0,
            "total_entities": 0,
            "adapters_run": 1,
        }

    monkeypatch.setattr("patina.ingest.ingest_all", fake_ingest_all)

    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert called_with["lookback_days"] == 3


def test_ingest_lookback_days_custom(tmp_path, monkeypatch):
    called_with = {}

    def fake_ingest_all(*, home=None, lookback_days=3):
        called_with["lookback_days"] = lookback_days
        return {
            "messages_inserted": 5,
            "messages_skipped": 2,
            "entities_created": 3,
            "total_observations": 10,
            "total_entities": 5,
            "adapters_run": 1,
        }

    monkeypatch.setattr("patina.ingest.ingest_all", fake_ingest_all)

    result = runner.invoke(app, ["ingest", "--lookback-days", "30", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert called_with["lookback_days"] == 30
    assert "Done" in result.output


def test_status_uninitialized(tmp_path):
    home = tmp_path / "empty_home"
    home.mkdir()
    result = runner.invoke(app, ["status", "--home", str(home)])
    assert result.exit_code == 1


def test_status_after_init(tmp_path):
    runner.invoke(app, ["init", "--home", str(tmp_path)])
    result = runner.invoke(app, ["status", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "Observations" in result.output
    assert "Entities" in result.output


def _seed_extraction_runs(tmp_path):
    from patina.store import record_extraction_run

    db_path = get_db_path(tmp_path)
    init_db(db_path)
    conn = connect(db_path)
    base = {
        "observations_processed": 0,
        "claims_extracted": 0,
        "skipped_unresolved": 0,
        "alias_collisions": 0,
        "empty_skipped": 0,
        "errors": 0,
    }
    runs = [
        ("2026-10-23T09:00:00+00:00", 100, 7, 1, {"slack_live": 7}),
        ("2026-10-24T09:00:00+00:00", 200, 11, 2, {"slack_live": 3, "outlook_mcp_email": 8}),
        ("2026-10-25T09:00:00+00:00", 300, 13, 3, {"slack_live": 9, "outlook_mcp_email": 4}),
    ]
    for started, processed, skipped, collisions, skips_by_source in runs:
        record_extraction_run(
            conn,
            started_at=started,
            finished_at=started,
            model="sonnet",
            stats=base
            | {
                "observations_processed": processed,
                "skipped_unresolved": skipped,
                "alias_collisions": collisions,
            },
            by_source={
                src: {"skipped_unresolved": n, "alias_collisions": 0}
                for src, n in skips_by_source.items()
            },
        )
    conn.close()


def test_extract_history_prints_most_recent_runs_newest_first(tmp_path):
    _seed_extraction_runs(tmp_path)

    result = runner.invoke(app, ["extract", "--history", "2", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    lines = result.output.strip().splitlines()
    assert lines[0].split() == [
        "Date",
        "Processed",
        "Skipped",
        "Collisions",
        "Top",
        "source",
        "(skips)",
    ]
    assert len(lines) == 3
    assert lines[1].split() == ["2026-10-25", "09:00:00", "300", "13", "3", "slack_live", "(9)"]
    assert lines[2].split() == [
        "2026-10-24",
        "09:00:00",
        "200",
        "11",
        "2",
        "outlook_mcp_email",
        "(8)",
    ]


def test_extract_history_defaults_to_ten(tmp_path, monkeypatch):
    _seed_extraction_runs(tmp_path)
    called = {}
    monkeypatch.setattr(
        "patina.cli._print_extraction_history",
        lambda limit, home: called.setdefault("limit", limit),
    )

    result = runner.invoke(app, ["extract", "--history", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert called["limit"] == 10


def test_extract_history_does_not_extract(tmp_path, monkeypatch):
    _seed_extraction_runs(tmp_path)

    def boom(**kwargs):
        raise AssertionError("extract_beliefs should not run with --history")

    monkeypatch.setattr("patina.beliefs.extractor.extract_beliefs", boom)

    result = runner.invoke(app, ["extract", "--history", "5", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "2026-10-23" in result.output


def test_extract_count_without_history_rejected(tmp_path, monkeypatch):
    def boom(**kwargs):
        raise AssertionError("extract_beliefs should not run")

    monkeypatch.setattr("patina.beliefs.extractor.extract_beliefs", boom)

    result = runner.invoke(app, ["extract", "5", "--home", str(tmp_path)])

    assert result.exit_code == 2


def test_extract_history_empty(tmp_path):
    init_db(get_db_path(tmp_path))

    result = runner.invoke(app, ["extract", "--history", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "No extraction runs recorded." in result.output


def _fake_ingest_all(channels_seen=0, newly_watched=0, zero_streak=0):
    def fake(*, home=None, lookback_days=3):
        return {
            "messages_inserted": 5,
            "messages_skipped": 2,
            "entities_created": 3,
            "total_observations": 10,
            "total_entities": 5,
            "adapters_run": 1,
            "channels_seen": channels_seen,
            "newly_watched": newly_watched,
            "zero_streak": zero_streak,
        }

    return fake


def test_ingest_discovery_summary_always_printed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "patina.ingest.ingest_all",
        _fake_ingest_all(channels_seen=12, newly_watched=1),
    )
    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "Discovery: 12 channels seen, 1 newly watched" in result.output


def test_ingest_discovery_summary_with_zero_values(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "patina.ingest.ingest_all",
        _fake_ingest_all(channels_seen=0, newly_watched=0),
    )
    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "Discovery: 0 channels seen, 0 newly watched" in result.output


def test_ingest_streak_warning_at_threshold(tmp_path, monkeypatch):
    init_db(get_db_path(tmp_path))
    monkeypatch.setattr(
        "patina.ingest.ingest_all",
        _fake_ingest_all(channels_seen=0, zero_streak=3),
    )
    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "Warning: discovery returned 0 channels for 3 consecutive runs" in result.output
    assert "adapter/bridge response-shape change" in result.output
    assert "permission loss" in result.output
    assert "no group DMs" in result.output


def test_ingest_streak_warning_above_threshold(tmp_path, monkeypatch):
    init_db(get_db_path(tmp_path))
    monkeypatch.setattr(
        "patina.ingest.ingest_all",
        _fake_ingest_all(channels_seen=0, zero_streak=5),
    )
    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "Warning: discovery returned 0 channels for 5 consecutive runs" in result.output


def test_ingest_no_warning_below_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "patina.ingest.ingest_all",
        _fake_ingest_all(channels_seen=0, zero_streak=2),
    )
    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "Warning" not in result.output


def test_ingest_no_warning_when_channels_seen(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "patina.ingest.ingest_all",
        _fake_ingest_all(channels_seen=5, zero_streak=3),
    )
    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "Warning" not in result.output


def test_ingest_streak_warning_writes_journal(tmp_path, monkeypatch):
    init_db(get_db_path(tmp_path))
    monkeypatch.setattr(
        "patina.ingest.ingest_all",
        _fake_ingest_all(channels_seen=0, zero_streak=3),
    )
    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0

    conn = connect(get_db_path(tmp_path))
    try:
        row = conn.execute(
            "SELECT body, entry_type FROM journal WHERE entry_type = 'note' "
            "AND body LIKE '%discovery returned 0 channels%'"
        ).fetchone()
        assert row is not None
        assert row["entry_type"] == "note"
        assert "adapter/bridge response-shape change" in row["body"]
        assert "permission loss" in row["body"]
        assert "no group DMs" in row["body"]
    finally:
        conn.close()


def test_ingest_no_journal_when_no_warning(tmp_path, monkeypatch):
    init_db(get_db_path(tmp_path))
    monkeypatch.setattr(
        "patina.ingest.ingest_all",
        _fake_ingest_all(channels_seen=0, zero_streak=2),
    )
    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0

    conn = connect(get_db_path(tmp_path))
    try:
        row = conn.execute(
            "SELECT body FROM journal WHERE entry_type = 'note' "
            "AND body LIKE '%discovery returned 0 channels%'"
        ).fetchone()
        assert row is None
    finally:
        conn.close()


def test_ingest_no_journal_when_channels_seen(tmp_path, monkeypatch):
    init_db(get_db_path(tmp_path))
    monkeypatch.setattr(
        "patina.ingest.ingest_all",
        _fake_ingest_all(channels_seen=5, zero_streak=3),
    )
    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0

    conn = connect(get_db_path(tmp_path))
    try:
        row = conn.execute(
            "SELECT body FROM journal WHERE entry_type = 'note' "
            "AND body LIKE '%discovery returned 0 channels%'"
        ).fetchone()
        assert row is None
    finally:
        conn.close()


def test_ingest_discovery_threshold_default(tmp_path, monkeypatch):
    init_db(get_db_path(tmp_path))
    monkeypatch.setattr(
        "patina.ingest.ingest_all",
        _fake_ingest_all(channels_seen=0, zero_streak=3),
    )
    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "Warning" in result.output


def test_ingest_discovery_threshold_from_config(tmp_path, monkeypatch):
    init_db(get_db_path(tmp_path))
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"discovery": {"zero_streak_threshold": 5}}))

    monkeypatch.setattr(
        "patina.ingest.ingest_all",
        _fake_ingest_all(channels_seen=0, zero_streak=3),
    )
    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "Warning" not in result.output

    monkeypatch.setattr(
        "patina.ingest.ingest_all",
        _fake_ingest_all(channels_seen=0, zero_streak=5),
    )
    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "Warning" in result.output
    assert "5 consecutive runs" in result.output


# ── owner merge tests ──────────────────────────────────────────────


def _setup_owner_merge(tmp_path, owner_ids=None):
    """Set up a database with a canonical owner and duplicate entities."""
    init_db(get_db_path(tmp_path))

    config = {"owner": {"user_ids": owner_ids or ["U_OWNER"], "name": "Taro Tanaka"}}
    (tmp_path / "config.yaml").write_text(yaml.dump(config))

    conn = connect(get_db_path(tmp_path))
    now = "2026-01-01T00:00:00+00:00"

    conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}', ?, ?, 1)",
        ("owner-001", "Taro Tanaka", json.dumps(["U_OWNER", "slack:U_OWNER"]), now, now),
    )

    conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}', ?, ?, 0)",
        ("dup-001", "U_OWNER", json.dumps(["U_OWNER"]), now, now),
    )

    conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}', ?, ?, 0)",
        ("other-001", "Yuki Mori", json.dumps(["U_OTHER"]), now, now),
    )

    conn.commit()
    return conn


def test_owner_merge_reassigns_observations(tmp_path):
    conn = _setup_owner_merge(tmp_path)
    now = "2026-01-01T00:00:00+00:00"

    conn.execute(
        "INSERT INTO observations (id, source, timestamp, sender_entity_id, text, ingested_at)"
        " VALUES (?, 'test', 1000.0, ?, 'hello from dup', ?)",
        ("obs-dup-1", "dup-001", now),
    )
    conn.execute(
        "INSERT INTO observations (id, source, timestamp, sender_entity_id, text, ingested_at)"
        " VALUES (?, 'test', 1001.0, ?, 'hello from other', ?)",
        ("obs-other-1", "other-001", now),
    )
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["owner", "merge", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "Merged 1 duplicate" in result.output

    conn = connect(get_db_path(tmp_path))
    try:
        row = conn.execute(
            "SELECT sender_entity_id FROM observations WHERE id = 'obs-dup-1'"
        ).fetchone()
        assert row["sender_entity_id"] == "owner-001"

        row = conn.execute(
            "SELECT sender_entity_id FROM observations WHERE id = 'obs-other-1'"
        ).fetchone()
        assert row["sender_entity_id"] == "other-001"
    finally:
        conn.close()


def test_owner_merge_deduplicates_claims(tmp_path):
    conn = _setup_owner_merge(tmp_path)
    now = "2026-01-01T00:00:00+00:00"

    conn.execute(
        "INSERT INTO claims (id, subject_id, predicate, object,"
        " confidence, first_asserted, last_confirmed)"
        " VALUES (?, ?, 'likes', 'tea', 0.8, ?, ?)",
        ("claim-owner-1", "owner-001", now, now),
    )
    conn.execute(
        "INSERT INTO claims (id, subject_id, predicate, object,"
        " confidence, first_asserted, last_confirmed)"
        " VALUES (?, ?, 'likes', 'tea', 0.6, ?, ?)",
        ("claim-dup-1", "dup-001", now, now),
    )
    conn.execute(
        "INSERT INTO claims (id, subject_id, predicate, object,"
        " confidence, first_asserted, last_confirmed)"
        " VALUES (?, ?, 'speaks', 'english', 0.9, ?, ?)",
        ("claim-dup-2", "dup-001", now, now),
    )
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["owner", "merge", "--home", str(tmp_path)])
    assert result.exit_code == 0

    conn = connect(get_db_path(tmp_path))
    try:
        owner_claims = conn.execute(
            "SELECT * FROM claims WHERE subject_id = 'owner-001'"
        ).fetchall()
        predicates = {(c["predicate"], c["object"]) for c in owner_claims}
        assert ("likes", "tea") in predicates
        assert ("speaks", "english") in predicates
        assert len(owner_claims) == 2

        dup_claims = conn.execute("SELECT * FROM claims WHERE subject_id = 'dup-001'").fetchall()
        assert len(dup_claims) == 0
    finally:
        conn.close()


def test_owner_merge_reattributes_relationships(tmp_path):
    conn = _setup_owner_merge(tmp_path)
    now = "2026-01-01T00:00:00+00:00"

    conn.execute(
        "INSERT INTO relationships (id, subject_id, predicate,"
        " object_id, confidence, first_seen, last_confirmed)"
        " VALUES (?, ?, 'collaborates_with', ?, 0.7, ?, ?)",
        ("rel-dup-1", "dup-001", "other-001", now, now),
    )
    conn.execute(
        "INSERT INTO relationships (id, subject_id, predicate,"
        " object_id, confidence, first_seen, last_confirmed)"
        " VALUES (?, ?, 'reports_to', ?, 0.5, ?, ?)",
        ("rel-dup-2", "other-001", "dup-001", now, now),
    )
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["owner", "merge", "--home", str(tmp_path)])
    assert result.exit_code == 0

    conn = connect(get_db_path(tmp_path))
    try:
        rels = conn.execute(
            "SELECT * FROM relationships WHERE subject_id = 'dup-001' OR object_id = 'dup-001'"
        ).fetchall()
        assert len(rels) == 0

        rel1 = conn.execute(
            "SELECT * FROM relationships WHERE predicate = 'collaborates_with'"
        ).fetchone()
        assert rel1["subject_id"] == "owner-001"
        assert rel1["object_id"] == "other-001"

        rel2 = conn.execute("SELECT * FROM relationships WHERE predicate = 'reports_to'").fetchone()
        assert rel2["subject_id"] == "other-001"
        assert rel2["object_id"] == "owner-001"
    finally:
        conn.close()


def test_owner_merge_deletes_duplicate_entities(tmp_path):
    conn = _setup_owner_merge(tmp_path)
    conn.close()

    result = runner.invoke(app, ["owner", "merge", "--home", str(tmp_path)])
    assert result.exit_code == 0

    conn = connect(get_db_path(tmp_path))
    try:
        row = conn.execute("SELECT * FROM entities WHERE id = 'dup-001'").fetchone()
        assert row is None

        owner = conn.execute("SELECT * FROM entities WHERE id = 'owner-001'").fetchone()
        assert owner is not None
        assert owner["is_owner"] == 1

        other = conn.execute("SELECT * FROM entities WHERE id = 'other-001'").fetchone()
        assert other is not None
    finally:
        conn.close()


def test_owner_merge_noop_when_no_duplicates(tmp_path):
    init_db(get_db_path(tmp_path))
    config = {"owner": {"user_ids": ["U_OWNER"], "name": "Taro Tanaka"}}
    (tmp_path / "config.yaml").write_text(yaml.dump(config))

    conn = connect(get_db_path(tmp_path))
    now = "2026-01-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}', ?, ?, 1)",
        ("owner-001", "Taro Tanaka", json.dumps(["U_OWNER"]), now, now),
    )
    conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}', ?, ?, 0)",
        ("other-001", "Yuki Mori", json.dumps(["U_OTHER"]), now, now),
    )
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["owner", "merge", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "No duplicate" in result.output


def test_owner_merge_uses_get_owner_identifiers(tmp_path):
    init_db(get_db_path(tmp_path))
    config = {
        "owner": {
            "user_ids": ["U_OWNER"],
            "handles": ["taro.tanaka"],
            "display_names": ["Taro Tanaka"],
        }
    }
    (tmp_path / "config.yaml").write_text(yaml.dump(config))

    conn = connect(get_db_path(tmp_path))
    now = "2026-01-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}', ?, ?, 1)",
        ("owner-001", "Taro Tanaka", json.dumps(["U_OWNER"]), now, now),
    )
    conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}', ?, ?, 0)",
        ("dup-handle", "taro.tanaka", json.dumps(["display_name:taro.tanaka"]), now, now),
    )
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["owner", "merge", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "Merged 1 duplicate" in result.output

    conn = connect(get_db_path(tmp_path))
    try:
        row = conn.execute("SELECT * FROM entities WHERE id = 'dup-handle'").fetchone()
        assert row is None
    finally:
        conn.close()


def test_owner_merge_deduplicates_relationships(tmp_path):
    conn = _setup_owner_merge(tmp_path)
    now = "2026-01-01T00:00:00+00:00"

    conn.execute(
        "INSERT INTO relationships (id, subject_id, predicate,"
        " object_id, confidence, first_seen, last_confirmed)"
        " VALUES (?, ?, 'works_with', ?, 0.8, ?, ?)",
        ("rel-owner-1", "owner-001", "other-001", now, now),
    )
    conn.execute(
        "INSERT INTO relationships (id, subject_id, predicate,"
        " object_id, confidence, first_seen, last_confirmed)"
        " VALUES (?, ?, 'works_with', ?, 0.5, ?, ?)",
        ("rel-dup-1", "dup-001", "other-001", now, now),
    )
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["owner", "merge", "--home", str(tmp_path)])
    assert result.exit_code == 0

    conn = connect(get_db_path(tmp_path))
    try:
        rels = conn.execute("SELECT * FROM relationships WHERE predicate = 'works_with'").fetchall()
        assert len(rels) == 1
        assert rels[0]["subject_id"] == "owner-001"
    finally:
        conn.close()


def test_owner_merge_dry_run(tmp_path):
    conn = _setup_owner_merge(tmp_path)
    now = "2026-01-01T00:00:00+00:00"

    conn.execute(
        "INSERT INTO observations (id, source, timestamp, sender_entity_id, text, ingested_at)"
        " VALUES (?, 'test', 1000.0, ?, 'hello from dup', ?)",
        ("obs-dup-1", "dup-001", now),
    )
    conn.execute(
        "INSERT INTO claims (id, subject_id, predicate, object,"
        " confidence, first_asserted, last_confirmed)"
        " VALUES (?, ?, 'likes', 'tea', 0.8, ?, ?)",
        ("claim-dup-1", "dup-001", now, now),
    )
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["owner", "merge", "--dry-run", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "CANDIDATE" in result.output
    assert "dup-001" in result.output
    assert "observations:" in result.output
    assert "claims:" in result.output

    conn = connect(get_db_path(tmp_path))
    try:
        ent = conn.execute("SELECT * FROM entities WHERE id = 'dup-001'").fetchone()
        assert ent is not None
        obs = conn.execute(
            "SELECT sender_entity_id FROM observations WHERE id = 'obs-dup-1'"
        ).fetchone()
        assert obs["sender_entity_id"] == "dup-001"
    finally:
        conn.close()


def test_owner_merge_skips_non_owner_with_observations(tmp_path):
    """A candidate matched by alias whose name is not an owner id and has sent
    observations should be skipped with a warning."""
    init_db(get_db_path(tmp_path))

    config = {"owner": {"user_ids": ["U_OWNER"], "handles": ["shared-alias"]}}
    (tmp_path / "config.yaml").write_text(yaml.dump(config))

    conn = connect(get_db_path(tmp_path))
    now = "2026-01-01T00:00:00+00:00"

    conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}', ?, ?, 1)",
        ("owner-001", "Taro Tanaka", json.dumps(["U_OWNER"]), now, now),
    )
    conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}', ?, ?, 0)",
        ("colleague-001", "Yuki Mori", json.dumps(["shared-alias"]), now, now),
    )
    conn.execute(
        "INSERT INTO observations (id, source, timestamp, sender_entity_id, text, ingested_at)"
        " VALUES (?, 'test', 1000.0, ?, 'message from colleague', ?)",
        ("obs-col-1", "colleague-001", now),
    )
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["owner", "merge", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "SKIP" in result.output
    assert "colleague-001" in result.output
    assert "non-owner identity" in result.output

    conn = connect(get_db_path(tmp_path))
    try:
        ent = conn.execute("SELECT * FROM entities WHERE id = 'colleague-001'").fetchone()
        assert ent is not None
        obs = conn.execute(
            "SELECT sender_entity_id FROM observations WHERE id = 'obs-col-1'"
        ).fetchone()
        assert obs["sender_entity_id"] == "colleague-001"
    finally:
        conn.close()


def test_owner_merge_safety_allows_name_match_with_observations(tmp_path):
    """A candidate whose name matches an owner id should merge even with observations."""
    init_db(get_db_path(tmp_path))

    config = {"owner": {"user_ids": ["U_OWNER"]}}
    (tmp_path / "config.yaml").write_text(yaml.dump(config))

    conn = connect(get_db_path(tmp_path))
    now = "2026-01-01T00:00:00+00:00"

    conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}', ?, ?, 1)",
        ("owner-001", "Taro Tanaka", json.dumps(["U_OWNER"]), now, now),
    )
    conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}', ?, ?, 0)",
        ("dup-name", "U_OWNER", json.dumps([]), now, now),
    )
    conn.execute(
        "INSERT INTO observations (id, source, timestamp, sender_entity_id, text, ingested_at)"
        " VALUES (?, 'test', 1000.0, ?, 'hello', ?)",
        ("obs-dup-name", "dup-name", now),
    )
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["owner", "merge", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "Merged 1 duplicate" in result.output
    assert "SKIP" not in result.output

    conn = connect(get_db_path(tmp_path))
    try:
        ent = conn.execute("SELECT * FROM entities WHERE id = 'dup-name'").fetchone()
        assert ent is None
    finally:
        conn.close()


def test_autonomy_status_per_domain_output(tmp_path):
    from patina.autonomy.levels import freeze_advancement, set_level

    db_path = get_db_path(tmp_path)
    init_db(db_path)
    conn = connect(db_path)
    try:
        set_level(conn, 3, domain="triage")
        set_level(conn, 2, domain="draft")
        freeze_advancement(conn, domain="draft")
    finally:
        conn.close()

    result = runner.invoke(app, ["autonomy", "status", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "triage" in result.output
    assert "draft" in result.output
    assert "3" in result.output
    assert "2" in result.output
    assert "yes" in result.output
    assert "no" in result.output


def _setup_credential_references(tmp_path):
    """Store with 3 credential-bearing reference URLs, two sharing a base URL."""
    db_path = get_db_path(tmp_path)
    init_db(db_path)
    conn = connect(db_path)
    now = "2026-01-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen)"
        " VALUES ('p1', 'person', 'Alice Tran', '[]', '{}', ?, ?)",
        (now, now),
    )
    for eid, url in (
        ("ref-a", "https://meet.example.com/j/123?pwd=AbC123"),
        ("ref-b", "https://meet.example.com/j/123?pwd=AbC123zz"),
        ("ref-c", "https://files.example.com/doc?id=7&token=AbC123"),
    ):
        conn.execute(
            "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen)"
            " VALUES (?, 'reference', ?, '[]', '{}', ?, ?)",
            (eid, url, now, now),
        )
        conn.execute(
            "INSERT INTO claims (id, subject_id, predicate, object,"
            " confidence, first_asserted, last_confirmed)"
            " VALUES (?, ?, 'topic', 'sync', 0.5, ?, ?)",
            (f"c-{eid}", eid, now, now),
        )
        conn.execute(
            "INSERT INTO relationships (id, subject_id, predicate, object_id,"
            " first_seen, last_confirmed)"
            " VALUES (?, 'p1', 'shared', ?, ?, ?)",
            (f"r-{eid}", eid, now, now),
        )
    conn.commit()
    conn.close()
    return db_path


def _store_rows(db_path):
    conn = connect(db_path)
    try:
        return {
            table: [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()]
            for table in ("entities", "claims", "relationships")
        }
    finally:
        conn.close()


def test_entity_rekey_references_dry_run(tmp_path):
    db_path = _setup_credential_references(tmp_path)
    before = _store_rows(db_path)

    result = runner.invoke(app, ["entity", "rekey-references", "--home", str(tmp_path)])

    assert result.exit_code == 0
    assert "Would re-key 3 reference entity(ies) (2 renamed, 1 merged)" in result.stdout
    assert "https://meet.example.com/j/123" in result.stdout
    assert "https://files.example.com/doc?id=7" in result.stdout
    assert "re-run with --confirm" in result.stdout
    assert "AbC123" not in result.stdout
    assert "AbC123" not in result.stderr
    assert _store_rows(db_path) == before
    assert list(tmp_path.glob("*.bak.*")) == []


def test_entity_rekey_references_confirm(tmp_path):
    db_path = _setup_credential_references(tmp_path)

    result = runner.invoke(
        app, ["entity", "rekey-references", "--confirm", "--home", str(tmp_path)]
    )

    assert result.exit_code == 0
    assert "Backup:" in result.stdout
    assert "Re-keyed 3 reference entity(ies) (2 renamed, 1 merged)" in result.stdout
    assert "AbC123" not in result.stdout
    assert "AbC123" not in result.stderr
    assert len(list(tmp_path.glob("*.bak.*"))) == 1

    rows = _store_rows(db_path)
    assert not any("AbC123" in str(r) for r in rows["entities"])

    again = runner.invoke(app, ["entity", "rekey-references", "--confirm", "--home", str(tmp_path)])
    assert again.exit_code == 0
    assert "No credential-bearing reference entities found." in again.stdout
    assert _store_rows(db_path) == rows


def test_entity_rekey_references_help_shows_confirm():
    result = runner.invoke(app, ["entity", "rekey-references", "--help"])

    # CI forces Rich colour, and the escape codes split option names apart.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    assert result.exit_code == 0
    assert "--confirm" in plain


# --- cleanup-meeting-obs (#601) ---

_MEETING_SUBJECT = "The quick brown fox sync"


class _FakeOutlook:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def get_raw_message(self, source_id):
        self.calls.append(source_id)
        return self.payloads.get(source_id)


def _meeting_payload(conv_id, message_class, received):
    """Anonymized shape of a live Outlook meeting conversation (#580)."""
    return {
        "conversationId": conv_id,
        "topic": _MEETING_SUBJECT,
        "senders": ["Example, Jordan"],
        "from": {"name": "Jordan Example", "email": "jordan@example.com"},
        "recipients": ["Taylor, Morgan"],
        "preview": "",
        "receivedDateTime": received,
        "itemClasses": [message_class],
    }


_REFETCH = {
    "CONV_POS": ("IPM.Schedule.Meeting.Resp.Pos", "2026-10-01T15:04:05Z"),
    "CONV_REQ": ("IPM.Schedule.Meeting.Request", "2026-10-03T09:00:00Z"),
    "CONV_CXL": ("IPM.Schedule.Meeting.Canceled", "2026-10-05T18:30:00Z"),
}
# Rows carrying their class (or nothing) in stored metadata: (id, metadata, received, processed)
_STORED = [
    (
        "obs_meta_items",
        {"itemClasses": ["IPM.Schedule.Meeting.Request"], "conversationId": "META_1"},
        "2026-09-20T08:00:00Z",
        1,
    ),
    (
        "obs_meta_class",
        {"messageClass": "IPM.Schedule.Meeting.Resp.Pos", "id": "META_2"},
        "2026-10-10T12:00:00Z",
        0,
    ),
    ("obs_note", {"itemClasses": ["IPM.Note"], "preview": ""}, "2026-10-02T10:00:00Z", 0),
    (
        "obs_mixed",
        {"itemClasses": ["IPM.Note", "IPM.Schedule.Meeting.Resp.Pos"]},
        "2026-10-04T10:00:00Z",
        0,
    ),
    ("obs_no_id", {"channel_name": None}, "2026-08-15T07:00:00Z", 0),
    ("obs_gone", {"conversationId": "GONE"}, "2026-11-01T22:00:00Z", 0),
]
_SELECTED_IDS = {"obs_pos", "obs_req", "obs_cxl", "obs_meta_items", "obs_meta_class"}
_UNDETERMINED_IDS = {"obs_no_id", "obs_gone"}
_EXPECTED_CLASSES = {
    "obs_pos": "IPM.Schedule.Meeting.Resp.Pos",
    "obs_req": "IPM.Schedule.Meeting.Request",
    "obs_cxl": "IPM.Schedule.Meeting.Canceled",
    "obs_meta_items": "IPM.Schedule.Meeting.Request",
    "obs_meta_class": "IPM.Schedule.Meeting.Resp.Pos",
}


def _iso_ts(iso):
    return datetime.fromisoformat(iso).timestamp()


def _fmt_ts(ts):
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _fmt(iso):
    return _fmt_ts(_iso_ts(iso))


def _seed_meeting_store(tmp_path, *, cite=True):
    db_path = get_db_path(tmp_path)
    init_db(db_path)
    conn = connect(db_path)
    run_pending_migrations(conn)
    conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen)"
        " VALUES ('ent_jordan', 'person', 'Jordan Example', '[]', '{}', 'x', 'x')"
    )
    for obs_id, conv_id, meta in (
        ("obs_pos", "CONV_POS", {"channel_name": None, "reactions": []}),
        ("obs_req", "CONV_REQ", {"channel_name": None, "reactions": []}),
        (
            "obs_cxl",
            "CONV_CXL",
            {"channel_name": None, "reactions": [], "organizer_dn": "Example, Jordan"},
        ),
    ):
        message_class, received = _REFETCH[conv_id]
        # Live store shape (#609): no class fields and no ID in metadata; the
        # conversation ID is only in thread_id and channel_id.
        em = _email_from_raw(_meeting_payload(conv_id, message_class, received))
        insert_observation(
            conn,
            Observation(
                id=obs_id,
                source="outlook_mcp_email",
                channel_id=f"email:{em.conversation_id}",
                thread_id=em.conversation_id,
                timestamp=em.timestamp,
                sender_entity_id=None,
                text=em.text,
                metadata=meta,
            ),
        )
    for obs_id, meta, received, processed in _STORED:
        insert_observation(
            conn,
            Observation(
                id=obs_id,
                source="outlook_mcp_email",
                channel_id=None,
                thread_id=None,
                timestamp=_iso_ts(received),
                sender_entity_id=None,
                text=f"[Subject: {_MEETING_SUBJECT}] [Participants: Jordan Example]\n",
                metadata=meta,
                processed=processed,
            ),
        )
    if cite:
        for claim_id, obs_ids in (
            ("claim_a", ["obs_pos", "obs_meta_items"]),
            ("claim_b", ["obs_pos"]),
        ):
            insert_claim(
                conn,
                Claim(
                    id=claim_id,
                    subject_id="ent_jordan",
                    predicate="attends",
                    object=_MEETING_SUBJECT,
                    source_ids=obs_ids,
                ),
            )
    conn.commit()
    conn.close()
    return db_path


def _fake_outlook(monkeypatch):
    payloads = {
        conv_id: _meeting_payload(conv_id, message_class, received)
        for conv_id, (message_class, received) in _REFETCH.items()
    }
    payloads["GONE"] = None
    fake = _FakeOutlook(payloads)
    monkeypatch.setattr("patina.cli._load_outlook_refetch_adapter", lambda home: fake)
    return fake


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _outlook_ids(db_path):
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id FROM observations WHERE source = 'outlook_mcp_email'"
        ).fetchall()
        return {r["id"] for r in rows}
    finally:
        conn.close()


def _row_line(stdout, obs_id):
    lines = [line for line in stdout.splitlines() if obs_id in line]
    assert len(lines) == 1, lines
    return lines[0]


def test_cleanup_meeting_obs_dry_run_is_read_only(tmp_path, monkeypatch):
    db_path = _seed_meeting_store(tmp_path)
    _fake_outlook(monkeypatch)
    real_connect_readonly = cleanup_meeting_obs.connect_readonly
    write_errors = []

    def _spy(path):
        conn = real_connect_readonly(path)
        with pytest.raises(sqlite3.OperationalError) as exc:
            conn.execute("CREATE TABLE _probe (x)")
        write_errors.append(str(exc.value))
        return conn

    monkeypatch.setattr(cleanup_meeting_obs, "connect_readonly", _spy)
    before = _sha256(db_path)

    result = runner.invoke(app, ["cleanup-meeting-obs", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert _sha256(db_path) == before
    assert len(write_errors) == 1
    assert "readonly" in write_errors[0]
    assert list(tmp_path.glob("*.bak.*")) == []


def test_cleanup_meeting_obs_dry_run_text_report(tmp_path, monkeypatch):
    _seed_meeting_store(tmp_path)
    _fake_outlook(monkeypatch)

    result = runner.invoke(app, ["cleanup-meeting-obs", "--home", str(tmp_path)])
    out = result.stdout

    assert result.exit_code == 0, result.output
    assert "Selected: 5 meeting observation(s)" in out
    assert f"Earliest: {_fmt('2026-09-20T08:00:00Z')}" in out
    assert f"Latest: {_fmt('2026-10-10T12:00:00Z')}" in out
    assert "Processed: 1  Unprocessed: 4" in out

    dates = {
        "obs_pos": _REFETCH["CONV_POS"][1],
        "obs_req": _REFETCH["CONV_REQ"][1],
        "obs_cxl": _REFETCH["CONV_CXL"][1],
        "obs_meta_items": "2026-09-20T08:00:00Z",
        "obs_meta_class": "2026-10-10T12:00:00Z",
    }
    citations = {"obs_pos": 2, "obs_meta_items": 1}
    for obs_id in _SELECTED_IDS:
        line = _row_line(out, obs_id)
        assert _fmt(dates[obs_id]) in line
        assert _EXPECTED_CLASSES[obs_id] in line
        assert f"citing claims: {citations.get(obs_id, 0)}" in line
    assert "Total citing claims: 3" in out

    undetermined_range = f"{_fmt('2026-08-15T07:00:00Z')} to {_fmt('2026-11-01T22:00:00Z')}"
    assert f"Undetermined (not selected): 2 ({undetermined_range})" in out
    for obs_id in _UNDETERMINED_IDS | {"obs_note", "obs_mixed"}:
        assert obs_id not in out
    assert _MEETING_SUBJECT not in result.output
    assert "quick brown fox" not in result.output


def test_cleanup_meeting_obs_json_matches_text_and_store(tmp_path, monkeypatch):
    db_path = _seed_meeting_store(tmp_path)
    _fake_outlook(monkeypatch)

    text = runner.invoke(app, ["cleanup-meeting-obs", "--home", str(tmp_path)]).stdout
    result = runner.invoke(app, ["cleanup-meeting-obs", "--json", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)

    # Same values as the text output.
    assert f"Selected: {data['selected_count']} meeting" in text
    assert f"Earliest: {data['earliest']}" in text
    assert f"Latest: {data['latest']}" in text
    assert f"Processed: {data['processed']}  Unprocessed: {data['unprocessed']}" in text
    for row in data["selected"]:
        line = _row_line(text, row["observation_id"])
        assert row["date"] in line
        assert ", ".join(row["item_classes"]) in line
        assert f"citing claims: {row['citing_claims']}" in line
    assert f"Total citing claims: {data['total_citations']}" in text
    und = data["undetermined"]
    assert (
        f"Undetermined (not selected): {und['count']} ({und['earliest']} to {und['latest']})"
    ) in text

    # Same values as direct queries of the fixture store.
    conn = connect(db_path)
    try:
        obs = {
            r["id"]: r
            for r in conn.execute(
                "SELECT id, timestamp, processed FROM observations"
                " WHERE source = 'outlook_mcp_email'"
            ).fetchall()
        }
        claim_sources = [
            json.loads(r["source_ids"])
            for r in conn.execute("SELECT source_ids FROM claims").fetchall()
        ]
    finally:
        conn.close()

    by_id = {row["observation_id"]: row for row in data["selected"]}
    assert set(by_id) == _SELECTED_IDS
    assert data["selected_count"] == len(_SELECTED_IDS)
    selected_ts = [obs[i]["timestamp"] for i in _SELECTED_IDS]
    assert data["earliest"] == _fmt_ts(min(selected_ts))
    assert data["latest"] == _fmt_ts(max(selected_ts))
    assert data["processed"] == sum(1 for i in _SELECTED_IDS if obs[i]["processed"])
    assert data["unprocessed"] == sum(1 for i in _SELECTED_IDS if not obs[i]["processed"])
    total = 0
    for obs_id, row in by_id.items():
        cites = sum(1 for sids in claim_sources if obs_id in sids)
        total += cites
        assert row["date"] == _fmt_ts(obs[obs_id]["timestamp"])
        assert row["item_classes"] == [_EXPECTED_CLASSES[obs_id]]
        assert row["citing_claims"] == cites
    assert data["total_citations"] == total == 3
    undetermined_ts = [obs[i]["timestamp"] for i in _UNDETERMINED_IDS]
    assert und == {
        "count": len(_UNDETERMINED_IDS),
        "earliest": _fmt_ts(min(undetermined_ts)),
        "latest": _fmt_ts(max(undetermined_ts)),
        "reasons": {
            "no_source_id": 1,
            "not_in_current_inbox": 1,
            "no_class_fields": 0,
            "refetch_unavailable": 0,
        },
        "zero_timestamp": 0,
    }
    for reason, count in und["reasons"].items():
        assert f"  {reason}: {count}" in text
    assert "  zero_timestamp: 0" in text


def test_cleanup_meeting_obs_classifies_fixture_rows(tmp_path, monkeypatch):
    _seed_meeting_store(tmp_path)
    fake = _fake_outlook(monkeypatch)

    result = runner.invoke(app, ["cleanup-meeting-obs", "--json", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert {row["observation_id"] for row in data["selected"]} == _SELECTED_IDS
    # Rows with stored itemClasses/messageClass never reach the adapter.
    assert sorted(fake.calls) == ["CONV_CXL", "CONV_POS", "CONV_REQ", "GONE"]
    assert data["undetermined"]["count"] == len(_UNDETERMINED_IDS)


def test_cleanup_meeting_obs_reports_undetermined_reasons(tmp_path, monkeypatch):
    """#609: live-shape rows outside the re-fetch listing, or dated 0, are reported."""
    db_path = get_db_path(tmp_path)
    init_db(db_path)
    conn = connect(db_path)
    run_pending_migrations(conn)
    live_meta = {"channel_name": None, "reactions": []}
    for obs_id, conv_id, received in (
        ("obs_pos", "CONV_POS", "2026-10-01T15:04:05Z"),
        ("obs_old", "CONV_OLD", "2026-03-01T09:00:00Z"),
        ("obs_older", "CONV_OLDER", "2026-02-01T09:00:00Z"),
        ("obs_epoch", "CONV_EPOCH", None),
    ):
        insert_observation(
            conn,
            Observation(
                id=obs_id,
                source="outlook_mcp_email",
                channel_id=f"email:{conv_id}",
                thread_id=conv_id,
                timestamp=_iso_ts(received) if received else 0.0,
                sender_entity_id=None,
                text=f"[Subject: {_MEETING_SUBJECT}] [Participants: Jordan Example]\n",
                metadata=live_meta,
            ),
        )
    conn.commit()
    conn.close()
    _fake_outlook(monkeypatch)

    text = runner.invoke(app, ["cleanup-meeting-obs", "--home", str(tmp_path)])
    result = runner.invoke(app, ["cleanup-meeting-obs", "--json", "--home", str(tmp_path)])

    assert text.exit_code == 0, text.output
    out = text.stdout
    assert "Selected: 1 meeting observation(s)" in out
    assert "obs_pos" in out
    range_ = f"{_fmt('2026-02-01T09:00:00Z')} to {_fmt('2026-03-01T09:00:00Z')}"
    assert f"Undetermined (not selected): 3 ({range_})" in out
    assert "  not_in_current_inbox: 3" in out
    assert "  no_source_id: 0" in out
    assert "  zero_timestamp: 1" in out
    assert "1970" not in out

    data = json.loads(result.stdout)
    assert [row["observation_id"] for row in data["selected"]] == ["obs_pos"]
    assert data["undetermined"]["count"] == 3
    assert data["undetermined"]["reasons"]["not_in_current_inbox"] == 3
    assert data["undetermined"]["zero_timestamp"] == 1
    assert data["undetermined"]["earliest"] == _fmt("2026-02-01T09:00:00Z")


def test_cleanup_meeting_obs_follows_is_meeting_message(tmp_path, monkeypatch):
    _seed_meeting_store(tmp_path)
    _fake_outlook(monkeypatch)
    monkeypatch.setattr(
        "patina.adapters.outlook_mcp._is_meeting_message",
        lambda raw: raw.get("itemClasses") == ["IPM.Note"],
    )

    result = runner.invoke(app, ["cleanup-meeting-obs", "--json", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert [row["observation_id"] for row in data["selected"]] == ["obs_note"]


def test_cleanup_meeting_obs_confirm_removes_only_selected(tmp_path, monkeypatch):
    db_path = _seed_meeting_store(tmp_path, cite=False)
    _fake_outlook(monkeypatch)
    real_backup = cleanup_meeting_obs.backup_store
    backup_calls = []

    def _spy(path):
        backup_calls.append(path)
        return real_backup(path)

    monkeypatch.setattr(cleanup_meeting_obs, "backup_store", _spy)
    before = _outlook_ids(db_path)

    result = runner.invoke(app, ["cleanup-meeting-obs", "--confirm", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert backup_calls == [db_path]
    backups = list(tmp_path.glob("*.bak.*"))
    assert len(backups) == 1
    assert f"Backup: {backups[0]}" in result.stdout
    assert _outlook_ids(backups[0]) == before
    assert before == _SELECTED_IDS | _UNDETERMINED_IDS | {"obs_note", "obs_mixed"}
    assert _outlook_ids(db_path) == _UNDETERMINED_IDS | {"obs_note", "obs_mixed"}
    assert "Deleted 5 observation(s)" in result.stdout
    assert "outlook_mcp_email observations: 9 -> 4" in result.stdout


def test_cleanup_meeting_obs_confirm_refuses_cited_rows(tmp_path, monkeypatch):
    db_path = _seed_meeting_store(tmp_path)
    _fake_outlook(monkeypatch)
    before = _sha256(db_path)

    result = runner.invoke(app, ["cleanup-meeting-obs", "--confirm", "--home", str(tmp_path)])

    assert result.exit_code != 0
    assert "Refusing to delete: 2 selected row(s) have citing claims" in result.stdout
    assert "obs_pos  citing claims: 2" in result.stdout
    assert "obs_meta_items  citing claims: 1" in result.stdout
    assert "No changes made." in result.stdout
    assert _sha256(db_path) == before
    assert list(tmp_path.glob("*.bak.*")) == []


def test_cleanup_meeting_obs_second_confirm_is_noop(tmp_path, monkeypatch):
    db_path = _seed_meeting_store(tmp_path, cite=False)
    _fake_outlook(monkeypatch)
    first = runner.invoke(app, ["cleanup-meeting-obs", "--confirm", "--home", str(tmp_path)])
    assert first.exit_code == 0, first.output
    rows = _outlook_ids(db_path)
    digest = _sha256(db_path)
    backups = set(tmp_path.glob("*.bak.*"))

    again = runner.invoke(app, ["cleanup-meeting-obs", "--confirm", "--home", str(tmp_path)])

    assert again.exit_code == 0, again.output
    assert "Selected: 0 meeting observation(s)" in again.stdout
    assert "Deleted 0 observation(s)" in again.stdout
    assert "outlook_mcp_email observations: 4 -> 4" in again.stdout
    assert "Backup:" not in again.stdout
    assert _outlook_ids(db_path) == rows
    assert _sha256(db_path) == digest
    assert set(tmp_path.glob("*.bak.*")) == backups


def test_cleanup_meeting_obs_uninitialized(tmp_path):
    result = runner.invoke(app, ["cleanup-meeting-obs", "--home", str(tmp_path / "missing")])

    assert result.exit_code == 1
    assert "not initialized" in result.output


def _stored_objective(tmp_path):
    conn = connect(get_db_path(tmp_path))
    row = conn.execute(
        "SELECT id, label, keywords, participants, customer_domains FROM objectives"
    ).fetchone()
    conn.close()
    return row


def test_objectives_add_and_update_targets(tmp_path):
    home = ["--home", str(tmp_path)]
    added = runner.invoke(
        app,
        [
            "objectives",
            "add",
            "Ship Atlas",
            "--keywords",
            "atlas",
            "--participant",
            " Jordan.Example@Example.com",
            "--participant",
            "e1",
            "--customer-domain",
            "Example.com",
            *home,
        ],
    )
    assert added.exit_code == 0, added.output
    assert "participants: jordan.example@example.com, e1" in added.output
    assert "customer_domains: example.com" in added.output

    row = _stored_objective(tmp_path)
    assert json.loads(row["participants"]) == ["jordan.example@example.com", "e1"]
    assert json.loads(row["customer_domains"]) == ["example.com"]

    updated = runner.invoke(
        app,
        [
            "objectives",
            "update",
            row["id"][:8],
            "--customer-domain",
            "example.org",
            "--customer-domain",
            "Example.net",
            *home,
        ],
    )
    assert updated.exit_code == 0, updated.output
    assert "customer_domains: example.org, example.net" in updated.output

    row = _stored_objective(tmp_path)
    assert row["label"] == "Ship Atlas"
    assert row["keywords"] == "atlas"
    assert json.loads(row["participants"]) == ["jordan.example@example.com", "e1"]
    assert json.loads(row["customer_domains"]) == ["example.org", "example.net"]

    updated = runner.invoke(app, ["objectives", "update", row["id"], "--participant", "e2", *home])
    assert updated.exit_code == 0, updated.output
    assert json.loads(_stored_objective(tmp_path)["participants"]) == ["e2"]

    listed = runner.invoke(app, ["objectives", "list", *home])
    assert listed.exit_code == 0, listed.output
    assert "Ship Atlas (keywords: atlas)" in listed.output
    assert "participants: e2" in listed.output
    assert "customer_domains: example.org, example.net" in listed.output


def test_objectives_add_without_targets_lists_empty(tmp_path):
    home = ["--home", str(tmp_path)]
    assert runner.invoke(app, ["objectives", "add", "Ship Atlas", *home]).exit_code == 0

    row = _stored_objective(tmp_path)
    assert json.loads(row["participants"]) == []
    assert json.loads(row["customer_domains"]) == []

    listed = runner.invoke(app, ["objectives", "list", *home])
    assert "participants: -" in listed.output
    assert "customer_domains: -" in listed.output


def test_objectives_update_unknown_id_fails(tmp_path):
    result = runner.invoke(
        app,
        ["objectives", "update", "ffffffff", "--participant", "e1", "--home", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "No objective updated" in result.output


# --- #618: ingest --dry-run relevance report ---

_DRY_OWNER_TO = [{"name": "Owner, Jane", "email": "owner@example.com"}]
_DRY_TEAM_ALL = [{"name": "Team All", "email": "team-all@example.com", "isDistributionList": True}]


def _dry_item(n: int, subject: str, senders: list[str], to: list[dict]) -> dict:
    return {
        "conversationId": f"AAQkADDryConv{n:03d}=",
        "id": f"AAMkADDryMsg{n:03d}=",
        "itemClasses": ["IPM.Note"],
        "topic": subject,
        "senders": senders,
        "toRecipients": to,
        "ccRecipients": [{"name": "Lee, Casey", "email": "casey.lee@example.com"}],
        "receivedDateTime": f"2026-11-03T09:{n:02d}:42Z",
        "preview": f"Body {n}: the lazy dog naps in the sun.",
    }


_DRY_ITEMS = [
    _dry_item(1, "Re: The quick brown fox — Q3 plan", ["Example, Jordan"], _DRY_OWNER_TO),
    _dry_item(2, "Fox launch notes", ["Sample, Riley"], _DRY_OWNER_TO),
    _dry_item(3, "All-hands recap", ["Placeholder, Taylor"], _DRY_TEAM_ALL),
    _dry_item(4, "Your weekly digest", ["no-reply@example.com"], _DRY_OWNER_TO),
    _dry_item(5, "Build finished", ["notifications@tool.example"], _DRY_OWNER_TO),
]


class _DryRunOutlookPort:
    def __init__(self, items: list[dict]) -> None:
        self._items = items

    @property
    def platform(self) -> str:
        return "outlook_mcp"

    def list_inbox(self, since: float):
        return [_email_from_raw(item) for item in self._items]

    def search_sent(self, query: str):
        return []


def _dry_run_home(tmp_path, monkeypatch, *, seed: bool = True):
    from patina.ingest import ingest_live

    (tmp_path / "config.yaml").write_text(
        yaml.dump(
            {
                "owner": {"emails": ["owner@example.com"]},
                "ingest": {"outlook_relevance_filter": True},
            }
        )
    )
    if seed:
        # Pre-existing store holding one earlier observation.
        seed_item = _dry_item(9, "Earlier thread", ["Example, Jordan"], _DRY_OWNER_TO)
        ingest_live(
            port=_DryRunOutlookPort([seed_item]),
            source="outlook_mcp_email",
            home=tmp_path,
            lookback_days=10000,
        )
    monkeypatch.setattr(
        "patina.ingest._load_adapters",
        lambda home: [("outlook_mcp_email", _DryRunOutlookPort(_DRY_ITEMS))],
    )
    return get_db_path(tmp_path)


def _sqlite_dump(db_path) -> list[str]:
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def test_ingest_dry_run_prints_counts_by_reason(tmp_path, monkeypatch):
    _dry_run_home(tmp_path, monkeypatch)

    result = runner.invoke(app, ["ingest", "--dry-run", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "Outlook relevance: 5 fetched, 2 kept, 3 dropped" in result.output
    assert "  direct: 2" in result.output
    assert "  dropped_bot_or_list: 2" in result.output
    assert "  dropped_not_direct: 1" in result.output
    # #633: the not_direct sender has only a display name and no address in the store.
    assert "  sender_unresolved: 1" in result.output


def test_ingest_dry_run_counts_shared_outlook_inbox_once(tmp_path, monkeypatch):
    """#641: the email and calendar adapters both list the one outlook_mcp inbox."""
    _dry_run_home(tmp_path, monkeypatch, seed=False)
    monkeypatch.setattr(
        "patina.ingest._load_adapters",
        lambda home: [
            ("outlook_mcp_email", _DryRunOutlookPort(_DRY_ITEMS)),
            ("outlook_mcp_calendar", _DryRunOutlookPort(_DRY_ITEMS)),
        ],
    )

    result = runner.invoke(app, ["ingest", "--dry-run", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert f"Outlook relevance: {len(_DRY_ITEMS)} fetched, 2 kept, 3 dropped" in result.output


def test_ingest_dry_run_leaves_store_byte_identical(tmp_path, monkeypatch):
    db_path = _dry_run_home(tmp_path, monkeypatch)
    before_hash = _sha256(db_path)
    before_dump = _sqlite_dump(db_path)

    result = runner.invoke(app, ["ingest", "--dry-run", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "direct: 2" in result.output  # emails that would be kept are still not written
    assert _sha256(db_path) == before_hash
    assert _sqlite_dump(db_path) == before_dump


def test_ingest_dry_run_without_store_creates_none(tmp_path, monkeypatch):
    db_path = _dry_run_home(tmp_path, monkeypatch, seed=False)

    result = runner.invoke(app, ["ingest", "--dry-run", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert not db_path.exists()


def test_ingest_dry_run_output_has_no_email_content(tmp_path, monkeypatch):
    _dry_run_home(tmp_path, monkeypatch)

    result = runner.invoke(app, ["ingest", "--dry-run", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    out = result.output.casefold()
    for item in _DRY_ITEMS:
        assert item["topic"].casefold() not in out
        assert "lazy dog" not in out
        for sender in item["senders"]:
            assert sender.casefold() not in out
        for recipient in [*item["toRecipients"], *item["ccRecipients"]]:
            assert recipient["email"] not in out
            assert recipient["name"].casefold() not in out
    assert "@" not in out


def test_ingest_dry_run_rejects_from_export(tmp_path):
    result = runner.invoke(
        app, ["ingest", "--dry-run", "--from-export", "x.zip", "--home", str(tmp_path)]
    )
    assert result.exit_code == 2


def test_contradictions_prints_uncapped_totals_before_capped_listing(tmp_path):
    db_path = get_db_path(tmp_path)
    init_db(db_path)
    conn = connect(db_path)
    upsert_entity(conn, Entity(id="e1", type="person", name="Jordan"))
    claims = [("location", f"Town {i}") for i in range(15)]  # 105 pairs, over the cap
    claims += [("org", "Example Corp"), ("org", "Sample Industries")]
    claims += [("title", "Engineer"), ("title", "Designer")]
    for i, (predicate, obj) in enumerate(claims):
        insert_claim(conn, Claim(id=f"c{i:02d}", subject_id="e1", predicate=predicate, object=obj))
    conn.close()

    result = runner.invoke(app, ["contradictions", "--home", str(tmp_path)])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "Uncapped totals: location=105, org=1, title=1"
    assert lines[1] == "Found 100 contradiction(s):"
