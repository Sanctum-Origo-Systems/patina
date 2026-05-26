from __future__ import annotations

import json
import zipfile

import pytest

from patina.ingest import ingest_all, ingest_from_export, ingest_live
from patina.models import ChatMessage


@pytest.fixture
def export_zip(tmp_path):
    zip_path = tmp_path / "export.zip"
    users = [
        {"id": "U001", "real_name": "Alice", "name": "alice"},
        {"id": "U002", "real_name": "Bob", "name": "bob"},
    ]
    channels = [{"id": "C001", "name": "general"}]
    messages = [
        {"user": "U001", "text": "Hello <@U002>!", "ts": "1700000100.000"},
        {"user": "U002", "text": "Hey Alice!", "ts": "1700000200.000"},
        {"user": "U001", "text": "Check <#C001|general>", "ts": "1700000300.000"},
    ]

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("users.json", json.dumps(users))
        zf.writestr("channels.json", json.dumps(channels))
        zf.writestr("general/2023-11-15.json", json.dumps(messages))

    return zip_path


def test_creates_observations(export_zip, tmp_path):
    home = tmp_path / "patina_home"
    result = ingest_from_export(export_zip, home=home)
    assert result["messages_inserted"] == 3
    assert result["total_observations"] == 3


def test_creates_entities(export_zip, tmp_path):
    home = tmp_path / "patina_home"
    result = ingest_from_export(export_zip, home=home)
    assert result["entities_created"] >= 2
    assert result["total_entities"] >= 2


def test_idempotent(export_zip, tmp_path):
    home = tmp_path / "patina_home"
    result1 = ingest_from_export(export_zip, home=home)
    result2 = ingest_from_export(export_zip, home=home)
    assert result2["messages_inserted"] == 0
    assert result2["messages_skipped"] == 3
    assert result2["total_observations"] == result1["total_observations"]


def test_links_sender_entity(export_zip, tmp_path):
    home = tmp_path / "patina_home"
    ingest_from_export(export_zip, home=home)

    from patina.store import connect, get_db_path

    conn = connect(get_db_path(home))
    rows = conn.execute(
        "SELECT sender_entity_id FROM observations WHERE sender_entity_id IS NOT NULL"
    ).fetchall()
    assert len(rows) == 3
    conn.close()


def test_returns_correct_counts(export_zip, tmp_path):
    home = tmp_path / "patina_home"
    result = ingest_from_export(export_zip, home=home)
    assert "messages_inserted" in result
    assert "messages_skipped" in result
    assert "entities_created" in result
    assert "total_observations" in result
    assert "total_entities" in result


_FIXED_TS = 1700000100.0


class MockChatPort:
    @property
    def platform(self) -> str:
        return "mock"

    def list_dm_messages(self, since: float) -> list[ChatMessage]:
        return [
            ChatMessage(
                user_id="U001",
                text="Hello from DM",
                timestamp=_FIXED_TS,
                channel_id="D001",
                user_name="Alice",
            ),
        ]

    def list_mentions(self, since: float) -> list[ChatMessage]:
        return [
            ChatMessage(
                user_id="U002",
                text="Hey <@U001>",
                timestamp=_FIXED_TS + 100,
                channel_id="C001",
                user_name="Bob",
            ),
        ]

    def list_channel_messages(self, channel_id, since):
        return []

    def get_thread(self, channel_id, thread_id):
        return []


def test_ingest_live_with_mock_port(tmp_path):
    home = tmp_path / "live_home"
    port = MockChatPort()
    result = ingest_live(port=port, source="mock", home=home)
    assert result["messages_inserted"] == 2
    assert result["entities_created"] >= 2


def test_ingest_live_dedup(tmp_path):
    home = tmp_path / "live_home"
    port = MockChatPort()
    ingest_live(port=port, source="mock", home=home)
    result2 = ingest_live(port=port, source="mock", home=home)
    assert result2["messages_skipped"] == 2


def test_ingest_all_no_adapters(tmp_path):
    result = ingest_all(home=tmp_path)
    assert result["adapters_run"] == 0
    assert result["messages_inserted"] == 0
