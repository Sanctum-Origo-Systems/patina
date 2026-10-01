from __future__ import annotations

import json

from patina.graph import (
    insert_claim,
    insert_observation,
    upsert_entity,
    upsert_relationship,
)
from patina.maintenance import (
    backup_store,
    dedup_entities,
    find_dedup_candidates,
    is_non_person,
    merge_entities,
    prune_non_person_entities,
    reprocess_observations,
    rewire_entity_references,
)
from patina.models import Claim, Entity, Observation, Relationship


def _entity(eid, name, aliases=None):
    return Entity(id=eid, type="person", name=name, aliases=aliases or [])


def _insert_entity_raw(conn, eid, name, aliases=None, is_owner=0):
    """Insert entity directly, bypassing resolve_entity_id."""
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    conn.execute(
        "INSERT INTO entities"
        " (id, type, name, aliases, metadata,"
        "  first_seen, last_seen, decay_rate, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}', ?, ?, 0.02, ?)",
        (eid, name, json.dumps(aliases or []), now, now, is_owner),
    )
    conn.commit()


def _obs(oid, sender_id, source="slack_export", ts=1000.0, processed=0):
    return Observation(
        id=oid,
        source=source,
        channel_id="C001",
        thread_id=None,
        timestamp=ts,
        sender_entity_id=sender_id,
        text="The quick brown fox",
        processed=processed,
    )


def _claim(cid, subject_id, predicate="role", obj="engineer"):
    return Claim(
        id=cid,
        subject_id=subject_id,
        predicate=predicate,
        object=obj,
    )


def _rel(rid, subj, obj, predicate="works_with"):
    return Relationship(
        id=rid,
        subject_id=subj,
        predicate=predicate,
        object_id=obj,
    )


# ── is_non_person ────────────────────────────────────────────


def test_is_non_person_bot_suffix():
    assert is_non_person("Build Bot") is True
    assert is_non_person("deploy bot") is True


def test_is_non_person_room_suffix():
    assert is_non_person("Weekly Sync Room") is True


def test_is_non_person_calendar_suffix():
    assert is_non_person("Team Calendar") is True


def test_is_non_person_noreply_prefix():
    assert is_non_person("noreply@example.com") is True
    assert is_non_person("no-reply@example.com") is True


def test_is_non_person_regular_name():
    assert is_non_person("Sam Rivera") is False
    assert is_non_person("Alice Chen") is False


def test_is_non_person_short_name():
    assert is_non_person("A") is False


def test_is_non_person_empty():
    assert is_non_person("") is False


def test_is_non_person_bot_parenthetical():
    assert is_non_person("Jenkins (Bot)") is True


# ── backup_store ─────────────────────────────────────────────


def test_backup_store_creates_file(db_path):
    backup = backup_store(db_path)
    assert backup.exists()
    assert backup.stat().st_size > 0
    assert ".bak." in backup.name


# ── rewire_entity_references ────────────────────────────────


def test_rewire_moves_observations(db_conn):
    upsert_entity(db_conn, _entity("e1", "Alice Tran"))
    upsert_entity(db_conn, _entity("e2", "alice.tran"))
    insert_observation(db_conn, _obs("o1", "e2"))

    counts = rewire_entity_references(db_conn, "e1", "e2")
    assert counts["observations"] == 1

    row = db_conn.execute("SELECT sender_entity_id FROM observations WHERE id = 'o1'").fetchone()
    assert row["sender_entity_id"] == "e1"


def test_rewire_moves_claims(db_conn):
    upsert_entity(db_conn, _entity("e1", "Alice Tran"))
    upsert_entity(db_conn, _entity("e2", "alice.tran"))
    insert_claim(db_conn, _claim("c1", "e2"))

    counts = rewire_entity_references(db_conn, "e1", "e2")
    assert counts["claims"] == 1

    row = db_conn.execute("SELECT subject_id FROM claims WHERE id = 'c1'").fetchone()
    assert row["subject_id"] == "e1"


def test_rewire_moves_relationships(db_conn):
    upsert_entity(db_conn, _entity("e1", "Alice Tran"))
    upsert_entity(db_conn, _entity("e2", "alice.tran"))
    upsert_entity(db_conn, _entity("e3", "Bob Marsh"))
    upsert_relationship(db_conn, _rel("r1", "e2", "e3"))
    upsert_relationship(db_conn, _rel("r2", "e3", "e2"))

    counts = rewire_entity_references(db_conn, "e1", "e2")
    assert counts["relationships"] == 2

    r1 = db_conn.execute("SELECT subject_id FROM relationships WHERE id = 'r1'").fetchone()
    assert r1["subject_id"] == "e1"

    r2 = db_conn.execute("SELECT object_id FROM relationships WHERE id = 'r2'").fetchone()
    assert r2["object_id"] == "e1"


