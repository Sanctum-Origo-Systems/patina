from __future__ import annotations

import json

from patina.graph import (
    insert_claim,
    insert_observation,
    upsert_entity,
    upsert_relationship,
)
from patina.maintenance import (
    _collect_slack_ids,
    _is_junk_sender_name,
    backup_store,
    dedup_entities,
    find_dedup_candidates,
    find_id_named_entities,
    fix_junk_senders,
    is_non_person,
    is_organization,
    is_plausible_person_name,
    merge_entities,
    prune_non_person_entities,
    prune_slack_link_entities,
    reprocess_observations,
    retype_organization_entities,
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


def test_is_non_person_legacy_dn():
    dn = "/O=EXCHANGELABS/OU=EXCHANGE ADMINISTRATIVE GROUP/CN=RECIPIENTS/CN=abc123"
    assert is_non_person(dn) is True


def test_is_non_person_legacy_dn_lowercase():
    assert is_non_person("/o=EXCHANGELABS/ou=GROUP/cn=abc") is True


def test_is_non_person_team_suffix():
    assert is_non_person("Engineering Team") is True
    assert is_non_person("IT Support team") is True


def test_is_non_person_list_suffix():
    assert is_non_person("All-Hands List") is True
    assert is_non_person("Distribution list") is True


def test_is_non_person_group_suffix():
    assert is_non_person("Marketing Group") is True
    assert is_non_person("Finance group") is True


def test_is_non_person_donotreply():
    assert is_non_person("donotreply@example.com") is True
    assert is_non_person("do-not-reply@example.com") is True
    assert is_non_person("do_not_reply@example.com") is True


# ── is_organization ─────────────────────────────────────────


def test_is_organization_field_research():
    assert is_organization("Acme Field Research") is True


def test_is_organization_events():
    assert is_organization("Acme Events") is True


def test_is_organization_newsletter():
    assert is_organization("Weekly Newsletter") is True


def test_is_organization_role_title():
    assert is_organization("Acme Engagement Manager") is True


def test_is_organization_person_name():
    assert is_organization("Dana Brook") is False
    assert is_organization("Sam Rivera") is False
    assert is_organization("Alice Chen") is False


def test_is_organization_single_word():
    assert is_organization("Newsletter") is False
    assert is_organization("Research") is False


def test_is_organization_empty():
    assert is_organization("") is False


def test_is_organization_various_suffixes():
    assert is_organization("Acme Services") is True
    assert is_organization("Regional Office") is True
    assert is_organization("Product Solutions") is True
    assert is_organization("Global Consulting") is True
    assert is_organization("Acme Labs") is True
    assert is_organization("Corporate Communications") is True


def test_is_organization_role_nouns():
    assert is_organization("Sales Director") is True
    assert is_organization("VP Operations Coordinator") is True
    assert is_organization("Acme Specialist") is True


# ── is_plausible_person_name ────────────────────────────────


def test_plausible_accepts_real_names():
    assert is_plausible_person_name("Sam Rivera") is True
    assert is_plausible_person_name("Alice Chen") is True


def test_plausible_rejects_phrases():
    assert is_plausible_person_name("Orion and Project Lumen integration") is False


def test_plausible_rejects_long_phrases():
    assert is_plausible_person_name("Head of Engineering at Acme Corp") is False


def test_plausible_rejects_grammar_words():
    assert is_plausible_person_name("Sam and Alice") is False


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


def test_find_dedup_candidates_shared_alias(db_conn):
    _insert_entity_raw(db_conn, "e1", "Sam Rivera", aliases=["slack:U001"])
    _insert_entity_raw(db_conn, "e2", "Rivera, Sam", aliases=["slack:U001"])
    insert_observation(db_conn, _obs("o1", "e1"))

    result = find_dedup_candidates(db_conn)
    candidates = result["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["keep"]["id"] == "e1"
    assert len(candidates[0]["drop"]) == 1
    assert candidates[0]["match_identifier"] == "slack:u001"


def test_find_dedup_candidates_no_duplicates(db_conn):
    upsert_entity(db_conn, _entity("e1", "Alice Tran"))
    upsert_entity(db_conn, _entity("e2", "Bob Marsh"))

    result = find_dedup_candidates(db_conn)
    assert len(result["candidates"]) == 0


def test_find_dedup_candidates_rejects_unrelated_handles(db_conn):
    """Two handles with no shared hard identifier must not be merged."""
    _insert_entity_raw(db_conn, "e1", "dkim")
    _insert_entity_raw(db_conn, "e2", "dkay")

    result = find_dedup_candidates(db_conn)
    assert len(result["candidates"]) == 0


def test_find_dedup_candidates_email_vs_name(db_conn):
    _insert_entity_raw(db_conn, "e1", "sam.rivera@example.com")
    _insert_entity_raw(db_conn, "e2", "Sam Rivera", aliases=["sam.rivera@example.com"])

    result = find_dedup_candidates(db_conn)
    assert len(result["candidates"]) == 1


def test_find_dedup_candidates_skips_owner(db_conn):
    _insert_entity_raw(db_conn, "e1", "Sam Rivera", is_owner=1)
    _insert_entity_raw(db_conn, "e2", "Rivera, Sam")

    result = find_dedup_candidates(db_conn)
    assert len(result["candidates"]) == 0


def test_find_dedup_conflicting_slack_ids_rejected(db_conn):
    """Entities with different Slack IDs must not merge even through a shared handle alias."""
    _insert_entity_raw(db_conn, "e1", "user_a", aliases=["U0AAAA111"])
    _insert_entity_raw(db_conn, "e2", "user_b", aliases=["U0BBBB222", "user_a"])

    result = find_dedup_candidates(db_conn)
    assert len(result["candidates"]) == 0


def test_find_dedup_handle_alias_alone_insufficient(db_conn):
    """A handle alias on a foreign entity does not trigger a merge without a hard identifier."""
    _insert_entity_raw(db_conn, "e1", "dkim")
    _insert_entity_raw(db_conn, "e2", "Dana Brook", aliases=["dkim"])

    result = find_dedup_candidates(db_conn)
    assert len(result["candidates"]) == 0


def test_find_dedup_conflicting_emails_rejected(db_conn):
    """Entities sharing a name but holding different emails must not merge."""
    _insert_entity_raw(db_conn, "e1", "Sam Rivera", aliases=["sam@alpha.com"])
    _insert_entity_raw(db_conn, "e2", "Sam Rivera", aliases=["sam@beta.com"])

    result = find_dedup_candidates(db_conn)
    assert len(result["candidates"]) == 0


def test_find_dedup_transitive_conflict_blocked(db_conn):
    """Transitive chaining through soft matches must not link entities with conflicting IDs."""
    _insert_entity_raw(db_conn, "e1", "Sam Rivera", aliases=["U0AAAA111"])
    _insert_entity_raw(db_conn, "e2", "Sam Rivera")
    _insert_entity_raw(db_conn, "e3", "Sam Rivera", aliases=["U0CCCC333"])

    result = find_dedup_candidates(db_conn)
    for c in result["candidates"]:
        ids = {c["keep"]["id"]} | {d["id"] for d in c["drop"]}
        assert not ("e1" in ids and "e3" in ids), (
            "Conflicting Slack IDs should not be in same group"
        )


def test_find_dedup_contaminated_bare_id_needs_review(db_conn):
    """Entity with contaminated bare Slack ID is excluded and flagged as needs review."""
    _insert_entity_raw(db_conn, "e1", "user_a", aliases=["slack:U0AAAA111", "U0BBBB222"])
    _insert_entity_raw(db_conn, "e2", "U0BBBB222", aliases=["U0BBBB222"])

    result = find_dedup_candidates(db_conn)

    assert len(result["candidates"]) == 0
    assert len(result["needs_review"]) == 1
    assert result["needs_review"][0]["name"] == "user_a"
    assert result["needs_review"][0]["reason"] == "multiple Slack IDs"


def test_find_dedup_canonical_handle_over_slack_id(db_conn):
    """Handle + Slack ID merge keeps the handle as canonical."""
    _insert_entity_raw(db_conn, "e1", "user_b", aliases=["slack:U0CCCC333"])
    _insert_entity_raw(db_conn, "e2", "U0CCCC333", aliases=["slack:U0CCCC333"])

    result = find_dedup_candidates(db_conn)
    candidates = result["candidates"]

    assert len(candidates) == 1
    assert candidates[0]["keep"]["name"] == "user_b"


def test_find_dedup_canonical_full_name_over_handle_and_id(db_conn):
    """Full name + handle + ID merge keeps the full name as canonical."""
    _insert_entity_raw(db_conn, "e1", "Aria Johansson", aliases=["slack:U0DDD55555D444"])
    _insert_entity_raw(db_conn, "e2", "ajohansson", aliases=["slack:U0DDD55555D444"])
    _insert_entity_raw(db_conn, "e3", "U0DDD55555D444", aliases=["slack:U0DDD55555D444"])

    result = find_dedup_candidates(db_conn)
    candidates = result["candidates"]

    assert len(candidates) == 1
    assert candidates[0]["keep"]["name"] == "Aria Johansson"


def test_find_dedup_handle_alias_merges_sender(db_conn):
    """Full-name entity with handle alias merges with sender handle entity."""
    _insert_entity_raw(db_conn, "e1", "Dana Brook", aliases=["dbrook"])
    _insert_entity_raw(db_conn, "e2", "dbrook", aliases=["slack:U0DDD55555"])
    insert_observation(db_conn, _obs("o1", "e2"))

    result = find_dedup_candidates(db_conn)
    candidates = result["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["keep"]["name"] == "Dana Brook"


def test_find_dedup_foreign_handle_exemption_requires_full_name(db_conn):
    """Handle-named entity holding another person's handle must not merge through it."""
    _insert_entity_raw(db_conn, "ec", "user_c", aliases=["slack:U0CCCC333C", "user_d"])
    _insert_entity_raw(db_conn, "ed", "user_d", aliases=["slack:U0DDD55555D444D"])
    _insert_entity_raw(db_conn, "edb", "Dana Brook", aliases=["user_d", "Brook, Dana"])
    insert_observation(db_conn, _obs("o1", "ec"))
    insert_observation(db_conn, _obs("o2", "ed"))

    result = find_dedup_candidates(db_conn)
    candidates = result["candidates"]

    all_merged_ids = set()
    for c in candidates:
        all_merged_ids.add(c["keep"]["id"])
        for d in c["drop"]:
            all_merged_ids.add(d["id"])

    assert "ec" not in all_merged_ids, "user_c must not be in any merge group"
    assert "ed" in all_merged_ids and "edb" in all_merged_ids, "dbrook and Dana Brook should merge"

    for c in candidates:
        all_ids = {c["keep"]["id"]} | {d["id"] for d in c["drop"]}
        if "ed" in all_ids:
            assert c["keep"]["name"] == "Dana Brook"


def test_find_dedup_handle_alias_no_id_mismatch_needs_review(db_conn):
    """Handle alias merge bypasses Slack ID guard when target has no ID (#391)."""
    _insert_entity_raw(db_conn, "e1", "Dana Brook", aliases=["dbrook2", "Brook, Dana"])
    _insert_entity_raw(db_conn, "e2", "dbrook2", aliases=["U0EXAMPLE9"])
    insert_observation(db_conn, _obs("o1", "e1"))
    insert_observation(db_conn, _obs("o2", "e2"))

    result = find_dedup_candidates(db_conn)

    for c in result["candidates"]:
        all_ids = {c["keep"]["id"]} | {d["id"] for d in c["drop"]}
        assert not ("e1" in all_ids and "e2" in all_ids), "dbrook2 -> Dana Brook must not merge"

    review_items = [r for r in result["needs_review"] if r["id"] in {"e1", "e2"}]
    assert len(review_items) >= 1
    assert any(r["reason"] == "handle-name mismatch" for r in review_items)


def test_find_dedup_handle_alias_with_own_slack_id_merges(db_conn):
    """Full-name entity with matching handle alias and its own Slack ID still merges (#391)."""
    _insert_entity_raw(db_conn, "e1", "Dana Brook", aliases=["dbrook", "slack:U0DBID"])
    _insert_entity_raw(db_conn, "e2", "dbrook", aliases=["slack:U0DBID"])
    insert_observation(db_conn, _obs("o1", "e2"))

    result = find_dedup_candidates(db_conn)
    candidates = result["candidates"]
    assert len(candidates) == 1
    assert candidates[0]["keep"]["name"] == "Dana Brook"


def test_find_dedup_ambiguous_handle_alias_needs_review(db_conn):
    """Handle held as alias by two full-name entities goes to needs review."""
    _insert_entity_raw(db_conn, "e1", "Alice Tran", aliases=["jfox"])
    _insert_entity_raw(db_conn, "e2", "Beth Marsh", aliases=["jfox"])
    _insert_entity_raw(db_conn, "e3", "jfox")
    insert_observation(db_conn, _obs("o1", "e3"))

    result = find_dedup_candidates(db_conn)

    review_names = {r["name"] for r in result["needs_review"]}
    assert "jfox" in review_names
    review_by_name = {r["name"]: r for r in result["needs_review"]}
    assert review_by_name["jfox"]["reason"] == "ambiguous handle alias"

    for c in result["candidates"]:
        all_ids = {c["keep"]["id"]} | {d["id"] for d in c["drop"]}
        assert "e3" not in all_ids


# ── dedup_entities ───────────────────────────────────────────


def test_dedup_entities_merges_group(db_conn):
    _insert_entity_raw(db_conn, "e1", "Sam Rivera", aliases=["slack:U001"])
    _insert_entity_raw(db_conn, "e2", "Rivera, Sam", aliases=["slack:U001"])
    insert_observation(db_conn, _obs("o1", "e1"))
    insert_observation(db_conn, _obs("o2", "e2"))
    insert_observation(db_conn, _obs("o3", "e1"))

    result = dedup_entities(db_conn)

    assert result["groups"] == 1
    assert result["entities_merged"] == 1
    assert result["merges"][0]["match_identifier"] == "slack:u001"
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e2'").fetchone() is None
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e1'").fetchone() is not None


def test_dedup_entities_dry_run(db_conn):
    _insert_entity_raw(db_conn, "e1", "Sam Rivera", aliases=["slack:U001"])
    _insert_entity_raw(db_conn, "e2", "Rivera, Sam", aliases=["slack:U001"])

    result = dedup_entities(db_conn, dry_run=True)

    assert result["groups"] == 1
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e2'").fetchone() is not None


def test_dedup_contaminated_appears_in_result(db_conn):
    """dedup_entities reports contaminated entities in needs_review."""
    _insert_entity_raw(db_conn, "e1", "user_a", aliases=["slack:U0AAAA111", "U0BBBB222"])
    _insert_entity_raw(db_conn, "e2", "U0BBBB222", aliases=["U0BBBB222"])

    result = dedup_entities(db_conn, dry_run=True)

    assert result["entities_merged"] == 0
    assert len(result["needs_review"]) == 1
    assert result["needs_review"][0]["name"] == "user_a"
    assert result["needs_review"][0]["reason"] == "multiple Slack IDs"


def test_dedup_canonical_prefers_full_name(db_conn):
    """Full-name + handle merge keeps the full name as canonical."""
    _insert_entity_raw(db_conn, "e1", "dkim", aliases=["slack:U007"])
    _insert_entity_raw(db_conn, "e2", "Dana Brook", aliases=["slack:U007"])
    insert_observation(db_conn, _obs("o1", "e1"))
    insert_observation(db_conn, _obs("o2", "e1"))
    insert_observation(db_conn, _obs("o3", "e1"))

    result = dedup_entities(db_conn)

    assert result["entities_merged"] == 1
    assert result["merges"][0]["keep_name"] == "Dana Brook"
    assert result["merges"][0]["drop_name"] == "dkim"
    keep = db_conn.execute("SELECT name, aliases FROM entities WHERE id = 'e2'").fetchone()
    assert keep["name"] == "Dana Brook"
    aliases = json.loads(keep["aliases"])
    assert "dkim" in aliases


def test_dedup_handle_alias_merge_keeps_full_name(db_conn):
    """Handle alias on full-name entity merges with sender, keeping full name."""
    _insert_entity_raw(db_conn, "e1", "Dana Brook", aliases=["dbrook"])
    _insert_entity_raw(db_conn, "e2", "dbrook", aliases=["slack:U0DDD55555"])
    insert_observation(db_conn, _obs("o1", "e2"))

    result = dedup_entities(db_conn)

    assert result["entities_merged"] == 1
    assert result["merges"][0]["keep_name"] == "Dana Brook"
    assert result["merges"][0]["drop_name"] == "dbrook"
    keep = db_conn.execute("SELECT name, aliases FROM entities WHERE id = 'e1'").fetchone()
    assert keep["name"] == "Dana Brook"
    aliases = json.loads(keep["aliases"])
    assert "dbrook" in aliases


def test_dedup_skips_alias_collision(db_conn):
    _insert_entity_raw(db_conn, "e1", "Sam Rivera", aliases=["slack:U001"])
    _insert_entity_raw(db_conn, "e2", "Rivera, Sam", aliases=["slack:U001"])
    _insert_entity_raw(db_conn, "e3", "Quinn Farrow", aliases=["sam.rivera@work.com"])
    insert_observation(db_conn, _obs("o1", "e1"))

    result = dedup_entities(db_conn)

    assert len(result["skipped"]) >= 1
    skipped_drops = {s["drop_name"] for s in result["skipped"]}
    assert "Rivera, Sam" in skipped_drops
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e3'").fetchone() is not None


def test_dedup_reports_skipped_in_result(db_conn):
    _insert_entity_raw(db_conn, "e1", "Sam Rivera", aliases=["slack:U001"])
    _insert_entity_raw(db_conn, "e2", "Rivera, Sam", aliases=["slack:U001"])
    _insert_entity_raw(db_conn, "e3", "Quinn Farrow", aliases=["sam.rivera@work.com"])
    insert_observation(db_conn, _obs("o1", "e1"))

    result = dedup_entities(db_conn, dry_run=True)

    assert "skipped" in result
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["reason"] == "alias collision"
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e2'").fetchone() is not None


def test_dedup_shared_slack_id_overrides_alias_collision(db_conn):
    _insert_entity_raw(db_conn, "e1", "user_a", aliases=["slack:U0AAAA1111"])
    _insert_entity_raw(db_conn, "e2", "U0AAAA1111", aliases=["slack:U0AAAA1111"])
    _insert_entity_raw(db_conn, "e3", "Quinn Farrow", aliases=["u0aaaa1111@work.com"])
    insert_observation(db_conn, _obs("o1", "e1"))

    result = dedup_entities(db_conn)

    assert result["entities_merged"] == 1
    assert len(result["skipped"]) == 0
    merged_names = {m["drop_name"] for m in result["merges"]}
    assert "U0AAAA1111" in merged_names
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e1'").fetchone() is not None


def test_dedup_shared_slack_id_extra_email_goes_to_review(db_conn):
    _insert_entity_raw(
        db_conn,
        "e1",
        "user_a",
        aliases=["slack:U0AAAA1111"],
    )
    _insert_entity_raw(
        db_conn,
        "e2",
        "U0AAAA1111",
        aliases=["slack:U0AAAA1111", "bob@elsewhere.com"],
    )
    _insert_entity_raw(db_conn, "e3", "Quinn Farrow", aliases=["u0aaaa1111@work.com"])
    insert_observation(db_conn, _obs("o1", "e1"))

    result = dedup_entities(db_conn)

    assert result["entities_merged"] == 0
    assert len(result["skipped"]) == 0
    review_names = {r["name"] for r in result["needs_review"]}
    assert "U0AAAA1111" in review_names


def test_dedup_three_entity_shared_slack_id_group(db_conn):
    """3-entity group: full name ← handle ← bare Slack ID.

    The handle and bare-ID drops share a Slack ID that the keep (full name)
    does not have.  Pre-merging the drops first removes the alias collision
    so all three collapse into one entity.
    """
    _insert_entity_raw(db_conn, "e1", "Dana Brook", aliases=["dbrook", "Brook, Dana"])
    _insert_entity_raw(
        db_conn,
        "e2",
        "dbrook",
        aliases=["dbrook", "slack:U0AAAA1111", "U0AAAA1111"],
    )
    _insert_entity_raw(db_conn, "e3", "U0AAAA1111", aliases=["U0AAAA1111"])
    insert_observation(db_conn, _obs("o1", "e2"))
    insert_observation(db_conn, _obs("o2", "e3", ts=1001.0))
    insert_claim(db_conn, _claim("c1", "e3"))

    result = dedup_entities(db_conn)

    assert result["entities_merged"] == 2
    assert len(result["skipped"]) == 0

    keep = db_conn.execute("SELECT * FROM entities WHERE id = 'e1'").fetchone()
    assert keep is not None
    aliases = json.loads(keep["aliases"])
    assert "dbrook" in aliases
    assert "slack:U0AAAA1111" in aliases or "U0AAAA1111" in aliases

    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e2'").fetchone() is None
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e3'").fetchone() is None

    obs1 = db_conn.execute("SELECT sender_entity_id FROM observations WHERE id = 'o1'").fetchone()
    assert obs1["sender_entity_id"] == "e1"
    obs2 = db_conn.execute("SELECT sender_entity_id FROM observations WHERE id = 'o2'").fetchone()
    assert obs2["sender_entity_id"] == "e1"

    claim = db_conn.execute("SELECT subject_id FROM claims WHERE id = 'c1'").fetchone()
    assert claim["subject_id"] == "e1"


def test_dedup_three_entity_dry_run_matches_confirm(db_conn):
    """Dry-run merge list must equal --confirm merge list (#428)."""
    _insert_entity_raw(db_conn, "e1", "Dana Brook", aliases=["dbrook", "Brook, Dana"])
    _insert_entity_raw(
        db_conn,
        "e2",
        "dbrook",
        aliases=["dbrook", "slack:U0AAAA1111", "U0AAAA1111"],
    )
    _insert_entity_raw(db_conn, "e3", "U0AAAA1111", aliases=["U0AAAA1111"])
    insert_observation(db_conn, _obs("o1", "e2"))
    insert_observation(db_conn, _obs("o2", "e3", ts=1001.0))
    insert_claim(db_conn, _claim("c1", "e3"))

    result = dedup_entities(db_conn, dry_run=True)

    assert result["entities_merged"] == 2
    assert len(result["skipped"]) == 0

    merge_pairs = [(m["keep_name"], m["drop_name"]) for m in result["merges"]]
    assert ("dbrook", "U0AAAA1111") in merge_pairs
    assert ("Dana Brook", "dbrook") in merge_pairs

    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e1'").fetchone() is not None
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e2'").fetchone() is not None
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e3'").fetchone() is not None


def test_dedup_unrelated_slack_collision_skips_both_modes(db_conn):
    """2-entity group whose drop holds an ID that an unrelated entity also holds (#428).

    e1 and e2 share slack:U0AAAA1111 → grouped.
    e3 has a different Slack ID (U0BBBB2222) so it stays out of the group,
    but e3 holds e2's email alias → collision blocks the merge in both modes.
    """
    _insert_entity_raw(db_conn, "e1", "Sam Rivera", aliases=["slack:U0AAAA1111"])
    _insert_entity_raw(
        db_conn,
        "e2",
        "Rivera, Sam",
        aliases=["slack:U0AAAA1111", "sam.rivera@work.com"],
    )
    _insert_entity_raw(
        db_conn,
        "e3",
        "Quinn Farrow",
        aliases=["sam.rivera@work.com", "slack:U0BBBB2222"],
    )
    insert_observation(db_conn, _obs("o1", "e1"))

    dry = dedup_entities(db_conn, dry_run=True)
    assert dry["entities_merged"] == 0
    assert len(dry["skipped"]) > 0 or len(dry["needs_review"]) > 0

    live = dedup_entities(db_conn)
    assert live["entities_merged"] == 0
    assert len(live["skipped"]) > 0 or len(live["needs_review"]) > 0


def test_dedup_multiple_slack_ids_goes_to_review(db_conn):
    _insert_entity_raw(
        db_conn,
        "e1",
        "user_a",
        aliases=["slack:U0AAAA1111", "slack:U0BBBB2222"],
    )

    result = dedup_entities(db_conn)

    review_ids = {r["id"] for r in result["needs_review"]}
    assert "e1" in review_ids
    review_reasons = {r["reason"] for r in result["needs_review"] if r["id"] == "e1"}
    assert "multiple Slack IDs" in review_reasons


# ── prune_non_person_entities ────────────────────────────────


def test_prune_removes_bots(db_conn):
    upsert_entity(db_conn, _entity("e1", "Build Bot"))
    upsert_entity(db_conn, _entity("e2", "Alice Tran"))
    insert_claim(db_conn, _claim("c1", "e1"))

    result = prune_non_person_entities(db_conn)

    assert result["pruned"] == 1
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e1'").fetchone() is None
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e2'").fetchone() is not None
    assert db_conn.execute("SELECT 1 FROM claims WHERE id = 'c1'").fetchone() is None


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


def test_prune_catches_phrase_entities(db_conn):
    _insert_entity_raw(db_conn, "e1", "Orion and Project Lumen integration")
    _insert_entity_raw(db_conn, "e2", "Alice Tran")
    _insert_entity_raw(db_conn, "e3", "Head of Engineering at Acme Corp")

    result = prune_non_person_entities(db_conn)

    assert result["pruned"] == 2
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e1'").fetchone() is None
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e3'").fetchone() is None
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e2'").fetchone() is not None


def test_prune_phrase_dry_run(db_conn):
    _insert_entity_raw(db_conn, "e1", "Orion and Project Lumen integration")
    _insert_entity_raw(db_conn, "e2", "Alice Tran")

    result = prune_non_person_entities(db_conn, dry_run=True)

    assert result["pruned"] == 1
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e1'").fetchone() is not None


def test_prune_skips_sender_entities(db_conn):
    upsert_entity(db_conn, _entity("e1", "Build Bot"))
    insert_observation(db_conn, _obs("o1", "e1"))

    result = prune_non_person_entities(db_conn)

    assert result["pruned"] == 0
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e1'").fetchone() is not None


def test_prune_handle_named_sender_with_claims_survives(db_conn):
    _insert_entity_raw(db_conn, "e1", "user_a")
    insert_observation(db_conn, _obs("o1", "e1"))
    insert_claim(db_conn, _claim("c1", "e1"))
    upsert_relationship(db_conn, _rel("r1", "e1", "e1"))

    result = prune_non_person_entities(db_conn)

    assert result["pruned"] == 0
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e1'").fetchone() is not None
    assert db_conn.execute("SELECT 1 FROM claims WHERE id = 'c1'").fetchone() is not None
    assert db_conn.execute("SELECT 1 FROM relationships WHERE id = 'r1'").fetchone() is not None


def test_plausible_accepts_slack_ids():
    assert is_plausible_person_name("U0EXAMPLE1") is True
    assert is_plausible_person_name("U012ABCDEF") is True
    assert is_plausible_person_name("W0EXAMPLE1") is True


def test_plausible_rejects_uppercase_words():
    assert is_plausible_person_name("URGENT") is False
    assert is_plausible_person_name("WEEKLY") is False
    assert is_plausible_person_name("UPDATE") is False
    assert is_plausible_person_name("WORKSHOP") is False


def test_plausible_rejects_lowercase_words():
    assert is_plausible_person_name("meeting") is False
    assert is_plausible_person_name("sprint") is False
    assert is_plausible_person_name("tomorrow") is False
    assert is_plausible_person_name("the_team") is False
    assert is_plausible_person_name("user_a") is False
    assert is_plausible_person_name("alice_chen") is False


# ── prune_slack_link_entities ──────────────────────────────────


def test_prune_slack_link_entities_removes_junk(db_conn):
    junk = Entity(
        id="junk1",
        type="reference",
        name="https://github.com/org/repo/compare/a...b|compare",
        aliases=[],
    )
    clean = Entity(
        id="clean1",
        type="reference",
        name="https://example.com/page",
        aliases=[],
    )
    upsert_entity(db_conn, junk)
    upsert_entity(db_conn, clean)

    result = prune_slack_link_entities(db_conn)
    assert result["pruned"] == 1
    assert result["entities"][0]["id"] == "junk1"

    remaining = db_conn.execute("SELECT id FROM entities WHERE type = 'reference'").fetchall()
    assert len(remaining) == 1
    assert remaining[0]["id"] == "clean1"


def test_prune_slack_link_entities_dry_run(db_conn):
    junk = Entity(
        id="junk1",
        type="reference",
        name="https://github.com/org/repo|repo link",
        aliases=[],
    )
    upsert_entity(db_conn, junk)

    result = prune_slack_link_entities(db_conn, dry_run=True)
    assert result["pruned"] == 1

    remaining = db_conn.execute("SELECT id FROM entities WHERE type = 'reference'").fetchall()
    assert len(remaining) == 1


# ── retype_organization_entities ─────────────────────────────


def test_retype_retypes_orgs(db_conn):
    _insert_entity_raw(db_conn, "e1", "Acme Field Research")
    _insert_entity_raw(db_conn, "e2", "Dana Brook")
    _insert_entity_raw(db_conn, "e3", "Acme Events")

    result = retype_organization_entities(db_conn)

    assert result["retyped"] == 2
    row1 = db_conn.execute("SELECT type FROM entities WHERE id = 'e1'").fetchone()
    assert row1["type"] == "organization"
    row2 = db_conn.execute("SELECT type FROM entities WHERE id = 'e2'").fetchone()
    assert row2["type"] == "person"
    row3 = db_conn.execute("SELECT type FROM entities WHERE id = 'e3'").fetchone()
    assert row3["type"] == "organization"


def test_retype_dry_run(db_conn):
    _insert_entity_raw(db_conn, "e1", "Acme Field Research")

    result = retype_organization_entities(db_conn, dry_run=True)

    assert result["retyped"] == 1
    row = db_conn.execute("SELECT type FROM entities WHERE id = 'e1'").fetchone()
    assert row["type"] == "person"


def test_retype_skips_owner(db_conn):
    _insert_entity_raw(db_conn, "e1", "Acme Research", is_owner=1)

    result = retype_organization_entities(db_conn)
    assert result["retyped"] == 0


def test_retype_skips_already_organization(db_conn):
    db_conn.execute(
        "INSERT INTO entities"
        " (id, type, name, aliases, metadata,"
        "  first_seen, last_seen, decay_rate, is_owner)"
        " VALUES ('e1', 'organization', 'Acme Research', '[]', '{}', '', '', 0.02, 0)"
    )
    db_conn.commit()

    result = retype_organization_entities(db_conn)
    assert result["retyped"] == 0


# ── _is_junk_sender_name ─────────────────────────────────────


def test_is_junk_sender_name_legacy_dn():
    assert _is_junk_sender_name("/O=EXCHANGELABS/OU=GROUP/CN=abc") is True


def test_is_junk_sender_name_legacy_dn_lower():
    assert _is_junk_sender_name("/o=EXCHANGELABS/ou=GROUP/cn=abc") is True


def test_is_junk_sender_name_bare_email():
    assert _is_junk_sender_name("dana.brook@example.com") is True


def test_is_junk_sender_name_regular_name():
    assert _is_junk_sender_name("Dana Brook") is False


def test_is_junk_sender_name_handle():
    assert _is_junk_sender_name("dbrook") is False


# ── fix_junk_senders ────────────────────────────────────────


def test_fix_junk_senders_dn_merges_via_alias(db_conn):
    """DN entity whose email alias matches Dana Brook merges into her."""
    _insert_entity_raw(db_conn, "e_dana", "Dana Brook", aliases=["dana.brook@example.com"])
    dn = "/O=EXCHANGELABS/OU=EXCHANGE ADMINISTRATIVE GROUP/CN=RECIPIENTS/CN=abc123"
    _insert_entity_raw(db_conn, "e_dn", dn, aliases=["dana.brook@example.com"])
    insert_observation(db_conn, _obs("o1", "e_dn"))

    result = fix_junk_senders(db_conn)

    assert len(result["merged"]) == 1
    assert result["merged"][0]["target_name"] == "Dana Brook"
    assert result["merged"][0]["junk_name"] == dn
    assert len(result["retyped"]) == 0

    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e_dn'").fetchone() is None
    row = db_conn.execute("SELECT sender_entity_id FROM observations WHERE id = 'o1'").fetchone()
    assert row["sender_entity_id"] == "e_dana"


def test_fix_junk_senders_email_merges_via_dedup_norm(db_conn):
    """Email-as-name entity merges into matching person via dedup normalization."""
    _insert_entity_raw(db_conn, "e_sam", "Sam Rivera")
    _insert_entity_raw(db_conn, "e_email", "sam.rivera@example.com")
    insert_observation(db_conn, _obs("o1", "e_email"))

    result = fix_junk_senders(db_conn)

    assert len(result["merged"]) == 1
    assert result["merged"][0]["target_name"] == "Sam Rivera"
    assert len(result["retyped"]) == 0

    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e_email'").fetchone() is None
    row = db_conn.execute("SELECT sender_entity_id FROM observations WHERE id = 'o1'").fetchone()
    assert row["sender_entity_id"] == "e_sam"


def test_fix_junk_senders_unmatched_retyped(db_conn):
    """Unmatched DN entity is retyped to reference and keeps its observations."""
    dn = "/O=EXCHANGELABS/OU=GROUP/CN=unknown_user"
    _insert_entity_raw(db_conn, "e_dn", dn)
    insert_observation(db_conn, _obs("o1", "e_dn"))

    result = fix_junk_senders(db_conn)

    assert len(result["merged"]) == 0
    assert len(result["retyped"]) == 1
    assert result["retyped"][0]["name"] == dn

    ent = db_conn.execute("SELECT type FROM entities WHERE id = 'e_dn'").fetchone()
    assert ent["type"] == "reference"

    row = db_conn.execute("SELECT sender_entity_id FROM observations WHERE id = 'o1'").fetchone()
    assert row["sender_entity_id"] == "e_dn"


def test_fix_junk_senders_dry_run(db_conn):
    """Dry run previews changes without modifying the database."""
    _insert_entity_raw(db_conn, "e_dana", "Dana Brook", aliases=["dana.brook@example.com"])
    dn = "/O=EXCHANGELABS/OU=GROUP/CN=abc"
    _insert_entity_raw(db_conn, "e_dn", dn, aliases=["dana.brook@example.com"])
    insert_observation(db_conn, _obs("o1", "e_dn"))

    result = fix_junk_senders(db_conn, dry_run=True)

    assert len(result["merged"]) == 1
    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e_dn'").fetchone() is not None
    row = db_conn.execute("SELECT sender_entity_id FROM observations WHERE id = 'o1'").fetchone()
    assert row["sender_entity_id"] == "e_dn"


def test_fix_junk_senders_skips_non_senders(db_conn):
    """Junk-named entities without observations are not processed."""
    _insert_entity_raw(db_conn, "e_dn", "/O=EXCHANGELABS/OU=GROUP/CN=abc")

    result = fix_junk_senders(db_conn)

    assert len(result["merged"]) == 0
    assert len(result["retyped"]) == 0
    ent = db_conn.execute("SELECT type FROM entities WHERE id = 'e_dn'").fetchone()
    assert ent["type"] == "person"


def test_fix_junk_senders_skips_owner(db_conn):
    """Owner entities are never touched."""
    _insert_entity_raw(db_conn, "e_own", "owner@example.com", is_owner=1)
    insert_observation(db_conn, _obs("o1", "e_own"))

    result = fix_junk_senders(db_conn)

    assert len(result["merged"]) == 0
    assert len(result["retyped"]) == 0


def test_fix_junk_senders_no_junk(db_conn):
    """No changes when all sender entities have proper names."""
    _insert_entity_raw(db_conn, "e1", "Alice Tran")
    insert_observation(db_conn, _obs("o1", "e1"))

    result = fix_junk_senders(db_conn)

    assert len(result["merged"]) == 0
    assert len(result["retyped"]) == 0


def test_fix_junk_senders_observations_never_deleted(db_conn):
    """Both merge and retype paths preserve all observations."""
    _insert_entity_raw(db_conn, "e_dana", "Dana Brook", aliases=["dana.brook@example.com"])
    _insert_entity_raw(
        db_conn,
        "e_dn_match",
        "/O=EXCHANGELABS/OU=GROUP/CN=match",
        aliases=["dana.brook@example.com"],
    )
    insert_observation(db_conn, _obs("o_match", "e_dn_match"))

    _insert_entity_raw(db_conn, "e_dn_nomatch", "/O=EXCHANGELABS/OU=GROUP/CN=nomatch")
    insert_observation(db_conn, _obs("o_nomatch", "e_dn_nomatch"))

    obs_before = db_conn.execute("SELECT COUNT(*) AS c FROM observations").fetchone()["c"]

    fix_junk_senders(db_conn)

    obs_after = db_conn.execute("SELECT COUNT(*) AS c FROM observations").fetchone()["c"]
    assert obs_after == obs_before


# ── CLI: patina entity fix-senders ────────────────────────────


def test_cli_entity_fix_senders_dry_run(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    _insert_entity_raw(conn, "e_dana", "Dana Brook", aliases=["dana.brook@example.com"])
    dn = "/O=EXCHANGELABS/OU=GROUP/CN=abc"
    _insert_entity_raw(conn, "e_dn", dn, aliases=["dana.brook@example.com"])
    insert_observation(conn, _obs("o1", "e_dn"))
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "fix-senders", "--home", str(home)])
    assert result.exit_code == 0
    assert "Would apply 1 merge(s)" in result.output
    assert "Dana Brook" in result.output
    assert "re-run with --confirm to apply" in result.output

    conn = connect(db_path)
    assert conn.execute("SELECT 1 FROM entities WHERE id = 'e_dn'").fetchone() is not None
    conn.close()


def test_cli_entity_fix_senders_confirm(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    _insert_entity_raw(conn, "e_dana", "Dana Brook", aliases=["dana.brook@example.com"])
    dn = "/O=EXCHANGELABS/OU=GROUP/CN=abc"
    _insert_entity_raw(conn, "e_dn", dn, aliases=["dana.brook@example.com"])
    insert_observation(conn, _obs("o1", "e_dn"))
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "fix-senders", "--confirm", "--home", str(home)])
    assert result.exit_code == 0
    assert "Applied 1 merge(s)" in result.output
    assert "Dana Brook" in result.output
    assert "re-run with --confirm" not in result.output

    conn = connect(db_path)
    assert conn.execute("SELECT 1 FROM entities WHERE id = 'e_dn'").fetchone() is None
    row = conn.execute("SELECT sender_entity_id FROM observations WHERE id = 'o1'").fetchone()
    assert row["sender_entity_id"] == "e_dana"
    conn.close()


def test_cli_entity_fix_senders_retype(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    dn = "/O=EXCHANGELABS/OU=GROUP/CN=orphan"
    _insert_entity_raw(conn, "e_dn", dn)
    insert_observation(conn, _obs("o1", "e_dn"))
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "fix-senders", "--confirm", "--home", str(home)])
    assert result.exit_code == 0
    assert "Applied 1 retype(s)" in result.output
    assert "reference" in result.output

    conn = connect(db_path)
    ent = conn.execute("SELECT type FROM entities WHERE id = 'e_dn'").fetchone()
    assert ent["type"] == "reference"
    row = conn.execute("SELECT sender_entity_id FROM observations WHERE id = 'o1'").fetchone()
    assert row["sender_entity_id"] == "e_dn"
    conn.close()


