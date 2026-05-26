from __future__ import annotations

import time

from patina.graph import insert_observation
from patina.mcp.tools_catch_up import catch_up, dismiss
from patina.models import Observation
from patina.store import init_db


def test_catch_up_returns_formatted(db_path, db_conn, tmp_path):
    init_db(db_path)
    now = time.time()
    obs = Observation(
        id="o1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=now - 3600,
        sender_entity_id=None,
        text="Test message",
    )
    insert_observation(db_conn, obs)
    db_conn.close()

    result = catch_up(days=3)
    assert isinstance(result, str)
    assert "Needs Action" in result or "New" in result or "Waiting" in result


def test_dismiss_records_decision(db_path, db_conn, tmp_path):
    init_db(db_path)
    obs = Observation(
        id="obs_dismiss",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=time.time(),
        sender_entity_id=None,
        text="Dismiss me",
    )
    insert_observation(db_conn, obs)
    db_conn.close()

    result = dismiss("obs_dismiss")
    assert "Dismissed" in result