def test_rewire_removes_self_referencing_relationships(db_conn):
    upsert_entity(db_conn, _entity("e1", "Alice Tran"))
    upsert_entity(db_conn, _entity("e2", "alice.tran"))
    upsert_relationship(db_conn, _rel("r1", "e1", "e2"))

    rewire_entity_references(db_conn, "e1", "e2")

    row = db_conn.execute("SELECT COUNT(*) AS c FROM relationships WHERE id = 'r1'").fetchone()
    assert row["c"] == 0


def test_rewire_does_not_delete_unrelated_self_refs(db_conn):
    """Regression: DELETE should only remove self-refs for keep_id, not all."""
    upsert_entity(db_conn, _entity("e1", "Alice Tran"))
    upsert_entity(db_conn, _entity("e2", "alice.tran"))
    upsert_entity(db_conn, _entity("e3", "Bob Marsh"))
    upsert_relationship(db_conn, _rel("r1", "e1", "e2"))
    upsert_relationship(db_conn, _rel("r_self", "e3", "e3"))

    rewire_entity_references(db_conn, "e1", "e2")

    row = db_conn.execute("SELECT COUNT(*) AS c FROM relationships WHERE id = 'r_self'").fetchone()
    assert row["c"] == 1, "Unrelated self-referencing relationship should not be deleted"


# ── merge_entities ───────────────────────────────────────────


def test_merge_entities_basic(db_conn):
    upsert_entity(db_conn, _entity("e1", "Sam Rivera", ["srivera"]))
    upsert_entity(db_conn, _entity("e2", "sam.rivera@example.com", ["samr"]))
    insert_observation(db_conn, _obs("o1", "e2"))
    insert_claim(db_conn, _claim("c1", "e2"))

    result = merge_entities(db_conn, "e1", "e2")

    assert result["keep_name"] == "Sam Rivera"
    assert result["drop_name"] == "sam.rivera@example.com"
    assert result["observations_moved"] == 1
    assert result["claims_moved"] == 1

    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e2'").fetchone() is None

    keep = db_conn.execute("SELECT aliases FROM entities WHERE id = 'e1'").fetchone()
    aliases = json.loads(keep["aliases"])
    assert "sam.rivera@example.com" in aliases
    assert "samr" in aliases
    assert "srivera" in aliases


def test_merge_entities_dry_run(db_conn):
    _insert_entity_raw(db_conn, "e1", "Sam Rivera")
    _insert_entity_raw(db_conn, "e2", "Rivera, Sam")
    insert_observation(db_conn, _obs("o1", "e2"))

    result = merge_entities(db_conn, "e1", "e2", dry_run=True)

    assert result["observations_moved"] == 1
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e2'").fetchone() is not None
    row = db_conn.execute("SELECT sender_entity_id FROM observations WHERE id = 'o1'").fetchone()
    assert row["sender_entity_id"] == "e2"


def test_merge_entities_not_found(db_conn):
    upsert_entity(db_conn, _entity("e1", "Sam Rivera"))
    try:
        merge_entities(db_conn, "e1", "nonexistent")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_merge_preserves_earlier_first_seen(db_conn):
    db_conn.execute(
        "INSERT INTO entities"
        " (id, type, name, aliases, metadata,"
        "  first_seen, last_seen, decay_rate, is_owner)"
        " VALUES (?, 'person', ?, '[]', '{}', ?, ?, 0.02, 0)",
        ("e1", "Sam Rivera", "2025-01-15T00:00:00+00:00", "2025-06-01T00:00:00+00:00"),
    )
    db_conn.execute(
        "INSERT INTO entities"
        " (id, type, name, aliases, metadata,"
        "  first_seen, last_seen, decay_rate, is_owner)"
        " VALUES (?, 'person', ?, '[]', '{}', ?, ?, 0.02, 0)",
        ("e2", "Rivera, Sam", "2024-06-01T00:00:00+00:00", "2025-09-01T00:00:00+00:00"),
    )
    db_conn.commit()

    merge_entities(db_conn, "e1", "e2")

    row = db_conn.execute("SELECT first_seen, last_seen FROM entities WHERE id = 'e1'").fetchone()
    assert row["first_seen"] == "2024-06-01T00:00:00+00:00"
    assert row["last_seen"] == "2025-09-01T00:00:00+00:00"


