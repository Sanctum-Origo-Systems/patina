from __future__ import annotations

import json
import time

from patina.autonomy.actions import approve_action, reject_action
from patina.decisions import get_act_on_rate
from patina.graph import upsert_entity
from patina.mcp.tools_style import draft_reply, style_show
from patina.models import Entity
from patina.store import connect, init_db

_PENDING_QUERY = (
    "SELECT * FROM action_queue WHERE action_type = 'draft_reply' AND status = 'proposed'"
)


def _insert_observation(conn, obs_id, entity_id, text):
    conn.execute(
        """INSERT INTO observations
           (id, source, timestamp, sender_entity_id,
            text, metadata, ingested_at, processed)
           VALUES (?, 'test', ?, ?, ?, '{}',
                   '2024-01-01T00:00:00', 0)""",
        (obs_id, time.time(), entity_id, text),
    )
    conn.commit()


def _insert_style_profile(conn, entity_id, profile_dict):
    from datetime import UTC, datetime

    conn.execute(
        """INSERT OR REPLACE INTO style_profiles
           (entity_id, profile, sample_count, last_updated)
           VALUES (?, ?, ?, ?)""",
        (
            entity_id,
            json.dumps(profile_dict),
            10,
            datetime.now(UTC).isoformat(),
        ),
    )
    conn.commit()


def test_style_show_no_profile(db_path, db_conn, tmp_path):
    init_db(db_path)
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
    db_conn.close()

    result = style_show("Alice")
    assert isinstance(result, str)
    assert "No style profile" in result or "Alice" in result


def test_draft_reply_returns_string(db_path, db_conn, tmp_path):
    init_db(db_path)
    upsert_entity(db_conn, Entity(id="e1", type="person", name="Bob"))
    db_conn.close()

    result = draft_reply("Bob", "follow up on project")
    assert isinstance(result, str)
    assert "Bob" in result


class TestDraftReply:
    def test_returns_context_not_mock(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        db_conn.close()
        result = draft_reply("Alice", "follow up on timeline")
        assert "Draft a reply to Alice" in result
        assert "follow up on timeline" in result

    def test_includes_recipient_style(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        _insert_style_profile(db_conn, "e1", {"formality": 0.8, "avg_length": 45})
        db_conn.close()
        result = draft_reply("Alice", "check in")
        assert "formality" in result
        assert "0.8" in result

    def test_no_profile_says_unavailable(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        db_conn.close()
        result = draft_reply("Alice", "hello")
        assert "no style profile available" in result

    def test_includes_user_style_when_owner_exists(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        db_conn.execute(
            """INSERT INTO entities
               (id, type, name, aliases, metadata, first_seen, last_seen,
                decay_rate, is_owner)
               VALUES ('owner1', 'person', 'Owner', '[]', '{}',
                       '2024-01-01', '2024-01-01', 0.02, 1)"""
        )
        db_conn.commit()
        _insert_style_profile(db_conn, "owner1", {"formality": 0.3, "avg_length": 80})
        db_conn.close()
        result = draft_reply("Alice", "update")
        assert "Your communication style" in result
        assert "0.3" in result

    def test_no_user_profile_omits_section(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        db_conn.close()
        result = draft_reply("Alice", "hello")
        assert "Your communication style" not in result

    def test_entity_not_found(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        result = draft_reply("Nobody", "hello")
        assert "No entity found" in result

    def test_includes_tone_instruction(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        db_conn.close()
        result = draft_reply("Alice", "hello")
        assert "Match their formality" in result

    def test_partial_name_match(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice Smith"))
        db_conn.close()
        result = draft_reply("Alice", "hello")
        assert "Alice Smith" in result

    def test_draft_reply_populates_action_queue(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Corinne"))
        _insert_observation(db_conn, "obs1", "e1", "hello from Corinne")
        db_conn.close()

        draft_reply("Corinne", "follow up on project")

        conn = connect(db_path)
        try:
            rows = conn.execute(_PENDING_QUERY).fetchall()
            assert len(rows) >= 1
            assert rows[0]["target_entity_id"] == "e1"
            assert rows[0]["target_observation_id"] == "obs1"
        finally:
            conn.close()


class TestDraftReplyEndToEnd:
    def test_approve_path(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Teodora"))
        _insert_observation(db_conn, "obs1", "e1", "message from Teodora")
        db_conn.close()

        draft_reply("Teodora", "check in about timeline")

        conn = connect(db_path)
        try:
            row = conn.execute(_PENDING_QUERY).fetchone()
            assert row is not None
            action_id = row["id"]

            result = approve_action(conn, action_id)
            assert result is True

            decision = conn.execute(
                "SELECT * FROM decisions WHERE observation_id = 'obs1' AND action = 'acted'",
            ).fetchone()
            assert decision is not None

            rate = get_act_on_rate(conn)
            assert isinstance(rate, float)
            assert rate == 1.0
        finally:
            conn.close()

    def test_reject_path(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Marisol"))
        _insert_observation(db_conn, "obs1", "e1", "message from Marisol")
        db_conn.close()

        draft_reply("Marisol", "follow up")

        conn = connect(db_path)
        try:
            row = conn.execute(_PENDING_QUERY).fetchone()
            assert row is not None
            action_id = row["id"]

            result = reject_action(conn, action_id)
            assert result is True

            decision = conn.execute(
                "SELECT * FROM decisions WHERE observation_id = 'obs1' AND action = 'rejected'",
            ).fetchone()
            assert decision is not None

            rate = get_act_on_rate(conn)
            assert isinstance(rate, float)
            assert rate == 0.0
        finally:
            conn.close()

    def test_mixed_approve_reject_rate(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Kazuki"))
        _insert_observation(db_conn, "obs1", "e1", "first message")
        _insert_observation(db_conn, "obs2", "e1", "second message")
        db_conn.close()

        draft_reply("Kazuki", "first reply")
        conn = connect(db_path)
        try:
            a1 = conn.execute(_PENDING_QUERY).fetchone()
            approve_action(conn, a1["id"])
        finally:
            conn.close()

        draft_reply("Kazuki", "second reply")
        conn = connect(db_path)
        try:
            a2 = conn.execute(_PENDING_QUERY).fetchone()
            reject_action(conn, a2["id"])

            rate = get_act_on_rate(conn)
            assert isinstance(rate, float)
            assert rate == 0.5
        finally:
            conn.close()