def test_cli_entity_fix_senders_noop(db_path):
    from typer.testing import CliRunner

    from patina.cli import app

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "fix-senders", "--home", str(home)])
    assert result.exit_code == 0
    assert "No junk sender entities found." in result.output


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
    _insert_entity_raw(conn, "e1aabbcc", "Sam Rivera", aliases=["slack:U001"])
    _insert_entity_raw(conn, "e2ddeeff", "Rivera, Sam", aliases=["slack:U001"])
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "dedup", "--home", str(home)])
    assert result.exit_code == 0
    assert "1 group" in result.output
    assert "re-run with --confirm to apply" in result.output
    assert "(match: slack:u001)" in result.output

    conn = connect(db_path)
    assert conn.execute("SELECT 1 FROM entities WHERE id = 'e2ddeeff'").fetchone() is not None
    conn.close()


def test_cli_entity_dedup_confirm(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    _insert_entity_raw(conn, "e1aabbcc", "Sam Rivera", aliases=["slack:U001"])
    _insert_entity_raw(conn, "e2ddeeff", "Rivera, Sam", aliases=["slack:U001"])
    insert_observation(conn, _obs("o1", "e1aabbcc"))
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "dedup", "--confirm", "--home", str(home)])
    assert result.exit_code == 0
    assert "Dedup" in result.output
    assert "re-run with --confirm" not in result.output

    conn = connect(db_path)
    assert conn.execute("SELECT 1 FROM entities WHERE id = 'e2ddeeff'").fetchone() is None
    conn.close()


