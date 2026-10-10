from __future__ import annotations

from patina.graph import (
    _name_type_rank,
    count_entities,
    count_observations,
    get_entity,
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
