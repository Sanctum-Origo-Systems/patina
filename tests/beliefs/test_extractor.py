from __future__ import annotations

import json
from unittest.mock import patch

from patina.beliefs.extractor import (
    _is_plausible_person_name,
    _parse_extraction,
    _resolve_entity_id,
    _upsert_entity,
    extract_beliefs,
)
from patina.graph import insert_observation, upsert_entity
from patina.models import Entity, Observation
from patina.owner import mark_entity_as_owner


def test_parse_extraction_valid_json():
    response = (
        '{"claims": [{"subject": "Alice", "predicate": "role",'
        ' "object": "VP"}], "relationships": []}'
    )
    result = _parse_extraction(response)
    assert len(result["claims"]) == 1
    assert result["claims"][0]["subject"] == "Alice"


def test_parse_extraction_markdown_fenced():
    response = '```json\n{"claims": [], "relationships": []}\n```'
    result = _parse_extraction(response)
    assert result["claims"] == []
    assert result["relationships"] == []


def test_parse_extraction_json_in_text():
    response = (
        "Here is the result:\n"
        '{"claims": [{"subject": "X", "predicate": "p",'
        ' "object": "o"}], "relationships": []}\nDone.'
    )
    result = _parse_extraction(response)
    assert len(result["claims"]) == 1


def test_parse_extraction_invalid():
    result = _parse_extraction("This is not JSON at all")
    assert result == {"claims": [], "relationships": []}


def test_resolve_entity_id_found(db_conn):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice Smith"))
    result = _resolve_entity_id(db_conn, "Alice Smith")
    assert result == "e1"


def test_resolve_entity_id_no_substring_match(db_conn):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice Smith"))
    result = _resolve_entity_id(db_conn, "Alice")
    assert result is None


def test_resolve_entity_id_not_found(db_conn):
    result = _resolve_entity_id(db_conn, "Nobody")
    assert result is None


def test_extract_beliefs_no_observations(tmp_path):
    stats = extract_beliefs(home=tmp_path, dry_run=True)
    assert stats["observations_processed"] == 0


def test_extract_beliefs_dry_run(db_conn, db_path, tmp_path):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    obs = Observation(
        id="o1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id="e1",
        text="I am the VP of Engineering",
    )
    insert_observation(db_conn, obs)
    db_conn.close()

    stats = extract_beliefs(home=tmp_path, dry_run=True, batch_size=5)
    assert stats["observations_processed"] == 1
    assert stats["batches_sent"] == 0


def test_extract_beliefs_with_mock_claude(db_conn, db_path, tmp_path):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    obs = Observation(
        id="o1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id="e1",
        text="I am the VP of Engineering",
    )
    insert_observation(db_conn, obs)
    db_conn.close()

    mock_response = (
        '{"entities": [{"name": "Alice", "aliases": [], "type": "person"}], '
        '"claims": [{"subject": "Alice", "predicate": "role", '
        '"object": "VP of Engineering", "confidence": 0.9}], '
        '"relationships": [], "behavioral": []}'
    )
    with patch("patina.beliefs.extractor._call_claude", return_value=mock_response):
        stats = extract_beliefs(home=tmp_path, batch_size=5)

    assert stats["observations_processed"] == 1
    assert stats["claims_extracted"] == 1
    assert stats["batches_sent"] == 1


def test_upsert_entity_creates_new(db_conn):
    entity_id = _upsert_entity(db_conn, "Bob Smith", ["bob"])
    assert entity_id != ""
    resolved = _resolve_entity_id(db_conn, "Bob Smith")
    assert resolved == entity_id


def test_upsert_entity_returns_existing(db_conn):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    entity_id = _upsert_entity(db_conn, "Alice")
    assert entity_id == "e1"


def test_upsert_entity_rejects_non_persons(db_conn):
    assert _upsert_entity(db_conn, "JIRA") == ""
    assert _upsert_entity(db_conn, "AWS/S3") == ""
    assert _upsert_entity(db_conn, "user@example.com") == ""
    assert _upsert_entity(db_conn, "https://zoom.us/j/123") == ""
    assert _upsert_entity(db_conn, "Ab") == ""
    assert _upsert_entity(db_conn, "API") == ""
    assert _upsert_entity(db_conn, "a]b") == ""
    assert _upsert_entity(db_conn, "project(alpha)") == ""