# ── find_dedup_candidates ───────────────────────────────────


def test_find_dedup_candidates_normalized_names(db_conn):
    _insert_entity_raw(db_conn, "e1", "Sam Rivera")
    _insert_entity_raw(db_conn, "e2", "Rivera, Sam")
    insert_observation(db_conn, _obs("o1", "e1"))

    candidates = find_dedup_candidates(db_conn)
    assert len(candidates) == 1
    assert candidates[0]["keep"]["id"] == "e1"
    assert len(candidates[0]["drop"]) == 1


def test_find_dedup_candidates_no_duplicates(db_conn):
    upsert_entity(db_conn, _entity("e1", "Alice Tran"))
    upsert_entity(db_conn, _entity("e2", "Bob Marsh"))

    candidates = find_dedup_candidates(db_conn)
    assert len(candidates) == 0


def test_find_dedup_candidates_email_vs_name(db_conn):
    _insert_entity_raw(db_conn, "e1", "sam.rivera@example.com")
    _insert_entity_raw(db_conn, "e2", "Sam Rivera")

    candidates = find_dedup_candidates(db_conn)
    assert len(candidates) == 1


def test_find_dedup_candidates_skips_owner(db_conn):
    _insert_entity_raw(db_conn, "e1", "Sam Rivera", is_owner=1)
    _insert_entity_raw(db_conn, "e2", "Rivera, Sam")

    candidates = find_dedup_candidates(db_conn)
    assert len(candidates) == 0


# ── dedup_entities ───────────────────────────────────────────


def test_dedup_entities_merges_group(db_conn):
    _insert_entity_raw(db_conn, "e1", "Sam Rivera")
    _insert_entity_raw(db_conn, "e2", "Rivera, Sam")
    insert_observation(db_conn, _obs("o1", "e1"))
    insert_observation(db_conn, _obs("o2", "e2"))
    insert_observation(db_conn, _obs("o3", "e1"))

    result = dedup_entities(db_conn)

    assert result["groups"] == 1
    assert result["entities_merged"] == 1
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e2'").fetchone() is None
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e1'").fetchone() is not None


def test_dedup_entities_dry_run(db_conn):
    _insert_entity_raw(db_conn, "e1", "Sam Rivera")
    _insert_entity_raw(db_conn, "e2", "Rivera, Sam")

    result = dedup_entities(db_conn, dry_run=True)

    assert result["groups"] == 1
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e2'").fetchone() is not None


# ── prune_non_person_entities ────────────────────────────────


def test_prune_removes_bots(db_conn):
    upsert_entity(db_conn, _entity("e1", "Build Bot"))
    upsert_entity(db_conn, _entity("e2", "Alice Tran"))
    insert_claim(db_conn, _claim("c1", "e1"))
    insert_observation(db_conn, _obs("o1", "e1"))

    result = prune_non_person_entities(db_conn)

    assert result["pruned"] == 1
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e1'").fetchone() is None
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e2'").fetchone() is not None
    assert db_conn.execute("SELECT 1 FROM claims WHERE id = 'c1'").fetchone() is None

    row = db_conn.execute("SELECT sender_entity_id FROM observations WHERE id = 'o1'").fetchone()
    assert row["sender_entity_id"] is None


def test_prune_dry_run(db_conn):
    upsert_entity(db_conn, _entity("e1", "Deploy Bot"))

    result = prune_non_person_entities(db_conn, dry_run=True)

    assert result["pruned"] == 1
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e1'").fetchone() is not None


def test_prune_skips_owner(db_conn):
    upsert_entity(db_conn, _entity("e1", "System Bot"))
    db_conn.execute("UPDATE entities SET is_owner = 1 WHERE id = 'e1'")
    db_conn.commit()

    result = prune_non_person_entities(db_conn)
    assert result["pruned"] == 0


def test_prune_no_matches(db_conn):
    upsert_entity(db_conn, _entity("e1", "Alice Tran"))

    result = prune_non_person_entities(db_conn)
    assert result["pruned"] == 0


# ── reprocess_observations ───────────────────────────────────


