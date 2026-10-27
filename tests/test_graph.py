from __future__ import annotations

from patina.graph import (
    IDENTIFIER_PRECEDENCE,
    _is_multi_identity,
    _name_type_rank,
    count_entities,
    count_observations,
    get_entity,
    identifier_rank,
    identifier_type,
    insert_claim,
    insert_observation,
    normalize_name,
    resolve_entity_id,
    upsert_entity,
    upsert_relationship,
)
from patina.models import Claim, Entity, Observation, Relationship


def test_upsert_entity_inserts(db_conn):
    e = Entity(id="e1", type="person", name="Alice")
    upsert_entity(db_conn, e)
    result = get_entity(db_conn, "e1")
    assert result is not None
    assert result.name == "Alice"


def test_upsert_entity_updates_last_seen(db_conn):
    e1 = Entity(id="e1", type="person", name="Alice", last_seen="2024-01-01")
    upsert_entity(db_conn, e1)

    e2 = Entity(id="e1", type="person", name="Alice Updated", last_seen="2024-06-01")
    upsert_entity(db_conn, e2)

    result = get_entity(db_conn, "e1")
    assert result.last_seen == "2024-06-01"
    assert result.name == "Alice Updated"


def test_insert_observation_new(db_conn):
    obs = Observation(
        id="o1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=None,
        text="hi",
    )
    assert insert_observation(db_conn, obs) is True


def test_insert_observation_duplicate(db_conn):
    obs = Observation(
        id="o1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=None,
        text="hi",
    )
    insert_observation(db_conn, obs)
    assert insert_observation(db_conn, obs) is False


def test_count_entities_all(db_conn):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    upsert_entity(db_conn, Entity(id="e2", type="topic", name="general"))
    assert count_entities(db_conn) == 2


def test_count_entities_by_type(db_conn):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    upsert_entity(db_conn, Entity(id="e2", type="topic", name="general"))
    assert count_entities(db_conn, "person") == 1
    assert count_entities(db_conn, "topic") == 1


def test_count_observations(db_conn):
    obs = Observation(
        id="o1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=None,
        text="hi",
    )
    insert_observation(db_conn, obs)
    assert count_observations(db_conn) == 1


def test_upsert_relationship(db_conn):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    upsert_entity(db_conn, Entity(id="e2", type="project", name="Atlas"))
    rel = Relationship(id="r1", subject_id="e1", predicate="works-on", object_id="e2")
    upsert_relationship(db_conn, rel)
    row = db_conn.execute("SELECT * FROM relationships WHERE id = 'r1'").fetchone()
    assert row is not None
    assert row["predicate"] == "works-on"


def test_insert_claim(db_conn):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    claim = Claim(id="c1", subject_id="e1", predicate="owns", object="ProjectX", confidence=0.8)
    insert_claim(db_conn, claim)
    row = db_conn.execute("SELECT * FROM claims WHERE id = 'c1'").fetchone()
    assert row is not None
    assert row["confidence"] == 0.8


class TestNormalizeName:
    def test_last_first_format(self):
        assert normalize_name("Chen, Dana") == "dana chen"

    def test_email_strips_domain(self):
        assert normalize_name("dchen@example.com") == "dchen"

    def test_simple_name_lowercased(self):
        assert normalize_name("Dana Chen") == "dana chen"

    def test_whitespace_stripped(self):
        assert normalize_name("  Alice  ") == "alice"

    def test_empty_string(self):
        assert normalize_name("") == ""

    def test_last_first_with_email(self):
        assert normalize_name("Chen, Dana") == "dana chen"

    def test_at_prefixed_alias(self):
        assert normalize_name("@jdoe") == "jdoe"

    def test_at_prefixed_alias_matches_bare_handle(self):
        assert normalize_name("@jdoe") == normalize_name("jdoe") == "jdoe"

    def test_email_still_strips_domain_after_at_prefix_fix(self):
        assert normalize_name("jdoe@example.com") == "jdoe"


