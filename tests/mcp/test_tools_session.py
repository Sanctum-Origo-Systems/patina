from __future__ import annotations

from patina.conversations import store_exchange
from patina.mcp.tools_session import recent_messages, session_checkpoint
from patina.store import init_db


def test_recent_messages_returns_string(db_path, db_conn):
    init_db(db_path)
    store_exchange(db_conn, "repl", "u1", "user", "hello")
    store_exchange(db_conn, "repl", "u1", "assistant", "hi there")
    db_conn.close()

    result = recent_messages("repl", limit=5)
    assert isinstance(result, str)
    assert "hello" in result
    assert "hi there" in result


def test_recent_messages_empty_channel(db_path):
    init_db(db_path)
    result = recent_messages("nonexistent")
    assert "No recent messages" in result


def test_recent_messages_respects_limit(db_path, db_conn):
    init_db(db_path)
    for i in range(10):
        store_exchange(db_conn, "ch1", "u1", "user", f"msg{i}", timestamp=1000.0 + i)
    db_conn.close()

    result = recent_messages("ch1", limit=3)
    assert "msg7" in result
    assert "msg0" not in result


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
