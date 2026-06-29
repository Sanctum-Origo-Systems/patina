from __future__ import annotations

from unittest.mock import patch

from patina.beliefs.extractor import (
    _parse_extraction,
    _resolve_entity_id,
    _upsert_entity,
    extract_beliefs,
)
from patina.graph import insert_observation, upsert_entity
from patina.models import Entity, Observation


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


def test_resolve_entity_id_partial(db_conn):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice Smith"))
    result = _resolve_entity_id(db_conn, "Alice")
    assert result == "e1"


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
    assert entity_id is not None
    resolved = _resolve_entity_id(db_conn, "Bob Smith")
    assert resolved == entity_id


def test_upsert_entity_returns_existing(db_conn):
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    entity_id = _upsert_entity(db_conn, "Alice")
    assert entity_id == "e1"


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