class TestResolveEntityId:
    def test_exact_name_match(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice Smith"))
        assert resolve_entity_id(db_conn, "Alice Smith") == "e1"

    def test_alias_match(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Dana Chen",
                aliases=["dchen", "U00DCHEN"],
            ),
        )
        assert resolve_entity_id(db_conn, "dchen") == "e1"

    def test_normalized_last_first(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Dana Chen"))
        assert resolve_entity_id(db_conn, "Chen, Dana") == "e1"

    def test_normalized_email(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Dana Chen",
                aliases=["dchen"],
            ),
        )
        assert resolve_entity_id(db_conn, "dchen@example.com") == "e1"

    def test_provided_alias_match(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Bob Smith",
                aliases=["bsmith"],
            ),
        )
        assert resolve_entity_id(db_conn, "Robert Smith", aliases=["bsmith"]) == "e1"

    def test_no_match_returns_none(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        assert resolve_entity_id(db_conn, "Nobody") is None

    def test_empty_name_returns_none(self, db_conn):
        assert resolve_entity_id(db_conn, "") is None
        assert resolve_entity_id(db_conn, "  ") is None

    def test_skips_owner_entities(self, db_conn):
        db_conn.execute(
            """INSERT INTO entities
               (id, type, name, aliases, metadata, first_seen, last_seen,
                decay_rate, is_owner)
               VALUES ('e1', 'person', 'Owner', '[]', '{}',
                       '2024-01-01', '2024-01-01', 0.02, 1)"""
        )
        db_conn.commit()
        assert resolve_entity_id(db_conn, "Owner") is None


class TestUpsertEntityMerge:
    def test_merges_into_existing_by_name(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Dana Chen",
                aliases=["dchen"],
            ),
        )
        new_entity = Entity(
            id="e2",
            type="person",
            name="Dana Chen",
            aliases=["U00DCHEN"],
        )
        upsert_entity(db_conn, new_entity)
        assert new_entity.id == "e1"
        assert count_entities(db_conn, "person") == 1
        ent = get_entity(db_conn, "e1")
        assert "dchen" in ent.aliases
        assert "U00DCHEN" in ent.aliases

    def test_merges_by_normalized_name(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(id="e1", type="person", name="Dana Chen"),
        )
        new_entity = Entity(
            id="e2",
            type="person",
            name="Chen, Dana",
            aliases=["dchen"],
        )
        upsert_entity(db_conn, new_entity)
        assert new_entity.id == "e1"
        assert count_entities(db_conn, "person") == 1

    def test_no_merge_for_different_people(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice Smith"))
        upsert_entity(db_conn, Entity(id="e2", type="person", name="Bob Jones"))
        assert count_entities(db_conn, "person") == 2

    def test_same_id_updates_in_place(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Alice",
                last_seen="2024-01-01",
            ),
        )
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Alice Updated",
                last_seen="2024-06-01",
            ),
        )
        ent = get_entity(db_conn, "e1")
        assert ent.name == "Alice Updated"
        assert count_entities(db_conn) == 1


class TestNameTypeRank:
    def test_full_name(self):
        assert _name_type_rank("Dana Brook") == 0

    def test_handle(self):
        assert _name_type_rank("dbrook") == 1

    def test_email(self):
        assert _name_type_rank("dbrook@example.com") == 2

    def test_slack_id(self):
        assert _name_type_rank("U0EXAMPLE1") == 3

    def test_ordering(self):
        assert (
            _name_type_rank("Dana Brook")
            < _name_type_rank("dbrook")
            < _name_type_rank("dbrook@example.com")
            < _name_type_rank("U0EXAMPLE1")
        )


class TestNameTypeRankDN:
    def test_truncated_dn_ranks_below_handle(self):
        assert _name_type_rank("/O=EXAMPLEORG/OU=X") > _name_type_rank("jsmith")

    def test_truncated_dn_ranks_below_display_name(self):
        assert _name_type_rank("/O=EXAMPLEORG/OU=X") > _name_type_rank("Dana Brook")

    def test_full_dn_ranks_below_handle(self):
        assert _name_type_rank("/O=EXAMPLEORG/OU=X/CN=Dana Brook") > _name_type_rank("jsmith")

    def test_full_dn_ranks_below_display_name(self):
        assert _name_type_rank("/O=EXAMPLEORG/OU=X/CN=Dana Brook") > _name_type_rank("Dana Brook")

    def test_dn_ordering(self):
        assert (
            _name_type_rank("Dana Brook")
            < _name_type_rank("jsmith")
            < _name_type_rank("/O=EXAMPLEORG/OU=X")
        )
        assert _name_type_rank("/O=EXAMPLEORG/OU=X") == _name_type_rank(
            "/O=EXAMPLEORG/OU=X/CN=Dana Brook"
        )


class TestResolveEntityIdTruncatedDN:
    def test_truncated_dn_does_not_match_by_name(self, db_conn):
        _raw_insert_entity(
            db_conn,
            "e1",
            "person",
            "/O=EXAMPLEORG/OU=ADMIN GROUP",
        )
        assert resolve_entity_id(db_conn, "/O=EXAMPLEORG/OU=ADMIN GROUP") is None

    def test_truncated_dn_does_not_match_by_alias(self, db_conn):
        _raw_insert_entity(
            db_conn,
            "e1",
            "person",
            "Dana Brook",
            aliases=["/O=EXAMPLEORG/OU=ADMIN GROUP"],
        )
        assert resolve_entity_id(db_conn, "/O=EXAMPLEORG/OU=ADMIN GROUP") is None

    def test_full_dn_still_resolvable(self, db_conn):
        _raw_insert_entity(
            db_conn,
            "e1",
            "person",
            "/O=EXAMPLEORG/OU=X/CN=Dana Brook",
        )
        assert resolve_entity_id(db_conn, "/O=EXAMPLEORG/OU=X/CN=Dana Brook") == "e1"