def test_cli_entity_dedup_shows_skipped(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    _insert_entity_raw(conn, "e1aabbcc", "Sam Rivera", aliases=["slack:U001"])
    _insert_entity_raw(conn, "e2ddeeff", "Rivera, Sam", aliases=["slack:U001"])
    _insert_entity_raw(conn, "e3aabbcc", "Quinn Farrow", aliases=["sam.rivera@work.com"])
    insert_observation(conn, _obs("o1", "e1aabbcc"))
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "dedup", "--home", str(home)])
    assert result.exit_code == 0
    assert "SKIP" in result.output
    assert "alias collision" in result.output


def test_cli_entity_dedup_shows_needs_review(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    _insert_entity_raw(conn, "e1aabbcc", "user_a", aliases=["slack:U0AAAA111", "U0BBBB222"])
    _insert_entity_raw(conn, "e2ddeeff", "U0BBBB222", aliases=["U0BBBB222"])
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "dedup", "--home", str(home)])
    assert result.exit_code == 0
    assert "REVIEW" in result.output
    assert "user_a" in result.output
    assert "multiple Slack IDs" in result.output


def test_cli_entity_dedup_ambiguous_handle_shows_correct_reason(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    _insert_entity_raw(conn, "e1aabbcc", "Alice Tran", aliases=["jfox"])
    _insert_entity_raw(conn, "e2ddeeff", "Beth Marsh", aliases=["jfox"])
    _insert_entity_raw(conn, "e3001122", "jfox", aliases=["slack:U0AAAA111"])
    insert_observation(conn, _obs("o1", "e3001122"))
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "dedup", "--home", str(home)])
    assert result.exit_code == 0
    assert "REVIEW" in result.output
    assert "jfox" in result.output
    assert "ambiguous handle alias" in result.output
    assert "multiple Slack IDs" not in result.output


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
    result = runner.invoke(app, ["entity", "prune", "--non-person", "--home", str(home)])
    assert result.exit_code == 0
    assert "1 non-person" in result.output
    assert "Build Bot" in result.output
    assert "re-run with --confirm" in result.output