def test_reprocess_all(db_conn):
    insert_observation(db_conn, _obs("o1", None, ts=1000.0, processed=1))
    insert_observation(db_conn, _obs("o2", None, ts=2000.0, processed=1))
    insert_observation(db_conn, _obs("o3", None, ts=3000.0, processed=0))

    result = reprocess_observations(db_conn)

    assert result["reset_count"] == 2
    rows = db_conn.execute("SELECT COUNT(*) AS c FROM observations WHERE processed = 0").fetchone()
    assert rows["c"] == 3


def test_reprocess_since(db_conn):
    insert_observation(db_conn, _obs("o1", None, ts=1000.0, processed=1))
    insert_observation(db_conn, _obs("o2", None, ts=2000.0, processed=1))

    result = reprocess_observations(db_conn, since="1970-01-01T00:33:20+00:00")

    assert result["reset_count"] == 1
    row = db_conn.execute("SELECT processed FROM observations WHERE id = 'o1'").fetchone()
    assert row["processed"] == 1

    row = db_conn.execute("SELECT processed FROM observations WHERE id = 'o2'").fetchone()
    assert row["processed"] == 0


def test_reprocess_by_source(db_conn):
    insert_observation(db_conn, _obs("o1", None, source="slack_export", ts=1000.0, processed=1))
    insert_observation(
        db_conn, _obs("o2", None, source="outlook_mcp_email", ts=2000.0, processed=1)
    )

    result = reprocess_observations(db_conn, source="slack_export")

    assert result["reset_count"] == 1
    row = db_conn.execute("SELECT processed FROM observations WHERE id = 'o1'").fetchone()
    assert row["processed"] == 0

    row = db_conn.execute("SELECT processed FROM observations WHERE id = 'o2'").fetchone()
    assert row["processed"] == 1


def test_reprocess_dry_run(db_conn):
    insert_observation(db_conn, _obs("o1", None, ts=1000.0, processed=1))

    result = reprocess_observations(db_conn, dry_run=True)

    assert result["reset_count"] == 1
    row = db_conn.execute("SELECT processed FROM observations WHERE id = 'o1'").fetchone()
    assert row["processed"] == 1


# ── CLI integration ─────────────────────────────────────────


def test_cli_entity_merge(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    upsert_entity(conn, _entity("e1aabbcc", "Alice Tran"))
    upsert_entity(conn, _entity("e2ddeeff", "alice.tran"))
    insert_observation(conn, _obs("o1", "e2ddeeff"))
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "merge", "e1aabbcc", "e2ddeeff", "--home", str(home)])
    assert result.exit_code == 0
    assert "Merged" in result.output
    assert "alice.tran" in result.output


def test_cli_entity_merge_dry_run(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    upsert_entity(conn, _entity("e1aabbcc", "Alice Tran"))
    upsert_entity(conn, _entity("e2ddeeff", "alice.tran"))
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(
        app, ["entity", "merge", "e1aabbcc", "e2ddeeff", "--dry-run", "--home", str(home)]
    )
    assert result.exit_code == 0
    assert "Would merge" in result.output


def test_cli_entity_merge_ambiguous_prefix(db_path):
    """Regression: ambiguous prefix should error, not silently pick one."""
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    upsert_entity(conn, _entity("e1aabbcc", "Alice Tran"))
    upsert_entity(conn, _entity("e1aabbdd", "Alice Chen"))
    upsert_entity(conn, _entity("e2ddeeff", "Bob Marsh"))
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "merge", "e1aa", "e2ddeeff", "--home", str(home)])
    assert result.exit_code == 1
    assert "Ambiguous" in result.output


def test_cli_entity_dedup(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    _insert_entity_raw(conn, "e1aabbcc", "Sam Rivera")
    _insert_entity_raw(conn, "e2ddeeff", "Rivera, Sam")
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "dedup", "--dry-run", "--home", str(home)])
    assert result.exit_code == 0
    assert "1 group" in result.output


def test_cli_entity_prune(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    upsert_entity(conn, _entity("e1aabbcc", "Build Bot"))
    upsert_entity(conn, _entity("e2ddeeff", "Alice Tran"))
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(
        app, ["entity", "prune", "--non-person", "--dry-run", "--home", str(home)]
    )
    assert result.exit_code == 0
    assert "1 non-person" in result.output
    assert "Build Bot" in result.output


def test_cli_entity_prune_requires_filter(db_path):
    from typer.testing import CliRunner

    from patina.cli import app

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "prune", "--home", str(home)])
    assert result.exit_code == 1
    assert "Specify a filter" in result.output