class TestUpsertEntityNoOverwrite:
    """#398: upsert must not overwrite a merged entity's name or aliases."""

    def test_same_id_preserves_full_name_over_handle(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Dana Brook",
                aliases=["Brook, Dana", "dbrook"],
            ),
        )
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="dbrook",
                aliases=["dbrook", "U0EXAMPLE1", "slack:U0EXAMPLE1"],
            ),
        )
        ent = get_entity(db_conn, "e1")
        assert ent.name == "Dana Brook"
        assert "Brook, Dana" in ent.aliases
        assert "U0EXAMPLE1" in ent.aliases
        assert "slack:U0EXAMPLE1" in ent.aliases
        assert count_entities(db_conn, "person") == 1

    def test_same_id_preserves_full_name_over_slack_id(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Dana Brook",
                aliases=["dbrook"],
            ),
        )
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="U0EXAMPLE1",
                aliases=["U0EXAMPLE1"],
            ),
        )
        ent = get_entity(db_conn, "e1")
        assert ent.name == "Dana Brook"
        assert "dbrook" in ent.aliases
        assert "U0EXAMPLE1" in ent.aliases

    def test_same_id_preserves_full_name_over_email(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Dana Brook",
                aliases=["dbrook@example.com"],
            ),
        )
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="dbrook@example.com",
                aliases=["dbrook@example.com"],
            ),
        )
        ent = get_entity(db_conn, "e1")
        assert ent.name == "Dana Brook"

    def test_same_id_upgrades_handle_to_full_name(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(id="e1", type="person", name="dbrook"),
        )
        upsert_entity(
            db_conn,
            Entity(id="e1", type="person", name="Dana Brook"),
        )
        ent = get_entity(db_conn, "e1")
        assert ent.name == "Dana Brook"

    def test_same_id_unions_aliases(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Dana Brook",
                aliases=["Brook, Dana", "dbrook"],
            ),
        )
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Dana Brook",
                aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1"],
            ),
        )
        ent = get_entity(db_conn, "e1")
        assert "Brook, Dana" in ent.aliases
        assert "dbrook" in ent.aliases
        assert "U0EXAMPLE1" in ent.aliases
        assert "slack:U0EXAMPLE1" in ent.aliases

    def test_email_alias_no_new_entity(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Dana Brook",
                aliases=["dbrook@example.com"],
            ),
        )
        resolved = resolve_entity_id(db_conn, "dbrook@example.com", aliases=["dbrook@example.com"])
        assert resolved == "e1"
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="dbrook@example.com",
                aliases=["dbrook@example.com"],
            ),
        )
        assert count_entities(db_conn, "person") == 1
        ent = get_entity(db_conn, "e1")
        assert ent.name == "Dana Brook"

    def test_email_alias_case_insensitive(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Dana Brook",
                aliases=["DBook@Example.COM"],
            ),
        )
        resolved = resolve_entity_id(db_conn, "dbook@example.com")
        assert resolved == "e1"


class TestMultiIdentityGuard:
    """#486: sink entity with >1 Slack ID or DN must not be renamed."""

    def test_is_multi_identity_two_slack_ids(self):
        assert _is_multi_identity(
            "/O=EXAMPLEORG/OU=X",
            ["U0EXAMPLE1", "slack:U0EXAMPLE1", "U0EXAMPLE2", "slack:U0EXAMPLE2", "user_a"],
        )

    def test_is_multi_identity_single_slack_id(self):
        assert not _is_multi_identity(
            "Dana Brook",
            ["U0EXAMPLE1", "slack:U0EXAMPLE1", "dbrook"],
        )

    def test_is_multi_identity_two_dns(self):
        assert _is_multi_identity(
            "/O=EXAMPLEORG/OU=X",
            ["/O=EXAMPLEORG/OU=X/CN=Dana Brook", "/O=OTHERORG/OU=Y/CN=Jo Smith"],
        )

    def test_sink_dn_name_not_overwritten_by_handle(self, db_conn):
        """Acceptance #1: fixture sink holds truncated-DN name, 2 Slack IDs
        and handle user_a.  Ingest from one of those IDs with user_name
        user_a — name must stay unchanged."""
        _raw_insert_entity(
            db_conn,
            "e626",
            "person",
            "/O=EXAMPLEORG/OU=X",
            aliases=[
                "U0EXAMPLE1",
                "slack:U0EXAMPLE1",
                "U0EXAMPLE2",
                "slack:U0EXAMPLE2",
                "user_a",
            ],
        )
        upsert_entity(
            db_conn,
            Entity(
                id="e626",
                type="person",
                name="user_a",
                aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1", "user_a"],
            ),
        )
        ent = get_entity(db_conn, "e626")
        assert ent.name == "/O=EXAMPLEORG/OU=X"
        assert "user_a" in ent.aliases

    def test_sink_dn_name_not_overwritten_by_full_name(self, db_conn):
        """Even a full name (rank 0) must not overwrite a multi-ID sink."""
        _raw_insert_entity(
            db_conn,
            "e626",
            "person",
            "/O=EXAMPLEORG/OU=X",
            aliases=[
                "U0EXAMPLE1",
                "slack:U0EXAMPLE1",
                "U0EXAMPLE2",
                "slack:U0EXAMPLE2",
            ],
        )
        upsert_entity(
            db_conn,
            Entity(
                id="e626",
                type="person",
                name="Dana Brook",
                aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1"],
            ),
        )
        ent = get_entity(db_conn, "e626")
        assert ent.name == "/O=EXAMPLEORG/OU=X"

    def test_single_slack_id_entity_still_promotable(self, db_conn):
        """Normal entity with one Slack ID should still get name promoted."""
        _raw_insert_entity(
            db_conn,
            "e1",
            "person",
            "U0EXAMPLE1",
            aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1"],
        )
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Dana Brook",
                aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1"],
            ),
        )
        ent = get_entity(db_conn, "e1")
        assert ent.name == "Dana Brook"