def test_cli_entity_prune_requires_filter(db_path):
    from typer.testing import CliRunner

    from patina.cli import app

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "prune", "--home", str(home)])
    assert result.exit_code == 1
    assert "Specify a filter" in result.output


def test_cli_entity_prune_links_dry_run(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    upsert_entity(
        conn,
        Entity(
            id="link1",
            type="reference",
            name="https://github.com/org/repo|repo link",
            aliases=[],
        ),
    )
    upsert_entity(
        conn,
        Entity(id="clean1", type="reference", name="https://example.com", aliases=[]),
    )
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "prune-links", "--dry-run", "--home", str(home)])
    assert result.exit_code == 0
    assert "Would prune" in result.output
    assert "1 link-markup" in result.output
    assert "repo link" in result.output

    conn = connect(db_path)
    remaining = conn.execute("SELECT id FROM entities WHERE type = 'reference'").fetchall()
    conn.close()
    assert len(remaining) == 2


def test_cli_entity_prune_links_deletes(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    upsert_entity(
        conn,
        Entity(
            id="link1",
            type="reference",
            name="https://github.com/org/repo|repo link",
            aliases=[],
        ),
    )
    upsert_entity(
        conn,
        Entity(id="clean1", type="reference", name="https://example.com", aliases=[]),
    )
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "prune-links", "--home", str(home)])
    assert result.exit_code == 0
    assert "Pruned" in result.output
    assert "1 link-markup" in result.output

    conn = connect(db_path)
    remaining = conn.execute("SELECT id FROM entities WHERE type = 'reference'").fetchall()
    conn.close()
    assert len(remaining) == 1
    assert remaining[0]["id"] == "clean1"


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


