from __future__ import annotations

import time

from patina.graph import insert_observation, upsert_entity
from patina.mcp.tools_catch_up import _sanitize_fts_query, store_search
from patina.models import Entity, Observation
from patina.store import init_db


def _seed(db_conn, db_path):
    init_db(db_path)
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    upsert_entity(db_conn, Entity(id="e2", type="person", name="Bob"))

    now = time.time()
    msgs = [
        ("o1", "e1", "Check the Atlas proposal for Acme Corp", now - 3600),
        ("o2", "e2", "Contract is in final review stages", now - 7200),
        ("o3", "e1", "Deploy Atlas to staging today", now - 1800),
        ("o4", "e2", "Meeting about dashboard launch", now - 900),
        ("o5", "e1", "Atlas search integration complete", now - 600),
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
        result = store_search("Atlas")
        assert "Atlas" in result
        assert "results for" in result

    def test_no_match(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("xyznonexistent")
        assert "No messages found" in result

    def test_returns_sender_name(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Atlas")
        assert "Alice" in result

    def test_returns_source(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Atlas")
        assert "slack" in result

    def test_returns_date(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Atlas")
        assert "[20" in result

    def test_returns_channel_name(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Atlas")
        assert "project-alpha" in result

    def test_multiple_results(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Atlas")
        assert result.count(">") >= 2

    def test_limit_respected(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Atlas", limit=1)
        lines = [line for line in result.split("\n") if line.startswith(">")]
        assert len(lines) == 1

    def test_limit_capped_at_50(self, db_conn, db_path, tmp_path):
        _seed(db_conn, db_path)
        result = store_search("Atlas", limit=999)
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
        result = store_search("Atlas staging")
        assert "staging" in result

    def test_non_adjacent_keywords(self, db_conn, db_path, tmp_path):
        """Multi-word query finds docs where terms appear non-adjacently."""
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        obs = Observation(
            id="o_nonadj",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=time.time(),
            sender_entity_id="e1",
            text="Things stalled on the security side",
            metadata={"channel_name": "general"},
        )
        insert_observation(db_conn, obs)
        db_conn.close()
        result = store_search("stalled security")
        assert "stalled" in result
        assert "security" in result

    def test_missing_sender_shows_unknown(self, db_conn, db_path, tmp_path):
        init_db(db_path)
        obs = Observation(
            id="o_nosender",
            source="email",
            channel_id="inbox",
            thread_id=None,
            timestamp=time.time(),
            sender_entity_id=None,
            text="Orphan message about Atlas",
        )
        insert_observation(db_conn, obs)
        db_conn.close()
        result = store_search("Atlas")
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


class TestStoreSearchSenderMatch:
    def test_finds_messages_by_sender_name(self, db_conn, db_path, tmp_path):
        """Searching 'Alice' should find messages sent BY Alice,
        even if her name doesn't appear in the message text."""
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        now = time.time()
        obs = Observation(
            id="o1",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=now,
            sender_entity_id="e1",
            text="The quarterly report is ready",
        )
        insert_observation(db_conn, obs)
        db_conn.close()
        result = store_search("Alice")
        assert "quarterly report" in result
        assert "Alice" in result

    def test_sender_match_deduplicates(self, db_conn, db_path, tmp_path):
        """A message mentioning Alice AND sent by Alice should appear once."""
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        now = time.time()
        obs = Observation(
            id="o1",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=now,
            sender_entity_id="e1",
            text="Alice here, confirming the plan",
        )
        insert_observation(db_conn, obs)
        db_conn.close()
        result = store_search("Alice")
        assert result.count("confirming the plan") == 1

    def test_sender_match_via_alias(self, db_conn, db_path, tmp_path):
        """Searching by alias should also find messages by that sender."""
        init_db(db_path)
        upsert_entity(
            db_conn,
            Entity(id="e1", type="person", name="Alice Smith", aliases=["asmith"]),
        )
        now = time.time()
        obs = Observation(
            id="o1",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=now,
            sender_entity_id="e1",
            text="Updated the dashboard metrics",
        )
        insert_observation(db_conn, obs)
        db_conn.close()
        result = store_search("asmith")
        assert "dashboard metrics" in result

    def test_combines_fts_and_sender_results(self, db_conn, db_path, tmp_path):
        """Should return both FTS matches and sender matches."""
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        upsert_entity(db_conn, Entity(id="e2", type="person", name="Bob"))
        now = time.time()
        obs1 = Observation(
            id="o1",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=now - 3600,
            sender_entity_id="e2",
            text="Hey Alice, check the report",
        )
        obs2 = Observation(
            id="o2",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=now,
            sender_entity_id="e1",
            text="The deployment is complete",
        )
        insert_observation(db_conn, obs1)
        insert_observation(db_conn, obs2)
        db_conn.close()
        result = store_search("Alice")
        assert "check the report" in result
        assert "deployment is complete" in result

    def test_no_sender_match_for_nonexistent_entity(self, db_conn, db_path, tmp_path):
        init_db(db_path)
        obs = Observation(
            id="o1",
            source="slack",
            channel_id="C1",
            thread_id=None,
            timestamp=time.time(),
            sender_entity_id=None,
            text="Random message",
        )
        insert_observation(db_conn, obs)
        db_conn.close()
        result = store_search("NonexistentPerson")
        assert "No messages found" in result


class TestSanitizeFtsQuery:
    def test_wraps_plain_query(self):
        assert _sanitize_fts_query("hello") == '"hello"'

    def test_escapes_colon(self):
        assert _sanitize_fts_query("re:Invent") == '"re:Invent"'

    def test_escapes_embedded_quotes(self):
        assert _sanitize_fts_query('say "hi"') == '"say" AND """hi"""'

    def test_empty_string(self):
        assert _sanitize_fts_query("") == '""'

    def test_multi_word_produces_per_term_quoting(self):
        assert _sanitize_fts_query("stalled security") == '"stalled" AND "security"'

    def test_multi_word_with_colon(self):
        assert _sanitize_fts_query("re:Invent talk") == '"re:Invent" AND "talk"'

    def test_fts_operators_quoted_per_term(self):
        assert _sanitize_fts_query("cats AND dogs") == '"cats" AND "AND" AND "dogs"'

    def test_or_join(self):
        assert _sanitize_fts_query("stalled security", join="OR") == '"stalled" OR "security"'


class TestStoreSearchSpecialChars:
    """Queries with FTS5 special characters must not crash."""

    def _seed_special(self, db_conn, db_path):
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        now = time.time()
        msgs = [
            ("s1", "e1", "Join us at re:Invent for the SDLC talk", now - 3600),
            ("s2", "e1", "Subject: (urgent) deploy by EOD", now - 1800),
            ("s3", "e1", 'She said "hello world" to the team', now - 900),
            ("s4", "e1", "non-blocking review needed ASAP", now - 600),
            ("s5", "e1", "Use the wildcard* search feature", now - 300),
        ]
        for oid, sender, text, ts in msgs:
            obs = Observation(
                id=oid,
                source="email",
                channel_id="inbox",
                thread_id=None,
                timestamp=ts,
                sender_entity_id=sender,
                text=text,
                metadata={},
            )
            insert_observation(db_conn, obs)
        db_conn.close()

    def test_colon_in_query(self, db_conn, db_path, tmp_path):
        self._seed_special(db_conn, db_path)
        result = store_search("re:Invent")
        assert "re:Invent" in result
        assert "results for" in result

    def test_parentheses_in_query(self, db_conn, db_path, tmp_path):
        self._seed_special(db_conn, db_path)
        result = store_search("(urgent)")
        assert "urgent" in result

    def test_quotes_in_query(self, db_conn, db_path, tmp_path):
        self._seed_special(db_conn, db_path)
        result = store_search('"hello world"')
        assert "hello world" in result

    def test_hyphen_in_query(self, db_conn, db_path, tmp_path):
        self._seed_special(db_conn, db_path)
        result = store_search("non-blocking")
        assert "non-blocking" in result

    def test_asterisk_in_query(self, db_conn, db_path, tmp_path):
        self._seed_special(db_conn, db_path)
        result = store_search("wildcard*")
        assert "wildcard" in result

    def test_fts_keyword_and(self, db_conn, db_path, tmp_path):
        self._seed_special(db_conn, db_path)
        result = store_search("AND")
        assert "No messages found" in result or "results for" in result

    def test_fts_keyword_or(self, db_conn, db_path, tmp_path):
        self._seed_special(db_conn, db_path)
        result = store_search("OR")
        assert "No messages found" in result or "results for" in result

    def test_fts_keyword_not(self, db_conn, db_path, tmp_path):
        self._seed_special(db_conn, db_path)
        result = store_search("NOT")
        assert "No messages found" in result or "results for" in result


class TestStoreSearchRegistered:
    def test_appears_in_tool_guide(self):
        from patina.agent.runtime import _build_tool_guide

        guide = _build_tool_guide()
        assert "**store_search**" in guide

    def test_docstring_in_guide(self):
        from patina.agent.runtime import _build_tool_guide

        guide = _build_tool_guide()
        assert "Full-text search" in guide
