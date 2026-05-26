from __future__ import annotations

from patina.autonomy.levels import (
    advance_level,
    can_advance,
    current_level,
    freeze_advancement,
    is_frozen,
    level_description,
    set_level,
)
from patina.graph import insert_observation
from patina.models import Observation


def test_default_level_is_0(db_conn):
    assert current_level(db_conn) == 0


def test_cannot_advance_without_data(db_conn):
    can, reason = can_advance(db_conn, 0)
    assert can is False
    assert "No observations" in reason


def test_can_advance_0_to_1_with_observations(db_conn):
    obs = Observation(
        id="o1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=None,
        text="hello",
    )
    insert_observation(db_conn, obs)
    can, reason = can_advance(db_conn, 0)
    assert can is True


def test_advance_level(db_conn):
    obs = Observation(
        id="o1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=None,
        text="hello",
    )
    insert_observation(db_conn, obs)
    new = advance_level(db_conn)
    assert new == 1
    assert current_level(db_conn) == 1


def test_freeze_blocks_advancement(db_conn):
    obs = Observation(
        id="o1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1.0,
        sender_entity_id=None,
        text="hello",
    )
    insert_observation(db_conn, obs)

    freeze_advancement(db_conn)
    assert is_frozen(db_conn) is True

    can, reason = can_advance(db_conn, 0)
    assert can is False
    assert "frozen" in reason.lower()


def test_set_level(db_conn):
    set_level(db_conn, 3)
    assert current_level(db_conn) == 3


def test_level_descriptions_all_defined():
    for level in range(7):
        desc = level_description(level)
        assert len(desc) > 0
        assert "Unknown" not in desc