def test_cli_entity_retype_preview_default(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    _insert_entity_raw(conn, "e1aabbcc", "Acme Field Research")
    _insert_entity_raw(conn, "e2ddeeff", "Dana Brook")
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "retype", "--home", str(home)])
    assert result.exit_code == 0
    assert "Would retype" in result.output
    assert "Acme Field Research" in result.output
    assert "Dana Brook" not in result.output
    assert "--confirm" in result.output

    conn = connect(db_path)
    row = conn.execute("SELECT type FROM entities WHERE id = 'e1aabbcc'").fetchone()
    conn.close()
    assert row["type"] == "person"


def test_cli_entity_retype_applies_with_confirm(db_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    _insert_entity_raw(conn, "e1aabbcc", "Acme Events")
    _insert_entity_raw(conn, "e2ddeeff", "Dana Brook")
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "retype", "--confirm", "--home", str(home)])
    assert result.exit_code == 0
    assert "Retyped" in result.output
    assert "Acme Events" in result.output

    conn = connect(db_path)
    row = conn.execute("SELECT type FROM entities WHERE id = 'e1aabbcc'").fetchone()
    conn.close()
    assert row["type"] == "organization"


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
    _insert_entity_raw(db_conn, "e1", "Sam Rivera", aliases=["slack:U001"])
    _insert_entity_raw(db_conn, "e2", "Rivera, Sam", aliases=["slack:U001"])
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
    assert "Removed 1 dangling claim(s), 1 dangling relationship(s)." in result.output