def test_upsert_entity_rejects_empty(db_conn):
    assert _upsert_entity(db_conn, "") == ""


def test_upsert_entity_accepts_real_names(db_conn):
    assert _upsert_entity(db_conn, "Alice Smith") != ""
    assert _upsert_entity(db_conn, "Jean-Pierre") != ""
    assert _upsert_entity(db_conn, "Carol Davis-Jones") != ""


class TestIsPlausiblePersonName:
    def test_valid_names(self):
        assert _is_plausible_person_name("Alice Smith")
        assert _is_plausible_person_name("Bob")
        assert _is_plausible_person_name("Carol Davis-Jones")
        assert _is_plausible_person_name("Jean-Pierre")

    def test_too_short(self):
        assert not _is_plausible_person_name("Ab")
        assert not _is_plausible_person_name("")

    def test_too_long(self):
        assert not _is_plausible_person_name("A" * 51)

    def test_special_chars_rejected(self):
        assert not _is_plausible_person_name("user@corp.com")
        assert not _is_plausible_person_name("slack/channel")
        assert not _is_plausible_person_name("project(alpha)")
        assert not _is_plausible_person_name("[Team Lead]")
        assert not _is_plausible_person_name("role:admin")
        assert not _is_plausible_person_name("v2.0")

    def test_all_caps_rejected(self):
        assert not _is_plausible_person_name("JIRA")
        assert not _is_plausible_person_name("API")
        assert not _is_plausible_person_name("AWS")

    def test_no_uppercase_word_rejected(self):
        assert not _is_plausible_person_name("the meeting")


def test_extract_creates_entities_from_response(db_conn, db_path, tmp_path):
    obs = Observation(
        id="o1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=None,
        text="Bob is the new CTO",
    )
    insert_observation(db_conn, obs)
    db_conn.close()

    mock_response = (
        '{"entities": [{"name": "Bob", "aliases": [], "type": "person"}], '
        '"claims": [{"subject": "Bob", "predicate": "role", '
        '"object": "CTO", "confidence": 0.9}], '
        '"relationships": [], "behavioral": []}'
    )
    with patch("patina.beliefs.extractor._call_claude", return_value=mock_response):
        stats = extract_beliefs(home=tmp_path, batch_size=5)

    assert stats["claims_extracted"] == 1


def test_extract_behavioral_claims(db_conn, db_path, tmp_path):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Carol"))
    obs = Observation(
        id="o1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id="e1",
        text="Carol always responds within 5 minutes",
    )
    insert_observation(db_conn, obs)
    db_conn.close()

    mock_response = (
        '{"entities": [{"name": "Carol", "aliases": [], "type": "person"}], '
        '"claims": [], "relationships": [], '
        '"behavioral": [{"subject": "Carol", '
        '"predicate": "response_pattern", '
        '"object": "responds within 5 minutes", "confidence": 0.8}]}'
    )
    with patch("patina.beliefs.extractor._call_claude", return_value=mock_response):
        stats = extract_beliefs(home=tmp_path, batch_size=5)

    assert stats["claims_extracted"] == 1

    from patina.store import connect, get_db_path

    conn = connect(get_db_path(tmp_path))
    row = conn.execute(
        "SELECT predicate FROM claims WHERE predicate LIKE 'behavioral:%'"
    ).fetchone()
    assert row is not None
    assert row["predicate"] == "behavioral:response_pattern"
    conn.close()


def _make_owner(db_conn, entity_id="owner1", name="Sam Rivera", aliases=None):
    upsert_entity(
        db_conn,
        Entity(id=entity_id, type="person", name=name, aliases=aliases or []),
    )
    mark_entity_as_owner(db_conn, entity_id)
    return entity_id


