from __future__ import annotations

import time

from patina.conversations import store_exchange
from patina.graph import insert_observation, upsert_entity
from patina.mcp.tools_catch_up import store_search
from patina.mcp.tools_session import recent_messages, session_checkpoint
from patina.models import Entity, Observation
from patina.store import init_db


def _ingest_observation(db_conn, obs_id, channel_id, sender_id, text, ts=None):
    obs = Observation(
        id=obs_id,
        source="slack",
        channel_id=channel_id,
        thread_id=None,
        timestamp=ts or time.time(),
        sender_entity_id=sender_id,
        text=text,
    )
    insert_observation(db_conn, obs)


def test_recent_messages_returns_string(db_path, db_conn):
    init_db(db_path)
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    _ingest_observation(db_conn, "o1", "C1", "e1", "hello")
    _ingest_observation(db_conn, "o2", "C1", "e1", "hi there")
    db_conn.close()

    result = recent_messages("C1", limit=5)
    assert isinstance(result, str)
    assert "hello" in result
    assert "hi there" in result


def test_recent_messages_empty_channel(db_path):
    init_db(db_path)
    result = recent_messages("nonexistent")
    assert "No recent messages" in result


def test_recent_messages_respects_limit(db_path, db_conn):
    init_db(db_path)
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    for i in range(10):
        _ingest_observation(db_conn, f"o{i}", "C1", "e1", f"msg{i}", ts=1000.0 + i)
    db_conn.close()

    result = recent_messages("C1", limit=3)
    assert "msg7" in result
    assert "msg0" not in result


def test_recent_messages_reads_observations(db_path, db_conn):
    """Ingested observation is returned by both store_search and recent_messages."""
    init_db(db_path)
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Fabian"))
    _ingest_observation(db_conn, "o1", "C123", "e1", "quarterly review notes")
    db_conn.close()

    search_result = store_search("quarterly review")
    assert "quarterly review" in search_result

    messages_result = recent_messages("C123")
    assert "quarterly review" in messages_result


def test_recent_messages_alias_resolves_to_channel_id(db_path, db_conn):
    """Watched-channel alias returns the same messages as the raw channel_id."""
    init_db(db_path)
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Greta"))
    _ingest_observation(db_conn, "o1", "C456", "e1", "sprint planning update")

    from datetime import UTC, datetime

    db_conn.execute(
        "INSERT INTO watched_channels (channel_id, channel_name, reason, added_at)"
        " VALUES (?, ?, ?, ?)",
        ("C456", "team-standup", "daily sync", datetime.now(UTC).isoformat()),
    )
    db_conn.commit()
    db_conn.close()

    by_id = recent_messages("C456")
    by_alias = recent_messages("team-standup")
    assert "sprint planning" in by_id
    assert "sprint planning" in by_alias


def test_checkpoint_writes_journal(db_path):
    init_db(db_path)
    result = session_checkpoint(decisions=["decided to ship v2"])
    assert "Checkpoint saved" in result


def test_checkpoint_includes_decisions(db_path, db_conn):
    init_db(db_path)
    session_checkpoint(decisions=["decided X", "decided Y"])

    from patina.store import connect, get_db_path

    conn = connect(get_db_path())
    row = conn.execute("SELECT body FROM journal WHERE entry_type = 'session_end'").fetchone()
    assert row is not None
    assert "decided X" in row["body"]
    assert "decided Y" in row["body"]
    conn.close()


def test_checkpoint_includes_open_threads(db_path):
    init_db(db_path)
    session_checkpoint(open_threads=["thread A pending"])

    from patina.store import connect, get_db_path

    conn = connect(get_db_path())
    row = conn.execute("SELECT body FROM journal WHERE entry_type = 'session_end'").fetchone()
    assert "thread A pending" in row["body"]
    conn.close()


def test_checkpoint_minimal(db_path):
    init_db(db_path)
    result = session_checkpoint()
    assert "Checkpoint saved" in result


def test_checkpoint_includes_recent_context(db_path, db_conn):
    init_db(db_path)
    store_exchange(db_conn, "repl", "u1", "user", "what about the migration?")
    store_exchange(db_conn, "repl", "u1", "assistant", "migration is on track")
    db_conn.close()

    session_checkpoint(channel="repl")

    from patina.store import connect, get_db_path

    conn = connect(get_db_path())
    row = conn.execute("SELECT body FROM journal WHERE entry_type = 'session_end'").fetchone()
    assert "migration" in row["body"]
    conn.close()
