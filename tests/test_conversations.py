from __future__ import annotations

import time

from patina.conversations import (
    build_checkpoint_summary,
    get_recent_messages,
    prune_conversations,
    store_exchange,
)


def test_store_exchange(db_conn):
    store_exchange(db_conn, "repl", "user1", "user", "hello", timestamp=1000.0)
    row = db_conn.execute("SELECT * FROM conversations").fetchone()
    assert row is not None
    assert row["channel"] == "repl"
    assert row["role"] == "user"
    assert row["content"] == "hello"


def test_get_recent_chronological(db_conn):
    for i in range(5):
        store_exchange(db_conn, "ch1", "u1", "user", f"msg{i}", timestamp=1000.0 + i)

    msgs = get_recent_messages(db_conn, "ch1", limit=5)
    assert len(msgs) == 5
    assert msgs[0]["content"] == "msg0"
    assert msgs[4]["content"] == "msg4"


def test_get_recent_respects_limit(db_conn):
    for i in range(10):
        store_exchange(db_conn, "ch1", "u1", "user", f"msg{i}", timestamp=1000.0 + i)

    msgs = get_recent_messages(db_conn, "ch1", limit=3)
    assert len(msgs) == 3
    assert msgs[0]["content"] == "msg7"


def test_get_recent_filters_by_channel(db_conn):
    store_exchange(db_conn, "ch1", "u1", "user", "in ch1", timestamp=1000.0)
    store_exchange(db_conn, "ch2", "u1", "user", "in ch2", timestamp=1001.0)

    msgs = get_recent_messages(db_conn, "ch1")
    assert len(msgs) == 1
    assert msgs[0]["content"] == "in ch1"


def test_empty_channel_returns_empty(db_conn):
    msgs = get_recent_messages(db_conn, "nonexistent")
    assert msgs == []


def test_prune_removes_old(db_conn):
    old_ts = time.time() - (60 * 86400)
    new_ts = time.time()
    store_exchange(db_conn, "ch1", "u1", "user", "old", timestamp=old_ts)
    store_exchange(db_conn, "ch1", "u1", "user", "new", timestamp=new_ts)

    count = prune_conversations(db_conn, max_age_days=30)
    assert count == 1

    msgs = get_recent_messages(db_conn, "ch1")
    assert len(msgs) == 1
    assert msgs[0]["content"] == "new"


def test_prune_returns_count(db_conn):
    old_ts = time.time() - (60 * 86400)
    for i in range(3):
        store_exchange(db_conn, "ch1", "u1", "user", f"old{i}", timestamp=old_ts + i)

    count = prune_conversations(db_conn, max_age_days=30)
    assert count == 3


def test_checkpoint_summary_with_channel(db_conn):
    for i in range(12):
        store_exchange(db_conn, "repl", "u1", "user", f"msg{i}", timestamp=1000.0 + i)

    summary = build_checkpoint_summary(db_conn, channel="repl")
    assert len(summary["recent_context"]) == 10
    assert "checkpoint_time" in summary


def test_checkpoint_summary_no_channel(db_conn):
    summary = build_checkpoint_summary(db_conn, channel=None)
    assert summary["recent_context"] == []
    assert "checkpoint_time" in summary


def test_checkpoint_summary_respects_cap(db_conn):
    for i in range(20):
        store_exchange(db_conn, "ch1", "u1", "user", f"msg{i}", timestamp=1000.0 + i)

    summary = build_checkpoint_summary(db_conn, channel="ch1")
    assert len(summary["recent_context"]) <= 10