class TestResolveEntityIdOwner:
    def test_owner_identifier_exact_match(self, db_conn):
        owner_id = _make_owner(db_conn, name="Sam Rivera")
        upsert_entity(
            db_conn,
            Entity(id="e1", type="person", name="Sam Rivera via securemail.example"),
        )
        result = _resolve_entity_id(
            db_conn,
            "Sam Rivera",
            owner_entity_id=owner_id,
            owner_match_names={"sam rivera", "srivera"},
        )
        assert result == owner_id

    def test_owner_identifier_case_insensitive(self, db_conn):
        owner_id = _make_owner(db_conn, name="Sam Rivera")
        result = _resolve_entity_id(
            db_conn,
            "sam rivera",
            owner_entity_id=owner_id,
            owner_match_names={"sam rivera"},
        )
        assert result == owner_id

    def test_partial_name_does_not_match_wrong_entity(self, db_conn):
        _make_owner(db_conn, name="Sam Rivera")
        upsert_entity(
            db_conn,
            Entity(id="e1", type="person", name="Sam Rivera via securemail.example"),
        )
        upsert_entity(db_conn, Entity(id="e2", type="person", name="Lee, Sam"))
        result = _resolve_entity_id(
            db_conn,
            "Sam",
            owner_entity_id="owner1",
            owner_match_names={"sam rivera", "srivera"},
        )
        assert result is None

    def test_different_person_does_not_attach_to_owner(self, db_conn):
        _make_owner(db_conn, name="Sam Rivera")
        upsert_entity(db_conn, Entity(id="e2", type="person", name="Jordan Blake"))
        result = _resolve_entity_id(
            db_conn,
            "Jordan Blake",
            owner_entity_id="owner1",
            owner_match_names={"sam rivera", "srivera"},
        )
        assert result == "e2"

    def test_normalized_name_matches_owner(self, db_conn):
        owner_id = _make_owner(db_conn, name="Sam Rivera")
        result = _resolve_entity_id(
            db_conn,
            "Rivera, Sam",
            owner_entity_id=owner_id,
            owner_match_names={"sam rivera"},
        )
        assert result == owner_id

    def test_no_owner_falls_through_to_graph(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice Smith"))
        result = _resolve_entity_id(db_conn, "Alice Smith")
        assert result == "e1"

    def test_relationship_uses_same_resolver(self, db_conn):
        owner_id = _make_owner(db_conn, name="Sam Rivera")
        upsert_entity(db_conn, Entity(id="e2", type="person", name="Jordan Blake"))
        subj = _resolve_entity_id(
            db_conn,
            "Sam Rivera",
            owner_entity_id=owner_id,
            owner_match_names={"sam rivera"},
        )
        obj = _resolve_entity_id(
            db_conn,
            "Jordan Blake",
            owner_entity_id=owner_id,
            owner_match_names={"sam rivera"},
        )
        assert subj == owner_id
        assert obj == "e2"


class TestExtractBeliefsOwnerResolution:
    def test_claim_attaches_to_owner(self, db_conn, db_path, tmp_path):
        import yaml

        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "owner": {
                        "display_names": ["Sam Rivera"],
                        "handles": ["srivera"],
                    }
                }
            )
        )
        _make_owner(db_conn, name="Sam Rivera")
        upsert_entity(
            db_conn,
            Entity(id="e1", type="person", name="Sam Rivera via securemail.example"),
        )
        obs = Observation(
            id="o1",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=1.0,
            sender_entity_id="e1",
            text="Sam Rivera is based in Springfield",
        )
        insert_observation(db_conn, obs)
        db_conn.close()

        mock_response = json.dumps(
            {
                "entities": [],
                "claims": [
                    {
                        "subject": "Sam Rivera",
                        "predicate": "location",
                        "object": "Springfield",
                        "confidence": 0.9,
                    }
                ],
                "relationships": [],
                "behavioral": [],
            }
        )
        with patch("patina.beliefs.extractor._call_claude", return_value=mock_response):
            stats = extract_beliefs(home=tmp_path, batch_size=5)

        assert stats["claims_extracted"] == 1

        from patina.store import connect, get_db_path

        conn = connect(get_db_path(tmp_path))
        row = conn.execute("SELECT subject_id FROM claims WHERE predicate = 'location'").fetchone()
        assert row is not None
        assert row["subject_id"] == "owner1"
        conn.close()

    def test_skipped_unresolved_counted(self, db_conn, db_path, tmp_path):
        obs = Observation(
            id="o1",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=1.0,
            sender_entity_id=None,
            text="Nobody said something",
        )
        insert_observation(db_conn, obs)
        db_conn.close()

        mock_response = json.dumps(
            {
                "entities": [],
                "claims": [
                    {
                        "subject": "UNKNOWN",
                        "predicate": "role",
                        "object": "CEO",
                        "confidence": 0.9,
                    }
                ],
                "relationships": [],
                "behavioral": [],
            }
        )
        with patch("patina.beliefs.extractor._call_claude", return_value=mock_response):
            stats = extract_beliefs(home=tmp_path, batch_size=5)

        assert stats["skipped_unresolved"] >= 1
        assert stats["claims_extracted"] == 0