class TestResolveEntityIdPrefixNormalization:
    def test_prefixed_query_finds_unprefixed_alias(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Rivera",
                aliases=["U000OWNER"],
            ),
        )
        assert resolve_entity_id(db_conn, "slack:U000OWNER") == "e1"

    def test_prefixed_and_unprefixed_resolve_same(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Rivera",
                aliases=["U000OWNER"],
            ),
        )
        assert resolve_entity_id(db_conn, "slack:U000OWNER") == resolve_entity_id(
            db_conn, "U000OWNER"
        )

    def test_unprefixed_query_finds_prefixed_alias(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Rivera",
                aliases=["slack:U000OWNER"],
            ),
        )
        assert resolve_entity_id(db_conn, "U000OWNER") == "e1"


class TestResolveEntityIdCrossMatch:
    def test_prefixed_alias_matches_name(self, db_conn):
        """Entity 'dchen' has alias 'display_name:Dana Chen'.
        Resolving 'Dana Chen' should find it via cross-match."""
        db_conn.execute(
            """INSERT INTO entities
               (id, type, name, aliases, metadata, first_seen, last_seen,
                decay_rate, is_owner)
               VALUES ('e1', 'person', 'dchen',
                       '["display_name:Dana Chen"]', '{}',
                       '2024-01-01', '2024-01-01', 0.02, 0)"""
        )
        db_conn.commit()
        assert resolve_entity_id(db_conn, "Dana Chen") == "e1"

    def test_prefixed_alias_normalized_match(self, db_conn):
        """'Chen, Dana' normalizes to 'dana chen', which matches
        stripped alias 'display_name:Dana Chen' -> 'dana chen'."""
        db_conn.execute(
            """INSERT INTO entities
               (id, type, name, aliases, metadata, first_seen, last_seen,
                decay_rate, is_owner)
               VALUES ('e1', 'person', 'dchen',
                       '["display_name:Dana Chen"]', '{}',
                       '2024-01-01', '2024-01-01', 0.02, 0)"""
        )
        db_conn.commit()
        assert resolve_entity_id(db_conn, "Chen, Dana") == "e1"

    def test_outlook_prefixed_alias(self, db_conn):
        db_conn.execute(
            """INSERT INTO entities
               (id, type, name, aliases, metadata, first_seen, last_seen,
                decay_rate, is_owner)
               VALUES ('e1', 'person', 'Bob Smith',
                       '["outlook:Smith, Bob"]', '{}',
                       '2024-01-01', '2024-01-01', 0.02, 0)"""
        )
        db_conn.commit()
        assert resolve_entity_id(db_conn, "Smith, Bob") == "e1"

    def test_no_false_cross_match(self, db_conn):
        db_conn.execute(
            """INSERT INTO entities
               (id, type, name, aliases, metadata, first_seen, last_seen,
                decay_rate, is_owner)
               VALUES ('e1', 'person', 'Alice',
                       '["slack:alice123"]', '{}',
                       '2024-01-01', '2024-01-01', 0.02, 0)"""
        )
        db_conn.commit()
        assert resolve_entity_id(db_conn, "Bob Jones") is None

    def test_upsert_merges_via_cross_match(self, db_conn):
        """Entity 'dchen' with prefixed alias. Upserting 'Dana Chen'
        should merge into it instead of creating a duplicate."""
        db_conn.execute(
            """INSERT INTO entities
               (id, type, name, aliases, metadata, first_seen, last_seen,
                decay_rate, is_owner)
               VALUES ('e1', 'person', 'dchen',
                       '["display_name:Dana Chen", "U00DCHEN2"]',
                       '{}', '2024-01-01', '2024-01-01', 0.02, 0)"""
        )
        db_conn.commit()
        new_ent = Entity(
            id="e2",
            type="person",
            name="Dana Chen",
            aliases=["dchen@corp.com"],
        )
        upsert_entity(db_conn, new_ent)
        assert new_ent.id == "e1"
        assert count_entities(db_conn, "person") == 1
        ent = get_entity(db_conn, "e1")
        assert "dchen@corp.com" in ent.aliases


def _raw_insert_entity(conn, eid, etype, name, aliases=None, is_owner=0):
    """Direct SQL insert bypassing upsert merge logic (for test fixtures)."""
    import json as _json

    conn.execute(
        """INSERT INTO entities
           (id, type, name, aliases, metadata, first_seen, last_seen,
            decay_rate, is_owner)
           VALUES (?, ?, ?, ?, '{}', '2024-01-01', '2024-01-01', 0.02, ?)""",
        (eid, etype, name, _json.dumps(aliases or []), is_owner),
    )
    conn.commit()


