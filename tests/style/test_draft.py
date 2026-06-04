from __future__ import annotations

from patina.graph import upsert_entity
from patina.llm import MockLLM
from patina.models import Entity
from patina.style.draft import generate_draft, load_style_profile


def test_load_style_profile_none(db_conn):
    result = load_style_profile(db_conn, "nonexistent")
    assert result is None


def test_load_style_profile_exists(db_conn):
    from datetime import UTC, datetime

    upsert_entity(db_conn, Entity(id="e1", type="person", name="Test"))
    now = datetime.now(UTC).isoformat()
    db_conn.execute(
        """INSERT INTO style_profiles (entity_id, profile, sample_count, last_updated)
           VALUES (?, ?, ?, ?)""",
        ("e1", '{"greeting": "hi"}', 5, now),
    )
    db_conn.commit()

    result = load_style_profile(db_conn, "e1")
    assert result == '{"greeting": "hi"}'


def test_generate_draft_returns_string(db_conn):
    e = Entity(id="recipient1", type="person", name="Bob")
    upsert_entity(db_conn, e)

    llm = MockLLM()
    result = generate_draft(
        context="Follow up on the project timeline",
        recipient_entity_id="recipient1",
        llm=llm,
        conn=db_conn,
    )
    assert isinstance(result, str)
    assert len(result) > 0


def test_draft_includes_recipient_in_llm_call(db_conn):
    e = Entity(id="recipient1", type="person", name="Bob")
    upsert_entity(db_conn, e)

    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    db_conn.execute(
        """INSERT INTO style_profiles (entity_id, profile, sample_count, last_updated)
           VALUES (?, ?, ?, ?)""",
        ("recipient1", '{"greeting": "hey", "formality": 0.3}', 10, now),
    )
    db_conn.commit()

    llm = MockLLM()
    generate_draft(
        context="Meeting follow-up",
        recipient_entity_id="recipient1",
        llm=llm,
        conn=db_conn,
    )

    assert len(llm.calls) == 1
    call = llm.calls[0]
    assert call["method"] == "draft"
    assert "greeting" in call["recipient_profile"]


def test_draft_fallback_no_profile(db_conn):
    e = Entity(id="recipient1", type="person", name="Bob")
    upsert_entity(db_conn, e)

    llm = MockLLM()
    result = generate_draft(
        context="Hello",
        recipient_entity_id="recipient1",
        llm=llm,
        conn=db_conn,
    )
    assert isinstance(result, str)


def test_draft_uses_owner_style(db_conn):
    from patina.owner import mark_entity_as_owner

    owner = Entity(id="owner1", type="person", name="Me")
    upsert_entity(db_conn, owner)
    mark_entity_as_owner(db_conn, "owner1")

    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    db_conn.execute(
        """INSERT INTO style_profiles (entity_id, profile, sample_count, last_updated)
           VALUES (?, ?, ?, ?)""",
        ("owner1", '{"greeting": "hey", "formality": 0.2}', 10, now),
    )
    db_conn.commit()

    recipient = Entity(id="r1", type="person", name="Alice")
    upsert_entity(db_conn, recipient)

    llm = MockLLM()
    generate_draft(context="follow up", recipient_entity_id="r1", llm=llm, conn=db_conn)

    assert len(llm.calls) == 1
    assert "formality" in llm.calls[0]["style_profile"]