def test_collect_slack_ids_filters_plain_handle():
    assert _collect_slack_ids(["wdana", "alias:wdana", "slack:W0EXAMPLE1"]) == {"W0EXAMPLE1"}


def test_collect_slack_ids_filters_first_name_aliases():
    assert _collect_slack_ids(["Umara Lee", "Umara", "Umarah"]) == set()


def test_collect_slack_ids_accepts_real_ids():
    assert _collect_slack_ids(["U0EXAMPLE1", "slack:W0EXAMPLE2"]) == {
        "U0EXAMPLE1",
        "W0EXAMPLE2",
    }


def test_find_dedup_plain_handle_with_id_not_in_review(db_conn):
    """A u/w-handle entity with one real Slack ID should not need review."""
    _insert_entity_raw(db_conn, "e1", "wdana", aliases=["alias:wdana", "slack:W0EXAMPLE1"])

    result = find_dedup_candidates(db_conn)
    review_names = {r["name"] for r in result["needs_review"]}
    assert "wdana" not in review_names


def test_find_dedup_u_first_name_aliases_not_in_review(db_conn):
    """A full-name entity with U-starting first-name aliases should not need review."""
    _insert_entity_raw(db_conn, "e1", "Umara Lee", aliases=["Umara", "Umarah"])

    result = find_dedup_candidates(db_conn)
    review_names = {r["name"] for r in result["needs_review"]}
    assert "Umara Lee" not in review_names


