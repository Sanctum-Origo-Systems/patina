from __future__ import annotations

import time

import pytest

from patina.graph import insert_observation
from patina.models import Observation
from patina.priority.catch_up import catch_up, priorities
from patina.store import init_db


def _insert_obs(conn, obs_id, text, age_hours):
    now = time.time()
    obs = Observation(
        id=obs_id,
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=now - (age_hours * 3600),
        sender_entity_id=None,
        text=text,
    )
    insert_observation(conn, obs)


def test_returns_three_groups(tmp_path):
    result = catch_up(home=tmp_path)
    assert "needs_action" in result
    assert "new" in result
    assert "waiting" in result


def test_empty_store_returns_empty(tmp_path):
    result = catch_up(home=tmp_path)
    assert result["needs_action"] == []
    assert result["new"] == []
    assert result["waiting"] == []


def test_fresh_items_in_new(db_conn, db_path, tmp_path):
    init_db(db_path)
    _insert_obs(db_conn, "fresh1", "Hello world", age_hours=2)
    db_conn.close()

    result = catch_up(home=tmp_path)
    ids = [i["id"] for i in result["new"]]
    assert "fresh1" in ids


def test_old_items_in_waiting(db_conn, db_path, tmp_path):
    init_db(db_path)
    _insert_obs(db_conn, "old1", "Something from a while ago", age_hours=48)
    db_conn.close()

    result = catch_up(home=tmp_path)
    ids = [i["id"] for i in result["waiting"]]
    assert "old1" in ids


def test_severity_items_in_needs_action(db_conn, db_path, tmp_path):
    init_db(db_path)
    _insert_obs(
        db_conn,
        "sev1",
        "SEV1: production outage on all endpoints",
        age_hours=4,
    )
    db_conn.close()

    result = catch_up(home=tmp_path)
    all_ids = [i["id"] for i in result["needs_action"]] + [i["id"] for i in result["new"]]
    assert "sev1" in all_ids


def test_respects_days_parameter(db_conn, db_path, tmp_path):
    init_db(db_path)
    _insert_obs(db_conn, "recent", "Hello", age_hours=12)
    _insert_obs(db_conn, "old", "Old message", age_hours=96)
    db_conn.close()

    result_1d = catch_up(home=tmp_path, days=1)
    all_1d = result_1d["needs_action"] + result_1d["new"] + result_1d["waiting"]
    ids_1d = [i["id"] for i in all_1d]
    assert "recent" in ids_1d
    assert "old" not in ids_1d


def test_priorities_groups_by_quadrant(db_conn, db_path, tmp_path):
    init_db(db_path)
    _insert_obs(db_conn, "p1", "regular message", age_hours=12)
    db_conn.close()

    result = priorities(home=tmp_path)
    assert "Q1" in result
    assert "Q2" in result
    assert "Q3" in result
    assert "Q4" in result

    all_items = result["Q1"] + result["Q2"] + result["Q3"] + result["Q4"]
    assert len(all_items) >= 1


def _insert_sender(conn, eid, name):
    conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen)"
        " VALUES (?, 'person', ?, '[]', '{}', '2026-01-01', '2026-01-01')",
        (eid, name),
    )
    conn.commit()


def _insert_legacy_obs(conn, obs_id, sender_id, text, age_hours):
    obs = Observation(
        id=obs_id,
        source="email",
        channel_id="inbox",
        thread_id=None,
        timestamp=time.time() - (age_hours * 3600),
        sender_entity_id=sender_id,
        text=text,
    )
    insert_observation(conn, obs)


def _needs_response_by_id(home):
    caught = catch_up(home=home)
    ranked = priorities(home=home)
    items = [i for group in caught.values() for i in group]
    items += [i for group in ranked.values() for i in group]
    result: dict[str, set[bool]] = {}
    for item in items:
        result.setdefault(item["id"], set()).add(item["needs_response"])
    return result


_SHARE_TEXTS = [
    "[Subject: Rowan Pike added you to Q3 roadmap] [Participants: a, b]\nThe quick brown fox",
    '[Subject: Rowan Pike shared "Launch notes" with you] [Participants: a]\nThe quick brown fox',
]


@pytest.mark.parametrize(
    "first",
    [
        _SHARE_TEXTS[0],
        "[Subject: Avery Quill added you to Ops: Q3 - Launch (draft)]\nThe quick brown fox",
        "[Subject: Avery Quill added you to Planning 計画書]\nThe quick brown fox",
    ],
    ids=["share-562", "punctuated-title", "cjk-title"],
)
def test_automated_share_sender_needs_no_response_569(db_conn, tmp_path, first):
    """#569: an address-less share-notification sender never needs a response."""
    _insert_sender(db_conn, "q", "Quillfeather")
    _insert_legacy_obs(db_conn, "s0", "q", first, age_hours=2)
    _insert_legacy_obs(db_conn, "s1", "q", _SHARE_TEXTS[1], age_hours=30)
    db_conn.close()

    assert _needs_response_by_id(tmp_path) == {"s0": {False}, "s1": {False}}


def test_human_sender_still_needs_response_569(db_conn, tmp_path):
    """#569: a human sender with ordinary subjects keeps needs_response true."""
    _insert_sender(db_conn, "d", "Dana")
    _insert_legacy_obs(db_conn, "h0", "d", "Lunch on Friday?", age_hours=2)
    _insert_legacy_obs(db_conn, "h1", "d", "Notes from today", age_hours=30)
    _insert_obs(db_conn, "n0", "Hello world", age_hours=2)
    db_conn.close()

    assert _needs_response_by_id(tmp_path) == {"h0": {True}, "h1": {True}, "n0": {True}}
