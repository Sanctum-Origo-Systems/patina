from __future__ import annotations

import json
import zipfile

import yaml
from typer.testing import CliRunner

from patina.cli import _bootstrap_home, app
from patina.store import connect, get_db_path, init_db

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