def test_find_dedup_two_real_ids_still_needs_review(db_conn):
    """An entity with two genuine Slack IDs should still be flagged for review."""
    _insert_entity_raw(db_conn, "e1", "user_x", aliases=["slack:U0AAAA11111", "U0BBBB22222"])

    result = find_dedup_candidates(db_conn)
    review_names = {r["name"] for r in result["needs_review"]}
    assert "user_x" in review_names


def test_cli_entity_cleanup_nulls_sender_entity_id(db_path):
    """Orphaned sender_entity_id is reported in dry-run and nulled after cleanup."""
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    upsert_entity(conn, _entity("e_alive", "Xander Rowe"))
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO observations"
        " (id, source, channel_id, timestamp, sender_entity_id, text,"
        "  metadata, ingested_at, processed)"
        " VALUES ('obs_orphan', 'slack_export', 'C001', 1000.0, 'gone',"
        "  'The quick brown fox', '{}', '2025-01-01T00:00:00+00:00', 1)"
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")

    obs_before = conn.execute("SELECT COUNT(*) AS c FROM observations").fetchone()["c"]
    conn.close()

    runner = CliRunner()
    home = db_path.parent

    # Dry-run should report dangling sender ref
    result = runner.invoke(app, ["entity", "cleanup", "--dry-run", "--home", str(home)])
    assert result.exit_code == 0
    assert "1 sender ref(s)" in result.output

    # Actual cleanup
    result = runner.invoke(app, ["entity", "cleanup", "--home", str(home)])
    assert result.exit_code == 0
    assert "1 dangling sender ref(s)" in result.output

    # Verify: sender_entity_id nulled, observation not deleted
    conn = connect(db_path)
    row = conn.execute(
        "SELECT sender_entity_id FROM observations WHERE id = 'obs_orphan'"
    ).fetchone()
    assert row is not None, "observation row must not be deleted"
    assert row["sender_entity_id"] is None

    obs_after = conn.execute("SELECT COUNT(*) AS c FROM observations").fetchone()["c"]
    assert obs_after == obs_before, "no observation rows should be deleted"

    # No dangling refs remain
    from patina.store import find_dangling_references

    dangling = find_dangling_references(conn)
    assert dangling.get("senders", 0) == 0
    conn.close()


def test_find_id_named_entities(db_conn):
    _insert_entity_raw(db_conn, "e_id1", "W0EXAMPLE9", aliases=["W0EXAMPLE9", "slack:W0EXAMPLE9"])
    _insert_entity_raw(db_conn, "e_id2", "U0TESTID01", aliases=["U0TESTID01", "slack:U0TESTID01"])
    _insert_entity_raw(db_conn, "e_named", "Dana Brook", aliases=["W0NAMED01", "slack:W0NAMED01"])
    _insert_entity_raw(db_conn, "e_handle", "dbrook", aliases=[])

    results = find_id_named_entities(db_conn)
    ids = {r["name"] for r in results}
    assert "W0EXAMPLE9" in ids
    assert "U0TESTID01" in ids
    assert "Dana Brook" not in ids
    assert "dbrook" not in ids


def test_find_id_named_entities_skips_owner(db_conn):
    _insert_entity_raw(db_conn, "e_owner", "W0OWNER001", aliases=["W0OWNER001"], is_owner=1)
    results = find_id_named_entities(db_conn)
    assert len(results) == 0


def test_cli_entity_resolve_names_preview_default(db_path):
    """Without --confirm, resolve-names previews and makes no writes."""
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.store import connect

    conn = connect(db_path)
    _insert_entity_raw(conn, "e_id1", "W0EXAMPLE9", aliases=["W0EXAMPLE9", "slack:W0EXAMPLE9"])
    _insert_entity_raw(conn, "e_named", "Dana Brook", aliases=["W0NAMED01"])
    before_count = conn.execute("SELECT COUNT(*) AS c FROM entities").fetchone()["c"]
    conn.close()

    runner = CliRunner()
    home = db_path.parent
    result = runner.invoke(app, ["entity", "resolve-names", "--home", str(home)])
    assert result.exit_code == 0
    assert "1 entity(ies)" in result.output
    assert "W0EXAMPLE9" in result.output
    assert "Dana Brook" not in result.output
    assert "re-run with --confirm" in result.output

    conn = connect(db_path)
    after_count = conn.execute("SELECT COUNT(*) AS c FROM entities").fetchone()["c"]
    conn.close()
    assert before_count == after_count


