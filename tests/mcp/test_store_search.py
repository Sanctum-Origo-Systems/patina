from __future__ import annotations

import time

from patina.graph import insert_observation, upsert_entity
from patina.mcp.tools_catch_up import store_search
from patina.models import Entity, Observation
from patina.store import init_db


def _seed(db_conn, db_path):
    init_db(db_path)
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    upsert_entity(db_conn, Entity(id="e2", type="person", name="Bob"))

    now = time.time()
    msgs = [
        ("o1", "e1", "Check the Neptune proposal for Elevance", now - 3600),
        ("o2", "e2", "SOW is in final review stages", now - 7200),
        ("o3", "e1", "Deploy Neptune to staging today", now - 1800),
        ("o4", "e2", "Meeting about Delivery Agent launch", now - 900),
        ("o5", "e1", "Neptune OpenSearch integration complete", now - 600),
    ]
    for oid, sender, text, ts in msgs:
        obs = Observation(
            id=oid,
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=ts,
            sender_entity_id=sender,
            text=text,
            metadata={"channel_name": "project-alpha"},
        )
        insert_observation(db_conn, obs)
    db_conn.close()


class TestStoreSearch:
    def test_simple_match(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Neptune")
        assert "Neptune" in result
        assert "results for" in result

    def test_no_match(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("xyznonexistent")
        assert "No messages found" in result

    def test_returns_sender_name(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Neptune")
        assert "Alice" in result

    def test_returns_source(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Neptune")
        assert "slack" in result

    def test_returns_date(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Neptune")
        assert "[20" in result

    def test_returns_channel_name(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Neptune")
        assert "project-alpha" in result

    def test_multiple_results(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Neptune")
        assert result.count(">") >= 2

    def test_limit_respected(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Neptune", limit=1)
        lines = [line for line in result.split("\n") if line.startswith(">")]
        assert len(lines) == 1

    def test_limit_capped_at_50(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Neptune", limit=999)
        assert "No messages found" not in result

    def test_text_truncated(self, db_conn, db_path, tmp_path):
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        obs = Observation(
            id="olong",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=time.time(),
            sender_entity_id="e1",
            text="x" * 500,
        )
        insert_observation(db_conn, obs)
        db_conn.close()
        result = store_search("x")
        quoted = [line for line in result.split("\n") if line.startswith(">")]
        assert all(len(line) <= 203 for line in quoted)

    def test_and_search(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Neptune staging")
        assert "staging" in result

    def test_missing_sender_shows_unknown(self, db_conn, db_path, tmp_path):
        init_db(db_path)
        obs = Observation(
            id="o_nosender",
            source="email",
            channel_id="inbox",
            thread_id=None,
            timestamp=time.time(),
            sender_entity_id=None,
            text="Orphan message about Neptune",
        )
        insert_observation(db_conn, obs)
        db_conn.close()
        result = store_search("Neptune")
        assert "unknown" in result

    def test_fts_trigger_on_new_insert(self, db_conn, db_path, tmp_path):
        init_db(db_path)
        obs = Observation(
            id="o_late",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=time.time(),
            sender_entity_id=None,
            text="Unique keyword xyztriggertest",
        )
        insert_observation(db_conn, obs)
        db_conn.close()
        result = store_search("xyztriggertest")
        assert "xyztriggertest" in result


class TestStoreSearchRegistered:
    def test_appears_in_tool_guide(self):
        from patina.agent.runtime import _build_tool_guide

        guide = _build_tool_guide()
        assert "**store_search**" in guide

    def test_docstring_in_guide(self):
        from patina.agent.runtime import _build_tool_guide

        guide = _build_tool_guide()
        assert "Full-text search" in guide
