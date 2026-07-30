from __future__ import annotations

import time

from patina.ingest import ingest_live
from patina.mcp.tools_catch_up import (
    channel_list_watched,
    channel_unwatch,
    channel_watch,
    sender_list_watched,
    sender_unwatch,
    sender_watch,
)
from patina.models import ChatMessage, DmChannel
from patina.store import connect, get_db_path, init_db


class TestSenderWatch:
    def test_watch_returns_confirmation(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        result = sender_watch("alice", reason="key stakeholder")
        assert "Now watching alice" in result

    def test_watch_persists(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        sender_watch("alice")
        conn = connect(db_path)
        row = conn.execute("SELECT alias FROM watched_senders WHERE alias = 'alice'").fetchone()
        conn.close()
        assert row is not None

    def test_watch_stores_reason(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        sender_watch("alice", reason="project lead")
        conn = connect(db_path)
        row = conn.execute("SELECT reason FROM watched_senders WHERE alias = 'alice'").fetchone()
        conn.close()
        assert row["reason"] == "project lead"

    def test_watch_idempotent(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        sender_watch("alice")
        sender_watch("alice", reason="updated reason")
        conn = connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM watched_senders WHERE alias = 'alice'"
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_unwatch(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        sender_watch("alice")
        result = sender_unwatch("alice")
        assert "Stopped watching alice" in result
        conn = connect(db_path)
        row = conn.execute("SELECT alias FROM watched_senders WHERE alias = 'alice'").fetchone()
        conn.close()
        assert row is None

    def test_unwatch_nonexistent(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        result = sender_unwatch("nobody")
        assert "Stopped watching nobody" in result

    def test_list_empty(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        result = sender_list_watched()
        assert "No watched senders" in result

    def test_list_shows_entries(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        sender_watch("alice", reason="lead")
        sender_watch("bob", reason="reviewer")
        result = sender_list_watched()
        assert "alice" in result
        assert "bob" in result
        assert "lead" in result
        assert "reviewer" in result


class TestChannelWatch:
    def test_watch_returns_confirmation(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        result = channel_watch("project-alpha", channel_id="C001")
        assert "Now watching #project-alpha" in result

    def test_watch_persists(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        channel_watch("project-alpha", channel_id="C001")
        conn = connect(db_path)
        row = conn.execute(
            "SELECT channel_name FROM watched_channels WHERE channel_id = 'C001'"
        ).fetchone()
        conn.close()
        assert row["channel_name"] == "project-alpha"

    def test_watch_without_channel_id(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        channel_watch("general")
        conn = connect(db_path)
        row = conn.execute(
            "SELECT channel_id FROM watched_channels WHERE channel_name = 'general'"
        ).fetchone()
        conn.close()
        assert row["channel_id"] == "unresolved:general"

    def test_watch_stores_reason(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        channel_watch("alerts", channel_id="C002", reason="oncall")
        conn = connect(db_path)
        row = conn.execute(
            "SELECT reason FROM watched_channels WHERE channel_id = 'C002'"
        ).fetchone()
        conn.close()
        assert row["reason"] == "oncall"

    def test_watch_idempotent(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        channel_watch("alerts", channel_id="C002")
        channel_watch("alerts", channel_id="C002", reason="updated")
        conn = connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM watched_channels WHERE channel_id = 'C002'"
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_unwatch(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        channel_watch("alerts", channel_id="C002")
        result = channel_unwatch("alerts")
        assert "Stopped watching #alerts" in result
        conn = connect(db_path)
        row = conn.execute(
            "SELECT channel_id FROM watched_channels WHERE channel_name = 'alerts'"
        ).fetchone()
        conn.close()
        assert row is None

    def test_unwatch_nonexistent(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        result = channel_unwatch("nonexistent")
        assert "Stopped watching #nonexistent" in result

    def test_list_empty(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        result = channel_list_watched()
        assert "No watched channels" in result

    def test_list_shows_entries(self, db_path, db_conn, tmp_path):
        init_db(db_path)
        db_conn.close()
        channel_watch("alerts", channel_id="C001", reason="oncall")
        channel_watch("general", channel_id="C002")
        result = channel_list_watched()
        assert "#alerts" in result
        assert "#general" in result
        assert "oncall" in result


class TestWatchedChannelIngestion:
    def test_watched_channel_messages_ingested(self, tmp_path):
        home = tmp_path / "patina_home"

        class MockChatPort:
            @property
            def platform(self) -> str:
                return "mock"

            def list_dm_messages(self, since):
                return []

            def list_mentions(self, since):
                return []

            def list_channel_messages(self, channel_id, since):
                if channel_id == "C_WATCHED":
                    return [
                        ChatMessage(
                            user_id="U001",
                            text="Message from watched channel",
                            timestamp=time.time(),
                            channel_id="C_WATCHED",
                            user_name="Alice",
                        ),
                    ]
                return []

            def get_thread(self, channel_id, thread_id):
                return []

        db_path = get_db_path(home)
        init_db(db_path)
        conn = connect(db_path)
        conn.execute(
            "INSERT INTO watched_channels"
            " (channel_id, channel_name, reason, added_at)"
            " VALUES ('C_WATCHED', 'test-channel', 'testing', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        port = MockChatPort()
        result = ingest_live(port=port, source="mock", home=home)
        assert result["messages_inserted"] == 1

    def test_unwatched_channel_not_ingested(self, tmp_path):
        home = tmp_path / "patina_home"

        class MockChatPort:
            @property
            def platform(self) -> str:
                return "mock"

            def list_dm_messages(self, since):
                return []

            def list_mentions(self, since):
                return []

            def list_channel_messages(self, channel_id, since):
                return [
                    ChatMessage(
                        user_id="U001",
                        text="Should not appear",
                        timestamp=time.time(),
                        channel_id=channel_id,
                        user_name="Alice",
                    ),
                ]

            def get_thread(self, channel_id, thread_id):
                return []

        db_path = get_db_path(home)
        init_db(db_path)

        port = MockChatPort()
        result = ingest_live(port=port, source="mock", home=home)
        assert result["messages_inserted"] == 0


class TestAutoWatch:
    def _make_home(self, tmp_path):
        home = tmp_path / "patina_home"
        home.mkdir(parents=True, exist_ok=True)
        (home / "config.yaml").write_text("owner:\n  user_ids:\n    - U_OWNER\n")
        db_path = get_db_path(home)
        init_db(db_path)
        return home, db_path

    def _make_port(self, channel_messages=None):
        chan_msgs = channel_messages or {}

        class MockChatPort:
            @property
            def platform(self) -> str:
                return "mock"

            def list_dm_messages(self, since):
                return []

            def list_mentions(self, since):
                return []

            def list_channel_messages(self, channel_id, since):
                return chan_msgs.get(channel_id, [])

            def get_thread(self, channel_id, thread_id):
                return []

            def list_dms(self, include_dormant=False):
                return [
                    DmChannel(channel_id="G_MPIM1", is_group=True, last_activity_ts=time.time())
                ]

        return MockChatPort()

    def test_auto_watch_adds_new_channel(self, tmp_path):
        home, db_path = self._make_home(tmp_path)
        port = self._make_port()

        ingest_live(port=port, source="mock", home=home)

        conn = connect(db_path)
        row = conn.execute("SELECT * FROM watched_channels WHERE channel_id = 'G_MPIM1'").fetchone()
        conn.close()
        assert row is not None
        assert row["reason"] == "auto-detected: user is participant"

    def test_auto_watch_dedup(self, tmp_path):
        home, db_path = self._make_home(tmp_path)
        port = self._make_port()

        ingest_live(port=port, source="mock", home=home)
        ingest_live(port=port, source="mock", home=home)

        conn = connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM watched_channels WHERE channel_id = 'G_MPIM1'"
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_auto_watch_preserves_existing_reason(self, tmp_path):
        home, db_path = self._make_home(tmp_path)

        conn = connect(db_path)
        conn.execute(
            "INSERT INTO watched_channels"
            " (channel_id, channel_name, reason, added_at)"
            " VALUES ('G_MPIM1', 'group-dm-1', 'manually added', '2026-01-01')"
        )
        conn.commit()
        conn.close()

        port = self._make_port()
        ingest_live(port=port, source="mock", home=home)

        conn = connect(db_path)
        row = conn.execute(
            "SELECT reason FROM watched_channels WHERE channel_id = 'G_MPIM1'"
        ).fetchone()
        conn.close()
        assert row["reason"] == "manually added"

    def test_auto_watch_messages_ingested(self, tmp_path):
        home, db_path = self._make_home(tmp_path)
        port = self._make_port(
            channel_messages={
                "G_MPIM1": [
                    ChatMessage(
                        user_id="U001",
                        text="Hello from group DM",
                        timestamp=time.time(),
                        channel_id="G_MPIM1",
                        user_name="Tester",
                    ),
                ]
            }
        )

        result = ingest_live(port=port, source="mock", home=home)
        assert result["messages_inserted"] == 1


class TestWatchingToolsRegistered:
    def test_tools_appear_in_guide(self):
        from patina.agent.runtime import _build_tool_guide

        guide = _build_tool_guide()
        for name in [
            "sender_watch",
            "sender_unwatch",
            "sender_list_watched",
            "channel_watch",
            "channel_unwatch",
            "channel_list_watched",
        ]:
            assert f"**{name}**" in guide, f"tool '{name}' missing from guide"