class TestNonPersonPhrasesRejected:
    """Regression tests for #346: non-person phrases must not create person entities."""

    def test_is_plausible_rejects_sentences(self):
        assert not _is_plausible_person_name("Offered to connect with Sam")
        assert not _is_plausible_person_name("Has been working on deployment")

    def test_is_plausible_rejects_role_descriptions(self):
        assert not _is_plausible_person_name("TPM for security")
        assert not _is_plausible_person_name("Manager of engineering")

    def test_is_plausible_rejects_phrases_with_prepositions(self):
        assert not _is_plausible_person_name("Lisbon office")
        assert not _is_plausible_person_name("VP of Engineering")

    def test_is_plausible_rejects_long_phrases(self):
        assert not _is_plausible_person_name("Senior VP of Global Engineering Strategy")

    def test_is_plausible_accepts_real_names(self):
        assert _is_plausible_person_name("Alice Smith")
        assert _is_plausible_person_name("Jean-Pierre")
        assert _is_plausible_person_name("Bob")

    def test_claim_subject_resolve_only(self, db_conn, db_path, tmp_path):
        """Claim subjects that don't match an existing entity are skipped, not created."""
        obs = Observation(
            id="o1",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=1.0,
            sender_entity_id=None,
            text="Project Lumen integration is on track",
        )
        insert_observation(db_conn, obs)
        db_conn.close()

        mock_response = json.dumps(
            {
                "entities": [
                    {"name": "Project Lumen", "aliases": [], "type": "project"},
                ],
                "claims": [
                    {
                        "subject": "Project Lumen",
                        "predicate": "status",
                        "object": "on track",
                        "confidence": 0.9,
                    }
                ],
                "relationships": [],
                "behavioral": [],
            }
        )
        with patch("patina.beliefs.extractor._call_claude", return_value=mock_response):
            stats = extract_beliefs(home=tmp_path, batch_size=5)

        assert stats["skipped_unresolved"] >= 1
        assert stats["claims_extracted"] == 0

        from patina.store import connect, get_db_path

        conn = connect(get_db_path(tmp_path))
        row = conn.execute("SELECT * FROM entities WHERE name = 'Project Lumen'").fetchone()
        assert row is None
        conn.close()

    def test_only_person_type_entities_created(self, db_conn, db_path, tmp_path):
        """Entities with type != 'person' in the LLM response must not be created."""
        obs = Observation(
            id="o1",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=1.0,
            sender_entity_id=None,
            text="Alice works at Contoso on Project Lumen",
        )
        insert_observation(db_conn, obs)
        db_conn.close()

        mock_response = json.dumps(
            {
                "entities": [
                    {"name": "Alice", "aliases": [], "type": "person"},
                    {"name": "Contoso", "aliases": [], "type": "organization"},
                    {"name": "Project Lumen", "aliases": [], "type": "project"},
                ],
                "claims": [
                    {
                        "subject": "Alice",
                        "predicate": "org",
                        "object": "Contoso",
                        "confidence": 0.9,
                    }
                ],
                "relationships": [],
                "behavioral": [],
            }
        )
        with patch("patina.beliefs.extractor._call_claude", return_value=mock_response):
            stats = extract_beliefs(home=tmp_path, batch_size=5)

        assert stats["claims_extracted"] == 1

        from patina.store import connect, get_db_path

        conn = connect(get_db_path(tmp_path))
        entities = conn.execute("SELECT name FROM entities").fetchall()
        entity_names = {r["name"] for r in entities}
        assert "Alice" in entity_names
        assert "Contoso" not in entity_names
        assert "Project Lumen" not in entity_names
        conn.close()

    def test_end_to_end_non_person_phrases(self, db_conn, db_path, tmp_path):
        """End-to-end: phrases from the issue examples must not become person entities."""
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Sam Rivera"))
        obs = Observation(
            id="o1",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=1.0,
            sender_entity_id="e1",
            text="Sam Rivera discussed the project integration and Canada expansion",
        )
        insert_observation(db_conn, obs)
        db_conn.close()

        mock_response = json.dumps(
            {
                "entities": [
                    {"name": "Sam Rivera", "aliases": [], "type": "person"},
                ],
                "claims": [
                    {
                        "subject": "Sam Rivera",
                        "predicate": "topic",
                        "object": "project integration",
                        "confidence": 0.8,
                    },
                    {
                        "subject": "Canada expansion team",
                        "predicate": "status",
                        "object": "growing",
                        "confidence": 0.7,
                    },
                ],
                "relationships": [],
                "behavioral": [],
            }
        )
        with patch("patina.beliefs.extractor._call_claude", return_value=mock_response):
            stats = extract_beliefs(home=tmp_path, batch_size=5)

        assert stats["claims_extracted"] == 1
        assert stats["skipped_unresolved"] >= 1

        from patina.store import connect, get_db_path

        conn = connect(get_db_path(tmp_path))
        entities = conn.execute("SELECT name FROM entities").fetchall()
        entity_names = {r["name"] for r in entities}
        assert "Canada expansion team" not in entity_names
        conn.close()


