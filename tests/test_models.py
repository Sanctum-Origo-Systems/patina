from __future__ import annotations

from patina.models import ChatMessage, Claim, Entity, Observation, Relationship


def test_entity_auto_sets_timestamps():
    e = Entity(id="e1", type="person", name="Alice")
    assert e.first_seen != ""
    assert e.last_seen != ""


def test_entity_preserves_explicit_timestamps():
    e = Entity(
        id="e1",
        type="person",
        name="Alice",
        first_seen="2024-01-01",
        last_seen="2024-06-01",
    )
    assert e.first_seen == "2024-01-01"
    assert e.last_seen == "2024-06-01"


def test_entity_defaults():
    e = Entity(id="e1", type="person", name="Alice")
    assert e.aliases == []
    assert e.metadata == {}
    assert e.decay_rate == 0.02


def test_relationship_auto_sets_timestamps():
    r = Relationship(id="r1", subject_id="a", predicate="works-on", object_id="b")
    assert r.first_seen != ""
    assert r.last_confirmed != ""


def test_claim_defaults():
    c = Claim(id="c1", subject_id="s1", predicate="owns", object="ProjectX")
    assert c.confidence == 0.5
    assert c.decay_rate == 0.02
    assert c.source_ids == []
    assert c.first_asserted != ""


def test_observation_defaults():
    o = Observation(
        id="o1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=None,
        text="hi",
    )
    assert o.processed == 0
    assert o.ingested_at != ""


def test_chat_message_defaults():
    m = ChatMessage(user_id="U1", text="hello", timestamp=1.0, channel_id="C1")
    assert m.thread_id is None
    assert m.is_bot is False
    assert m.reactions == []
    assert m.user_name is None