class TestResolveEntityIdSlackPriority:
    """#434: Slack ID in aliases must win over ambiguous handle matches."""

    def test_slack_id_routes_to_correct_entity(self, db_conn):
        """Repro from #434: handle_r is an alias on both A and B.
        Incoming Slack ID U0EXAMPLE1 belongs to B — should land on B."""
        _raw_insert_entity(
            db_conn,
            "eA",
            "person",
            "handle_m",
            aliases=["handle_m", "U0EXAMPLE2", "handle_r"],
        )
        _raw_insert_entity(
            db_conn,
            "eB",
            "person",
            "Dana Brook",
            aliases=["handle_r", "U0EXAMPLE1"],
        )
        result = resolve_entity_id(db_conn, "handle_r", aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1"])
        assert result == "eB"

    def test_slack_id_prevents_alias_contamination(self, db_conn):
        """After correct resolution, A's aliases must not gain B's Slack ID."""
        _raw_insert_entity(
            db_conn,
            "eA",
            "person",
            "handle_m",
            aliases=["handle_m", "U0EXAMPLE2", "handle_r"],
        )
        _raw_insert_entity(
            db_conn,
            "eB",
            "person",
            "Dana Brook",
            aliases=["handle_r", "U0EXAMPLE1"],
        )
        incoming = Entity(
            id="eNEW",
            type="person",
            name="handle_r",
            aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1"],
        )
        upsert_entity(db_conn, incoming)
        assert incoming.id == "eB"
        ent_a = get_entity(db_conn, "eA")
        assert "U0EXAMPLE1" not in ent_a.aliases
        assert "slack:U0EXAMPLE1" not in ent_a.aliases

    def test_shared_handle_no_slack_id_returns_none(self, db_conn):
        """A handle alias on two entities with no Slack ID must not pick one."""
        _raw_insert_entity(
            db_conn,
            "eA",
            "person",
            "handle_m",
            aliases=["handle_r"],
        )
        _raw_insert_entity(
            db_conn,
            "eB",
            "person",
            "Dana Brook",
            aliases=["handle_r"],
        )
        assert resolve_entity_id(db_conn, "handle_r") is None

    def test_slack_id_prefixed_also_wins(self, db_conn):
        """slack:U0EXAMPLE1 in aliases should match stored U0EXAMPLE1."""
        _raw_insert_entity(
            db_conn,
            "eA",
            "person",
            "handle_m",
            aliases=["handle_r"],
        )
        _raw_insert_entity(
            db_conn,
            "eB",
            "person",
            "Dana Brook",
            aliases=["handle_r", "U0EXAMPLE1"],
        )
        result = resolve_entity_id(db_conn, "handle_r", aliases=["slack:U0EXAMPLE1"])
        assert result == "eB"


class TestResolveEntityIdDuplicateSlackId:
    """#446: resolve_entity_id must not return wrong entity when
    duplicate Slack ID exists from prior misroute contamination."""

    def test_contaminated_entity_does_not_win(self, db_conn):
        """A (lower rowid) holds B's Slack ID from misroute.
        Resolution must return B, never A."""
        _raw_insert_entity(
            db_conn,
            "eA",
            "person",
            "handle_m",
            aliases=["handle_m", "U0EXAMPLE2", "handle_r", "U0EXAMPLE1", "slack:U0EXAMPLE1"],
        )
        _raw_insert_entity(
            db_conn,
            "eB",
            "person",
            "Dana Brook",
            aliases=["handle_r", "U0EXAMPLE1"],
        )
        result = resolve_entity_id(db_conn, "handle_r", aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1"])
        assert result != "eA"
        assert result == "eB"

    def test_slack_id_beats_unique_handle_alias(self, db_conn):
        """A uniquely holds handle_r, B holds only the Slack ID.
        Message carrying B's ID must resolve to B, not A."""
        _raw_insert_entity(
            db_conn,
            "eA",
            "person",
            "handle_m",
            aliases=["handle_m", "handle_r"],
        )
        _raw_insert_entity(
            db_conn,
            "eB",
            "person",
            "Dana Brook",
            aliases=["U0EXAMPLE1"],
        )
        result = resolve_entity_id(db_conn, "handle_r", aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1"])
        assert result == "eB"

    def test_upsert_no_alias_leak_to_contaminated_entity(self, db_conn):
        """After upsert with contaminated shape, A must not gain new aliases."""
        _raw_insert_entity(
            db_conn,
            "eA",
            "person",
            "handle_m",
            aliases=["handle_m", "U0EXAMPLE2", "handle_r", "U0EXAMPLE1", "slack:U0EXAMPLE1"],
        )
        _raw_insert_entity(
            db_conn,
            "eB",
            "person",
            "Dana Brook",
            aliases=["handle_r", "U0EXAMPLE1"],
        )
        a_before = get_entity(db_conn, "eA")
        incoming = Entity(
            id="eNEW",
            type="person",
            name="handle_r",
            aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1"],
        )
        upsert_entity(db_conn, incoming)
        a_after = get_entity(db_conn, "eA")
        assert set(a_after.aliases) == set(a_before.aliases)

    def test_upsert_no_alias_leak_unique_handle(self, db_conn):
        """After upsert where B resolves via Slack ID, A gains nothing."""
        _raw_insert_entity(
            db_conn,
            "eA",
            "person",
            "handle_m",
            aliases=["handle_m", "handle_r"],
        )
        _raw_insert_entity(
            db_conn,
            "eB",
            "person",
            "Dana Brook",
            aliases=["U0EXAMPLE1"],
        )
        a_before = get_entity(db_conn, "eA")
        incoming = Entity(
            id="eNEW",
            type="person",
            name="handle_r",
            aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1"],
        )
        upsert_entity(db_conn, incoming)
        a_after = get_entity(db_conn, "eA")
        assert set(a_after.aliases) == set(a_before.aliases)

    def test_both_single_slack_id_returns_none(self, db_conn):
        """Both entities hold the same Slack ID as their only one.
        Tiebreak cannot resolve — must return None."""
        _raw_insert_entity(
            db_conn,
            "eA",
            "person",
            "handle_m",
            aliases=["U0EXAMPLE1"],
        )
        _raw_insert_entity(
            db_conn,
            "eB",
            "person",
            "Dana Brook",
            aliases=["U0EXAMPLE1"],
        )
        result = resolve_entity_id(db_conn, "handle_r", aliases=["U0EXAMPLE1"])
        assert result is None


class TestSharedIdentityFixtures:
    """#447: Shared identity fixtures + graph.py Slack ID contract."""

    def test_slack_id_wins_over_display_name(self, slack_id_wins):
        conn = slack_id_wins["conn"]
        result = resolve_entity_id(
            conn,
            slack_id_wins["shared_name"],
            aliases=[slack_id_wins["slack_id"]],
        )
        assert result == slack_id_wins["entity_with_slack"]

    def test_ambiguous_name_returns_none(self, ambiguous_name):
        conn = ambiguous_name["conn"]
        assert resolve_entity_id(conn, "Riku Endo") is None
        assert resolve_entity_id(conn, "Endo, Riku") is None

    def test_upsert_ambiguous_name_does_not_merge(self, ambiguous_name):
        conn = ambiguous_name["conn"]
        incoming = Entity(
            id="amb-new",
            type="person",
            name="Riku Endo",
            aliases=[],
        )
        upsert_entity(conn, incoming)
        assert get_entity(conn, ambiguous_name["entity_a"]) is not None
        assert get_entity(conn, ambiguous_name["entity_b"]) is not None

    def test_conflicting_id_resolves_by_slack(self, conflicting_id):
        conn = conflicting_id["conn"]
        assert (
            resolve_entity_id(conn, "Yui Sato", aliases=[conflicting_id["slack_id_a"]])
            == conflicting_id["entity_a"]
        )
        assert (
            resolve_entity_id(conn, "Sato, Yui", aliases=[conflicting_id["slack_id_b"]])
            == conflicting_id["entity_b"]
        )

    def test_conflicting_id_no_slack_returns_none(self, conflicting_id):
        conn = conflicting_id["conn"]
        assert resolve_entity_id(conn, "Yui Sato") is None

    def test_clean_merge(self, clean_merge):
        conn = clean_merge["conn"]
        assert resolve_entity_id(conn, clean_merge["name"]) == clean_merge["entity_id"]
        assert resolve_entity_id(conn, clean_merge["alias"]) == clean_merge["entity_id"]
        incoming = Entity(
            id="cm-new",
            type="person",
            name="Hana Kimura",
            aliases=["hkimura"],
        )
        upsert_entity(conn, incoming)
        assert incoming.id == clean_merge["entity_id"]
        assert count_entities(conn, "person") == 1


class TestSlackIdUniquenessInvariant:
    """#434: No Slack ID alias may be held by more than one entity."""

    def test_upsert_does_not_duplicate_slack_id(self, db_conn):
        """Same-id update must not steal a Slack ID held by another entity."""
        _raw_insert_entity(
            db_conn,
            "eB",
            "person",
            "Dana Brook",
            aliases=["U0EXAMPLE1"],
        )
        _raw_insert_entity(
            db_conn,
            "eA",
            "person",
            "handle_m",
            aliases=["U0EXAMPLE2"],
        )
        upsert_entity(
            db_conn,
            Entity(
                id="eA",
                type="person",
                name="handle_m",
                aliases=["U0EXAMPLE2", "U0EXAMPLE1"],
            ),
        )
        ent_a = get_entity(db_conn, "eA")
        assert "U0EXAMPLE2" in ent_a.aliases
        assert "U0EXAMPLE1" not in ent_a.aliases
        ent_b = get_entity(db_conn, "eB")
        assert "U0EXAMPLE1" in ent_b.aliases

    def test_upsert_allows_slack_id_on_same_entity(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="eA",
                type="person",
                name="Dana Brook",
                aliases=["U0EXAMPLE1"],
            ),
        )
        upsert_entity(
            db_conn,
            Entity(
                id="eA",
                type="person",
                name="Dana Brook",
                aliases=["U0EXAMPLE1", "slack:U0EXAMPLE1"],
            ),
        )
        ent = get_entity(db_conn, "eA")
        assert "U0EXAMPLE1" in ent.aliases
        assert "slack:U0EXAMPLE1" in ent.aliases


_PRECEDENCE_SAMPLES = {
    "slack_id": "U0000000A1",
    "dn": "/O=EXAMPLEORG/OU=X/CN=RECIPIENTS/CN=DBROOK",
    "email": "dbrook@example.com",
    "handle": "dbrook",
    "display_name": "Dana Brook",
}
_OPAQUE = ("slack_id", "dn")


class TestIdentifierPrecedence:
    """#511: single IDENTIFIER_PRECEDENCE contract for identity resolution."""

    def test_precedence_order(self):
        assert IDENTIFIER_PRECEDENCE == ("slack_id", "dn", "email", "handle", "display_name")

    def test_identifier_type_classifies_samples(self):
        for kind, sample in _PRECEDENCE_SAMPLES.items():
            assert identifier_type(sample) == kind

    def test_identifier_rank_order_matches_precedence(self):
        ordered = sorted(_PRECEDENCE_SAMPLES, key=lambda k: identifier_rank(_PRECEDENCE_SAMPLES[k]))
        assert tuple(ordered) == IDENTIFIER_PRECEDENCE

    def test_name_type_rank_order_derived_from_precedence(self):
        """Readable labels rank in reverse precedence; opaque IDs last, in precedence order."""
        by_rank = sorted(_PRECEDENCE_SAMPLES, key=lambda k: _name_type_rank(_PRECEDENCE_SAMPLES[k]))
        readable = [k for k in IDENTIFIER_PRECEDENCE if k not in _OPAQUE]
        opaque = [k for k in IDENTIFIER_PRECEDENCE if k in _OPAQUE]
        assert by_rank == list(reversed(readable)) + opaque
        ranks = {_name_type_rank(s) for s in _PRECEDENCE_SAMPLES.values()}
        assert len(ranks) == len(IDENTIFIER_PRECEDENCE)


class TestTruncatedDnNotIdentifier:
    """#511: a truncated DN (/O= without CN=) is never an identifier."""

    TRUNCATED = "/O=EXAMPLEORG"
    FULL = "/O=EXAMPLEORG/OU=X/CN=RECIPIENTS/CN=DBROOK"

    def test_identifier_type(self):
        assert identifier_type(self.TRUNCATED) is None
        assert identifier_type("/o=exampleorg/ou=x") is None
        assert identifier_type(self.FULL) == "dn"

    def test_identifier_rank_after_every_identifier(self):
        assert identifier_rank(self.TRUNCATED) == len(IDENTIFIER_PRECEDENCE)
        assert identifier_rank(self.FULL) == IDENTIFIER_PRECEDENCE.index("dn")

    def test_name_type_rank_never_outranks_an_identifier(self):
        truncated = _name_type_rank(self.TRUNCATED)
        assert all(truncated >= _name_type_rank(s) for s in _PRECEDENCE_SAMPLES.values())

    def test_resolve_ignores_truncated_dn_name(self, db_conn):
        _raw_insert_entity(db_conn, "e1", "person", self.TRUNCATED)
        assert resolve_entity_id(db_conn, self.TRUNCATED) is None

    def test_resolve_ignores_truncated_dn_alias(self, db_conn):
        _raw_insert_entity(db_conn, "e1", "person", "Dana Brook", aliases=[self.TRUNCATED])
        assert resolve_entity_id(db_conn, "Zed Query", aliases=[self.TRUNCATED]) is None

    def test_resolve_uses_full_dn_name_and_alias(self, db_conn):
        _raw_insert_entity(db_conn, "e1", "person", "Dana Brook", aliases=[self.FULL])
        _raw_insert_entity(db_conn, "e2", "person", self.FULL + "-2")
        assert resolve_entity_id(db_conn, "Zed Query", aliases=[self.FULL]) == "e1"
        assert resolve_entity_id(db_conn, self.FULL + "-2") == "e2"


class TestResolveSinkHandleTiebreak:
    """#502: a handle held by one DN sink and one person resolves to the person."""

    _SINK_ALIASES = [
        "/O=EXAMPLEORG/OU=ADMIN GROUP/CN=RECIPIENTS/CN=AAA-USER_A",
        "/O=EXAMPLEORG/OU=ADMIN GROUP/CN=RECIPIENTS/CN=BBB-USER_B",
        "user_a",
    ]

    def test_sink_plus_person_resolves_to_person(self, db_conn):
        _raw_insert_entity(
            db_conn, "sink", "person", "/O=EXAMPLEORG/OU=ADMIN GROUP", self._SINK_ALIASES
        )
        _raw_insert_entity(db_conn, "p-dana", "person", "Dana Brook", aliases=["@user_a"])
        assert _is_multi_identity("/O=EXAMPLEORG/OU=ADMIN GROUP", self._SINK_ALIASES)
        assert resolve_entity_id(db_conn, "user_a") == "p-dana"

    def test_two_single_identity_holders_returns_none(self, db_conn):
        _raw_insert_entity(db_conn, "p-dana", "person", "Dana Brook", aliases=["@user_a"])
        _raw_insert_entity(db_conn, "p-evan", "person", "Evan Stone", aliases=["user_a"])
        assert resolve_entity_id(db_conn, "user_a") is None

    def test_two_sinks_plus_person_returns_none(self, db_conn):
        _raw_insert_entity(
            db_conn, "sink1", "person", "/O=EXAMPLEORG/OU=ADMIN GROUP", self._SINK_ALIASES
        )
        _raw_insert_entity(
            db_conn,
            "sink2",
            "person",
            "/O=SINK/sink2",
            aliases=["U0EXAMPLE1", "U0EXAMPLE2", "user_a"],
        )
        _raw_insert_entity(db_conn, "p-dana", "person", "Dana Brook", aliases=["@user_a"])
        assert resolve_entity_id(db_conn, "user_a") is None

    def test_sink_plus_two_persons_returns_none(self, db_conn):
        _raw_insert_entity(
            db_conn, "sink", "person", "/O=EXAMPLEORG/OU=ADMIN GROUP", self._SINK_ALIASES
        )
        _raw_insert_entity(db_conn, "p-dana", "person", "Dana Brook", aliases=["@user_a"])
        _raw_insert_entity(db_conn, "p-evan", "person", "Evan Stone", aliases=["user_a"])
        assert resolve_entity_id(db_conn, "user_a") is None


def _alias_provenance(conn, entity_id):
    from patina.store import ensure_entity_alias_provenance_table

    ensure_entity_alias_provenance_table(conn)
    rows = conn.execute(
        "SELECT alias, adapter, observation_id, action FROM entity_alias_provenance"
        " WHERE entity_id = ? ORDER BY rowid",
        (entity_id,),
    ).fetchall()
    return [tuple(r) for r in rows]


class TestUpsertEntityAliasProvenance:
    """#514: upsert_entity records 'added' rows for new aliases."""

    def test_new_entity_records_added_row_per_alias(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(
                id="e1",
                type="person",
                name="Dana Brook",
                aliases=["U0000000A1", "slack:U0000000A1"],
            ),
            adapter="slack",
            observation_id="obs1",
        )

        assert sorted(_alias_provenance(db_conn, "e1")) == [
            ("U0000000A1", "slack", "obs1", "added"),
            ("slack:U0000000A1", "slack", "obs1", "added"),
        ]

    def test_reupsert_existing_alias_writes_no_duplicate(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(id="e1", type="person", name="Dana Brook", aliases=["U0000000A1"]),
            adapter="slack",
            observation_id="obs1",
        )
        upsert_entity(
            db_conn,
            Entity(id="e1", type="person", name="Dana Brook", aliases=["U0000000A1"]),
            adapter="slack",
            observation_id="obs2",
        )

        assert _alias_provenance(db_conn, "e1") == [("U0000000A1", "slack", "obs1", "added")]

    def test_only_new_alias_recorded_on_update(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(id="e1", type="person", name="Dana Brook", aliases=["U0000000A1"]),
            adapter="slack",
            observation_id="obs1",
        )
        upsert_entity(
            db_conn,
            Entity(id="e1", type="person", name="Dana Brook", aliases=["U0000000A1", "dbrook"]),
            adapter="slack",
            observation_id="obs2",
        )

        assert _alias_provenance(db_conn, "e1") == [
            ("U0000000A1", "slack", "obs1", "added"),
            ("dbrook", "slack", "obs2", "added"),
        ]

    def test_alias_added_to_resolved_entity_recorded_on_that_entity(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(id="e1", type="person", name="Dana Brook", aliases=["U0000000A1"]),
            adapter="slack",
            observation_id="obs1",
        )
        upsert_entity(
            db_conn,
            Entity(id="e2", type="person", name="Dana Brook", aliases=["U0000000A1", "dbrook"]),
            adapter="slack",
            observation_id="obs2",
        )

        assert _alias_provenance(db_conn, "e1") == [
            ("U0000000A1", "slack", "obs1", "added"),
            ("dbrook", "slack", "obs2", "added"),
        ]
        assert _alias_provenance(db_conn, "e2") == []

    def test_no_adapter_writes_no_provenance(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(id="e1", type="person", name="Dana Brook", aliases=["U0000000A1"]),
        )

        assert _alias_provenance(db_conn, "e1") == []

    def test_observation_id_none_recorded_as_null(self, db_conn):
        upsert_entity(
            db_conn,
            Entity(id="e1", type="person", name="Dana Brook", aliases=["U0000000A1"]),
            adapter="slack",
            observation_id=None,
        )

        assert _alias_provenance(db_conn, "e1") == [("U0000000A1", "slack", None, "added")]
