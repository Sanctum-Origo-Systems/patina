from __future__ import annotations

import json

from patina.extraction import _make_id
from patina.graph import insert_observation, upsert_entity
from patina.models import Entity, Observation
from patina.style.consolidator import build_all_profiles, consolidate_profile
from patina.style.observer import StyleObservation


def test_consolidate_multiple_messages():
    obs = [
        StyleObservation(
            sender_entity_id="u1",
            recipient_entity_id="u2",
            text="Hi there, how are you?",
            timestamp=1.0,
            channel_name="general",
        ),
        StyleObservation(
            sender_entity_id="u1",
            recipient_entity_id="u2",
            text="Thanks for the update!",
            timestamp=2.0,
            channel_name="general",
        ),
    ]
    profile_json = consolidate_profile(obs)
    data = json.loads(profile_json)
    assert "avg_length" in data
    assert "greeting" in data
    assert "sign_off" in data
    assert "formality" in data
    assert "sample_count" in data
    assert data["sample_count"] == 2


def test_profile_json_has_expected_fields():
    obs = [
        StyleObservation(
            sender_entity_id="u1",
            recipient_entity_id=None,
            text="Hello world",
            timestamp=1.0,
            channel_name="general",
        ),
    ]
    profile_json = consolidate_profile(obs)
    data = json.loads(profile_json)
    expected_keys = {
        "avg_length",
        "greeting",
        "sign_off",
        "formality",
        "emoji_rate",
        "question_rate",
        "sample_count",
    }
    assert set(data.keys()) == expected_keys


def test_build_all_profiles(db_conn):
    e = Entity(id="sender1", type="person", name="Alice")
    upsert_entity(db_conn, e)
    e2 = Entity(id=_make_id("person", "U002"), type="person", name="Bob")
    upsert_entity(db_conn, e2)

    for i in range(3):
        obs = Observation(
            id=f"obs{i}",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=float(i),
            sender_entity_id="sender1",
            text=f"Hello <@U002> message {i}",
        )
        insert_observation(db_conn, obs)

    count = build_all_profiles(db_conn, "sender1")
    assert count >= 1

    row = db_conn.execute(
        "SELECT profile FROM style_profiles WHERE entity_id = 'sender1'"
    ).fetchone()
    assert row is not None
    data = json.loads(row["profile"])
    assert data["sample_count"] == 3


def test_build_updates_existing(db_conn):
    e = Entity(id="sender1", type="person", name="Alice")
    upsert_entity(db_conn, e)

    obs = Observation(
        id="obs0",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id="sender1",
        text="Hello",
    )
    insert_observation(db_conn, obs)

    build_all_profiles(db_conn, "sender1")
    build_all_profiles(db_conn, "sender1")

    rows = db_conn.execute(
        "SELECT COUNT(*) AS c FROM style_profiles WHERE entity_id = 'sender1'"
    ).fetchone()
    assert rows["c"] == 1


def test_build_skips_deleted_recipient(db_conn):
    sender = Entity(id="sender1", type="person", name="Alice")
    upsert_entity(db_conn, sender)
    recipient = Entity(id=_make_id("person", "U099"), type="person", name="Deleted Bob")
    upsert_entity(db_conn, recipient)

    for i in range(3):
        obs = Observation(
            id=f"obs{i}",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=float(i),
            sender_entity_id="sender1",
            text=f"Hey <@U099> message {i}",
        )
        insert_observation(db_conn, obs)

    db_conn.execute("DELETE FROM entities WHERE id = ?", (recipient.id,))
    db_conn.commit()

    count = build_all_profiles(db_conn, "sender1")
    assert count == 1

    row = db_conn.execute(
        "SELECT entity_id FROM style_profiles WHERE entity_id = ?",
        (recipient.id,),
    ).fetchone()
    assert row is None