class TestExtractionAliasesPollution:
    """Regression tests for #340: owner aliases must never leak into
    non-owner entities via partial-match resolution."""

    def test_owner_aliases_not_merged_into_colleague(self, db_conn, db_path, tmp_path):
        """Owner is 'Sam Lee' (handle 'slee'), colleague is 'Rivera, Sam'.
        LLM returns {"name": "Sam", "aliases": ["Sam Lee", "slee"]}.
        Owner identifiers must not end up in the colleague's aliases."""
        import yaml

        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.dump(
                {
                    "owner": {
                        "display_names": ["Sam Lee"],
                        "handles": ["slee"],
                    }
                }
            )
        )
        _make_owner(db_conn, name="Sam Lee", aliases=["slee"])
        upsert_entity(
            db_conn,
            Entity(id="colleague1", type="person", name="Rivera, Sam", aliases=["Sam"]),
        )
        obs = Observation(
            id="o1",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=1.0,
            sender_entity_id="colleague1",
            text="Sam mentioned the project deadline",
        )
        insert_observation(db_conn, obs)
        db_conn.close()

        mock_response = json.dumps(
            {
                "entities": [
                    {
                        "name": "Sam",
                        "aliases": ["Sam Lee", "slee"],
                        "type": "person",
                    },
                    {
                        "name": "Rivera, Sam",
                        "aliases": [],
                        "type": "person",
                    },
                ],
                "claims": [
                    {
                        "subject": "Sam Lee",
                        "predicate": "role",
                        "object": "Team Lead",
                        "confidence": 0.9,
                    },
                ],
                "relationships": [],
                "behavioral": [],
            }
        )
        with patch("patina.beliefs.extractor._call_claude", return_value=mock_response):
            extract_beliefs(home=tmp_path, batch_size=5)

        from patina.store import connect, get_db_path

        conn = connect(get_db_path(tmp_path))

        colleague = conn.execute("SELECT aliases FROM entities WHERE id = 'colleague1'").fetchone()
        assert colleague is not None
        colleague_aliases = json.loads(colleague["aliases"] or "[]")
        assert "Sam Lee" not in colleague_aliases
        assert "slee" not in colleague_aliases

        claim = conn.execute("SELECT subject_id FROM claims WHERE predicate = 'role'").fetchone()
        assert claim is not None
        assert claim["subject_id"] == "owner1"
        conn.close()
