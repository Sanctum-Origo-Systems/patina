from __future__ import annotations

from patina.extraction import _make_id
from patina.graph import insert_observation, upsert_entity
from patina.models import Entity, Observation
from patina.style.observer import observe_sent_messages


def _setup_user(conn, user_id="user1"):
    e = Entity(id=user_id, type="person", name="Test User")
    upsert_entity(conn, e)
    return user_id


def _add_obs(conn, obs_id, sender_id, text, ts=1.0):
    obs = Observation(
        id=obs_id,
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=ts,
        sender_entity_id=sender_id,
        text=text,
    )
    insert_observation(conn, obs)


def test_returns_sent_messages(db_conn):
    uid = _setup_user(db_conn)
    _add_obs(db_conn, "o1", uid, "Hello <@U002>!", ts=1.0)
    _add_obs(db_conn, "o2", uid, "How are you?", ts=2.0)

    result = observe_sent_messages(db_conn, uid)
    assert len(result) == 2


def test_extracts_recipient_from_mention(db_conn):
    uid = _setup_user(db_conn)
    _add_obs(db_conn, "o1", uid, "Hey <@U002> check this")

    result = observe_sent_messages(db_conn, uid)
    assert result[0].recipient_entity_id == _make_id("person", "U002")


def test_no_recipient_when_no_mention(db_conn):
    uid = _setup_user(db_conn)
    _add_obs(db_conn, "o1", uid, "General announcement")

    result = observe_sent_messages(db_conn, uid)
    assert result[0].recipient_entity_id is None


def test_empty_for_no_messages(db_conn):
    uid = _setup_user(db_conn)
    result = observe_sent_messages(db_conn, uid)
    assert result == []