def test_cli_entity_list(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    upsert_entity(conn, _entity("e1aabbcc", "Alice Tran"))
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "list", "--home", str(home)])
    assert result.exit_code == 0
    assert "Alice Tran" in result.output


def test_cli_extract_reprocess_dry_run(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    insert_observation(conn, _obs("o1", None, ts=1000.0, processed=1))
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["extract", "--reprocess", "--dry-run", "--home", str(home)])
    assert result.exit_code == 0
    assert "Would reset 1" in result.output


# ── cascade delete on prune ────────────────────────────────


def test_prune_cascades_claims_and_relationships(db_conn):
    upsert_entity(db_conn, _entity("e1", "Build Bot"))
    upsert_entity(db_conn, _entity("e2", "Alice Tran"))
    insert_claim(db_conn, _claim("c1", "e1"))
    insert_claim(db_conn, _claim("c2", "e2"))
    upsert_relationship(db_conn, _rel("r1", "e1", "e2"))
    upsert_relationship(db_conn, _rel("r2", "e2", "e1"))
    upsert_relationship(db_conn, _rel("r3", "e2", "e2"))

    prune_non_person_entities(db_conn)

    assert db_conn.execute("SELECT 1 FROM claims WHERE id = 'c1'").fetchone() is None
    assert db_conn.execute("SELECT 1 FROM claims WHERE id = 'c2'").fetchone() is not None
    assert db_conn.execute("SELECT 1 FROM relationships WHERE id = 'r1'").fetchone() is None
    assert db_conn.execute("SELECT 1 FROM relationships WHERE id = 'r2'").fetchone() is None
    assert db_conn.execute("SELECT 1 FROM relationships WHERE id = 'r3'").fetchone() is not None


def test_prune_dry_run_reports_dependent_counts(db_conn):
    upsert_entity(db_conn, _entity("e1", "Build Bot"))
    upsert_entity(db_conn, _entity("e2", "Alice Tran"))
    insert_claim(db_conn, _claim("c1", "e1"))
    insert_claim(db_conn, _claim("c2", "e1", predicate="team", obj="infra"))
    upsert_relationship(db_conn, _rel("r1", "e1", "e2"))

    result = prune_non_person_entities(db_conn, dry_run=True)

    assert result["pruned"] == 1
    assert result["claims_removed"] == 2
    assert result["relationships_removed"] == 1
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e1'").fetchone() is not None


# ── cascade on dedup / merge ───────────────────────────────


def test_dedup_rewires_claims_and_relationships(db_conn):
    _insert_entity_raw(db_conn, "e1", "Sam Rivera")
    _insert_entity_raw(db_conn, "e2", "Rivera, Sam")
    upsert_entity(db_conn, _entity("e3", "Bob Marsh"))
    insert_observation(db_conn, _obs("o1", "e1"))
    insert_claim(db_conn, _claim("c1", "e2"))
    upsert_relationship(db_conn, _rel("r1", "e2", "e3"))

    dedup_entities(db_conn)

    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e2'").fetchone() is None
    claim = db_conn.execute("SELECT subject_id FROM claims WHERE id = 'c1'").fetchone()
    assert claim["subject_id"] == "e1"
    rel = db_conn.execute(
        "SELECT subject_id, object_id FROM relationships WHERE id = 'r1'"
    ).fetchone()
    assert rel["subject_id"] == "e1"
    assert rel["object_id"] == "e3"


def test_merge_rewires_both_tables(db_conn):
    upsert_entity(db_conn, _entity("e1", "Alice Tran"))
    upsert_entity(db_conn, _entity("e2", "alice.tran"))
    insert_claim(db_conn, _claim("c1", "e2"))
    upsert_relationship(db_conn, _rel("r1", "e2", "e1"))
    upsert_relationship(db_conn, _rel("r2", "e1", "e2"))

    merge_entities(db_conn, "e1", "e2")

    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e2'").fetchone() is None
    claim = db_conn.execute("SELECT subject_id FROM claims WHERE id = 'c1'").fetchone()
    assert claim["subject_id"] == "e1"

    from patina.store import find_dangling_references

    assert find_dangling_references(db_conn) == {}


# ── find_dangling_references ───────────────────────────────


def test_find_dangling_references_clean(db_conn):
    from patina.store import find_dangling_references

    upsert_entity(db_conn, _entity("e1", "Alice Tran"))
    insert_claim(db_conn, _claim("c1", "e1"))

    assert find_dangling_references(db_conn) == {}


