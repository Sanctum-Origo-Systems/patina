from __future__ import annotations

import time

from patina.graph import insert_observation
from patina.mcp.tools_catch_up import (
    _format_item,
    _sanitize_fts_query,
    catch_up,
    dismiss,
    store_search,
)
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


def _item(**overrides) -> dict:
    item = {
        "staleness_days": 0.5,
        "text": "The quick brown fox — café update",
        "quadrant": "Q1",
        "sender_name": "Jordan Example",
        "source": "outlook_mcp_email",
        "permalink": "",
    }
    item.update(overrides)
    return item


def test_format_item_missing_sender_is_unknown():
    """#666: a missing or ``None`` sender shows 'unknown'; only ``""`` shows 'none'."""
    assert "**unknown**" in _format_item(_item(sender_name=None))
    assert "**unknown**" in _format_item(_without_key(_item(), "sender_name"))
    assert "**none**" in _format_item(_item(sender_name=""))
    assert "**Jordan Example**" in _format_item(_item())


def test_format_item_missing_source_is_unknown_not_omitted():
    """#666: no permalink and no source -> 'via unknown', never left out."""
    assert _format_item(_item()).endswith(" via outlook mcp email")
    assert _format_item(_item(source=None)).endswith(" via unknown")
    assert _format_item(_without_key(_item(), "source")).endswith(" via unknown")
    assert _format_item(_item(source="")).endswith(" via none")


def test_format_item_permalink_is_the_provenance():
    line = _format_item(_item(source=None, permalink="https://example.com/p/1"))
    assert "[Jordan Example](https://example.com/p/1)" in line
    assert " via " not in line


def _without_key(item: dict, key: str) -> dict:
    return {k: v for k, v in item.items() if k != key}


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


# --- _sanitize_fts_query ---


def test_sanitize_fts_query_single_term():
    assert _sanitize_fts_query("fox") == '"fox"'


def test_sanitize_fts_query_and_join():
    assert _sanitize_fts_query("quick fox", join="AND") == '"quick" AND "fox"'


def test_sanitize_fts_query_or_join():
    assert _sanitize_fts_query("quick fox", join="OR") == '"quick" OR "fox"'


def test_sanitize_fts_query_empty():
    assert _sanitize_fts_query("") == '""'


def test_sanitize_fts_query_escapes_quotes():
    result = _sanitize_fts_query('say "hello"', join="AND")
    assert '""hello""' in result


# --- store_search AND→OR fallback ---


def _insert_fox_message(db_conn):
    obs = Observation(
        id="obs_fox",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=time.time(),
        sender_entity_id=None,
        text="the quick brown fox jumps over the lazy dog",
    )
    insert_observation(db_conn, obs)
    db_conn.commit()


def test_store_search_single_term(db_path, db_conn):
    _insert_fox_message(db_conn)
    db_conn.close()
    result = store_search("fox")
    assert "quick brown fox" in result


def test_store_search_all_terms_present_uses_and(db_path, db_conn):
    _insert_fox_message(db_conn)
    db_conn.close()
    result = store_search("quick brown fox")
    assert "quick brown fox" in result


def test_store_search_multiword_with_missing_terms_falls_back_to_or(db_path, db_conn):
    _insert_fox_message(db_conn)
    db_conn.close()
    result = store_search("quick brown fox unicorn dragon")
    assert "quick brown fox" in result
    assert "No messages found" not in result


def test_store_search_no_matching_terms(db_path, db_conn):
    _insert_fox_message(db_conn)
    db_conn.close()
    result = store_search("unicorn dragon")
    assert "No messages found" in result


def test_store_search_or_fallback_ranks_best_match_first(db_path, db_conn):
    obs1 = Observation(
        id="obs_rank1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=time.time(),
        sender_entity_id=None,
        text="the quick brown fox jumps over the lazy dog",
    )
    obs2 = Observation(
        id="obs_rank2",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=time.time(),
        sender_entity_id=None,
        text="a completely unrelated topic about cooking recipes",
    )
    insert_observation(db_conn, obs1)
    insert_observation(db_conn, obs2)
    db_conn.commit()
    db_conn.close()

    result = store_search("quick animal jumping sleeping pet fox")
    assert "quick brown fox" in result
    lines = result.split("\n")
    fox_idx = next(i for i, line in enumerate(lines) if "quick brown fox" in line)
    cooking_present = any("cooking" in line for line in lines)
    assert not cooking_present or fox_idx < next(
        i for i, line in enumerate(lines) if "cooking" in line
    )