def test_resolve_names_simple_rename(db_conn):
    """With A alone (no B), renames A in place and keeps A.id."""
    from patina.extraction import extract_sender_entity
    from patina.graph import resolve_entity_id

    _insert_entity_raw(db_conn, "e_a", "U0EXAMPLE1", aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1"])

    entity = extract_sender_entity("U0EXAMPLE1", "Dana Brook")
    entity.id = "e_a"

    target_id = resolve_entity_id(db_conn, entity.name, entity.aliases)
    assert target_id is None or target_id == "e_a"

    upsert_entity(db_conn, entity)

    row = db_conn.execute("SELECT name, aliases FROM entities WHERE id = 'e_a'").fetchone()
    assert row["name"] == "Dana Brook"
    aliases = json.loads(row["aliases"])
    assert "U0EXAMPLE1" in aliases
    assert "slack:U0EXAMPLE1" in aliases


def test_resolve_names_merge_duplicate(db_conn):
    """With A + B, merge A into B: one entity named 'Dana Brook' holds U0EXAMPLE1."""
    from patina.extraction import extract_sender_entity
    from patina.graph import resolve_entity_id

    _insert_entity_raw(db_conn, "e_a", "U0EXAMPLE1", aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1"])
    _insert_entity_raw(db_conn, "e_b", "Dana Brook", aliases=["W0NAMED01"])

    db_conn.execute(
        "INSERT INTO observations"
        " (id, source, channel_id, timestamp, sender_entity_id, text, processed, ingested_at)"
        " VALUES ('obs-a', 'slack_export', 'C001', 1000.0, 'e_a', 'The quick brown fox', 1,"
        " '2025-01-01T00:00:00+00:00')"
    )
    db_conn.execute(
        "INSERT INTO claims"
        " (id, subject_id, predicate, object, confidence,"
        "  first_asserted, last_confirmed, decay_rate)"
        " VALUES ('claim-a', 'e_a', 'role', 'engineer', 0.5,"
        " '2025-01-01T00:00:00+00:00', '2025-01-01T00:00:00+00:00', 0.02)"
    )
    db_conn.commit()

    entity = extract_sender_entity("U0EXAMPLE1", "Dana Brook")
    entity.id = "e_a"

    target_id = resolve_entity_id(db_conn, entity.name, entity.aliases)
    assert target_id == "e_b"

    merge_entities(db_conn, keep_id=target_id, drop_id="e_a")
    existing = db_conn.execute("SELECT aliases FROM entities WHERE id = ?", (target_id,)).fetchone()
    existing_aliases = json.loads(existing["aliases"] or "[]")
    final_aliases = list(set(existing_aliases + entity.aliases))
    db_conn.execute(
        "UPDATE entities SET aliases = ? WHERE id = ?",
        (json.dumps(final_aliases), target_id),
    )
    db_conn.commit()

    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e_a'").fetchone() is None
    row = db_conn.execute("SELECT name, aliases FROM entities WHERE id = 'e_b'").fetchone()
    assert row["name"] == "Dana Brook"
    aliases = json.loads(row["aliases"])
    assert "U0EXAMPLE1" in aliases
    assert "slack:U0EXAMPLE1" in aliases

    obs = db_conn.execute("SELECT sender_entity_id FROM observations WHERE id = 'obs-a'").fetchone()
    assert obs["sender_entity_id"] == "e_b"
    claim = db_conn.execute("SELECT subject_id FROM claims WHERE id = 'claim-a'").fetchone()
    assert claim["subject_id"] == "e_b"


def test_upsert_entity_merges_orphan_on_ingest(db_conn):
    """Ingest-time retry: upsert_entity merges orphaned entity A into B."""
    _insert_entity_raw(db_conn, "e_a", "U0EXAMPLE1", aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1"])
    _insert_entity_raw(db_conn, "e_b", "Dana Brook", aliases=["W0NAMED01"])

    db_conn.execute(
        "INSERT INTO observations"
        " (id, source, channel_id, timestamp, sender_entity_id, text, processed, ingested_at)"
        " VALUES ('obs-a', 'slack_export', 'C001', 1000.0, 'e_a', 'The quick brown fox', 1,"
        " '2025-01-01T00:00:00+00:00')"
    )
    db_conn.commit()

    entity = _entity("e_a", "Dana Brook", aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1", "Dana Brook"])
    upsert_entity(db_conn, entity)

    assert db_conn.execute("SELECT 1 FROM entities WHERE id = 'e_a'").fetchone() is None
    row = db_conn.execute("SELECT name, aliases FROM entities WHERE id = 'e_b'").fetchone()
    assert row["name"] == "Dana Brook"
    aliases = json.loads(row["aliases"])
    assert "U0EXAMPLE1" in aliases
    assert "slack:U0EXAMPLE1" in aliases

    obs = db_conn.execute("SELECT sender_entity_id FROM observations WHERE id = 'obs-a'").fetchone()
    assert obs["sender_entity_id"] == "e_b"
    assert entity.id == "e_b"


def test_no_shared_slack_ids_after_upsert_merge(db_conn):
    """After upsert merge, no Slack ID is held by more than one entity."""
    import re

    _insert_entity_raw(db_conn, "e_a", "U0EXAMPLE1", aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1"])
    _insert_entity_raw(db_conn, "e_b", "Dana Brook", aliases=["W0NAMED01"])

    entity = _entity("e_a", "Dana Brook", aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1", "Dana Brook"])
    upsert_entity(db_conn, entity)

    slack_re = re.compile(r"^[UW](?=[A-Z0-9]*\d)[A-Z0-9]{8,10}$")
    id_holders: dict[str, set[str]] = {}
    rows = db_conn.execute("SELECT id, aliases FROM entities").fetchall()
    for r in rows:
        for alias in json.loads(r["aliases"] or "[]"):
            if slack_re.match(alias):
                id_holders.setdefault(alias, set()).add(r["id"])

    for sid, holders in id_holders.items():
        assert len(holders) <= 1, f"Slack ID {sid} held by {holders}"


_DN_PREFIX = "/O=EXAMPLEORG/OU=EXCHANGE ADMINISTRATIVE GROUP (FYDIBOHF23SPDLT)/CN=RECIPIENTS/CN="
_GUID = "0123456789abcdef0123456789abcdef"


def _add_person(conn, eid, name, aliases=None):
    now = "2025-01-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO entities"
        " (id, type, name, aliases, metadata, first_seen, last_seen, decay_rate, is_owner)"
        " VALUES (?, 'person', ?, ?, '{}', ?, ?, 0.02, 0)",
        (eid, name, json.dumps(aliases or []), now, now),
    )


def _add_dn_sender(conn, handle):
    _add_person(conn, "dn-1", f"{_DN_PREFIX}{_GUID}-{handle}")
    conn.execute(
        "INSERT INTO observations"
        " (id, source, channel_id, timestamp, sender_entity_id, text, processed, ingested_at)"
        " VALUES ('obs-dn-1', 'slack_export', 'C001', 1000.0, 'dn-1', 'The quick brown fox', 1,"
        " '2025-01-01T00:00:00+00:00')"
    )
    conn.commit()


def test_dn_handle_merges_into_alias_holder(db_conn):
    _add_person(db_conn, "p-dana", "Dana Brook", ["dbrook"])
    _add_dn_sender(db_conn, "DBROOK")
    result = fix_junk_senders(db_conn, dry_run=True)
    assert [m["target_id"] for m in result["merged"]] == ["p-dana"]
    assert result["retyped"] == []


def test_dn_handle_match_is_case_insensitive(db_conn):
    _add_person(db_conn, "p-dana", "Dana Brook", ["dbrook"])
    _add_dn_sender(db_conn, "DbRoOk")
    result = fix_junk_senders(db_conn, dry_run=True)
    assert [m["target_id"] for m in result["merged"]] == ["p-dana"]


def test_dn_hex_tail_still_retypes(db_conn):
    _add_person(db_conn, "p-dana", "Dana Brook", ["dbrook"])
    _add_dn_sender(db_conn, "A1B2C3D4")
    result = fix_junk_senders(db_conn, dry_run=True)
    assert result["merged"] == []
    assert [r["id"] for r in result["retyped"]] == ["dn-1"]


def test_dn_handle_without_alias_retypes(db_conn):
    _add_dn_sender(db_conn, "ZZTOP")
    result = fix_junk_senders(db_conn, dry_run=True)
    assert result["merged"] == []
    assert [r["id"] for r in result["retyped"]] == ["dn-1"]


def test_dn_handle_with_ambiguous_alias_retypes(db_conn):
    _add_person(db_conn, "p-a", "Dana Brook", ["dbrook"])
    _add_person(db_conn, "p-b", "Dale Brook", ["dbrook"])
    _add_dn_sender(db_conn, "DBROOK")
    result = fix_junk_senders(db_conn, dry_run=True)
    assert result["merged"] == []
    assert [r["id"] for r in result["retyped"]] == ["dn-1"]