def test_find_dangling_references_detects_orphans(db_conn):
    from patina.store import find_dangling_references

    upsert_entity(db_conn, _entity("e1", "Alice Tran"))
    insert_claim(db_conn, _claim("c1", "e1"))
    upsert_relationship(db_conn, _rel("r1", "e1", "e1"))

    db_conn.execute("PRAGMA foreign_keys=OFF")
    db_conn.execute(
        "INSERT INTO claims (id, subject_id, predicate, object, confidence,"
        " first_asserted, last_confirmed, decay_rate)"
        " VALUES ('c_orphan', 'gone', 'role', 'engineer', 0.5,"
        " '2025-01-01', '2025-01-01', 0.02)"
    )
    db_conn.execute(
        "INSERT INTO relationships (id, subject_id, predicate, object_id,"
        " confidence, first_seen, last_confirmed)"
        " VALUES ('r_orphan', 'gone', 'works_with', 'e1', 0.5,"
        " '2025-01-01', '2025-01-01')"
    )
    db_conn.commit()
    db_conn.execute("PRAGMA foreign_keys=ON")

    result = find_dangling_references(db_conn)
    assert result["claims"] == 1
    assert result["relationships"] == 1


# ── delete_dangling_references ─────────────────────────────


def test_delete_dangling_references(db_conn):
    from patina.store import delete_dangling_references, find_dangling_references

    upsert_entity(db_conn, _entity("e1", "Alice Tran"))
    insert_claim(db_conn, _claim("c1", "e1"))

    db_conn.execute("PRAGMA foreign_keys=OFF")
    db_conn.execute(
        "INSERT INTO claims (id, subject_id, predicate, object, confidence,"
        " first_asserted, last_confirmed, decay_rate)"
        " VALUES ('c_orphan', 'gone', 'role', 'engineer', 0.5,"
        " '2025-01-01', '2025-01-01', 0.02)"
    )
    db_conn.execute(
        "INSERT INTO relationships (id, subject_id, predicate, object_id,"
        " confidence, first_seen, last_confirmed)"
        " VALUES ('r_orphan', 'gone', 'works_with', 'e1', 0.5,"
        " '2025-01-01', '2025-01-01')"
    )
    db_conn.commit()
    db_conn.execute("PRAGMA foreign_keys=ON")

    result = delete_dangling_references(db_conn)
    assert result["claims"] == 1
    assert result["relationships"] == 1

    assert find_dangling_references(db_conn) == {}
    assert db_conn.execute("SELECT 1 FROM claims WHERE id = 'c1'").fetchone() is not None


# ── CLI: patina doctor ─────────────────────────────────────


def test_cli_doctor_clean(db_path):
    from typer.testing import CliRunner

    from patina.cli import app

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["doctor", "--home", str(home)])
    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_cli_doctor_warns_on_dangling(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    upsert_entity(conn, _entity("e1", "Alice Tran"))
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO claims (id, subject_id, predicate, object, confidence,"
        " first_asserted, last_confirmed, decay_rate)"
        " VALUES ('c_orphan', 'gone', 'role', 'engineer', 0.5,"
        " '2025-01-01', '2025-01-01', 0.02)"
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["doctor", "--home", str(home)])
    assert result.exit_code == 0
    assert "WARN dangling claims: 1 claim(s) reference missing entities" in result.output


# ── CLI: patina entity cleanup ─────────────────────────────


def test_cli_entity_cleanup_noop(db_path):
    from typer.testing import CliRunner

    from patina.cli import app

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "cleanup", "--home", str(home)])
    assert result.exit_code == 0
    assert "No dangling references found." in result.output


def test_cli_entity_cleanup_removes(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    upsert_entity(conn, _entity("e1", "Alice Tran"))
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO claims (id, subject_id, predicate, object, confidence,"
        " first_asserted, last_confirmed, decay_rate)"
        " VALUES ('c_orphan', 'gone', 'role', 'engineer', 0.5,"
        " '2025-01-01', '2025-01-01', 0.02)"
    )
    conn.execute(
        "INSERT INTO relationships (id, subject_id, predicate, object_id,"
        " confidence, first_seen, last_confirmed)"
        " VALUES ('r_orphan', 'gone', 'works_with', 'e1', 0.5,"
        " '2025-01-01', '2025-01-01')"
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "cleanup", "--home", str(home)])
    assert result.exit_code == 0
    assert "Removed 1 dangling claim(s) and 1 dangling relationship(s)." in result.output
