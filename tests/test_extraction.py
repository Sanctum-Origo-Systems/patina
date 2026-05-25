from __future__ import annotations

from patina.extraction import extract_entities_from_text, extract_sender_entity


def test_single_mention():
    entities = extract_entities_from_text("Hey <@U001> check this")
    assert len(entities) == 1
    assert entities[0].type == "person"


def test_multiple_mentions():
    entities = extract_entities_from_text("<@U001> and <@U002> on it")
    people = [e for e in entities if e.type == "person"]
    assert len(people) == 2


def test_channel_reference():
    entities = extract_entities_from_text("See <#C001|general> for details")
    topics = [e for e in entities if e.type == "topic"]
    assert len(topics) == 1
    assert topics[0].name == "general"


def test_url_reference():
    entities = extract_entities_from_text("Check https://example.com/page")
    refs = [e for e in entities if e.type == "reference"]
    assert len(refs) == 1
    assert "example.com" in refs[0].name


def test_plain_text_empty():
    entities = extract_entities_from_text("Just a normal message")
    assert entities == []


def test_sender_entity_with_name():
    e = extract_sender_entity("U001", "Alice")
    assert e.type == "person"
    assert e.name == "Alice"
    assert "U001" in e.aliases


def test_sender_entity_without_name():
    e = extract_sender_entity("U001")
    assert e.name == "U001"


def test_ids_deterministic():
    e1 = extract_sender_entity("U001")
    e2 = extract_sender_entity("U001")
    assert e1.id == e2.id


def test_ids_unique():
    e1 = extract_sender_entity("U001")
    e2 = extract_sender_entity("U002")
    assert e1.id != e2.id
