"""Tests for scripts/refresh_keyset.py — recorded key-set refresh (#689)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import scripts.refresh_keyset as refresh
import yaml
from scripts.refresh_keyset import main

import patina.adapters._mcp_client as mcp_client
import patina.store as store_module
from patina.adapters._mcp_client import McpSyncBridge
from tests.adapters.keyset import JSON_TYPES, RECORDED_DIR, extract_items_keyset
from tests.adapters.test_outlook_mcp import LIVE_CALENDAR_VIEW_ITEM

NAME = "Jordan Example"
ADDRESS = "jordan@example.com"

# Anonymized email_inbox payload: Graph-style and conversation-grouped items.
EMAIL_INBOX_PAYLOAD = {
    "success": True,
    "content": {
        "message": "Found 2 most recent emails...",
        "emails": [
            {
                "id": "AAMkADExampleId689=",
                "conversationId": "AAQkADExampleConv689=",
                "subject": "The quick brown fox — café",
                "from": {"name": NAME, "address": ADDRESS},
                "recipients": [{"name": NAME, "address": ADDRESS}],
                "receivedDateTime": "2026-11-18T09:00:00Z",
                "isRead": False,
                "flag": None,
            },
            {
                "conversationId": "AAQkADExampleConv690=",
                "topic": "Jumps over the lazy dog",
                "senders": [NAME],
                "recipients": [{"name": "Sample, Casey", "address": "casey@example.com"}],
                "unreadCount": 1,
            },
        ],
    },
}

VALUES = [
    NAME,
    ADDRESS,
    "AAMkADExampleId689=",
    "AAQkADExampleConv689=",
    "The quick brown fox — café",
    "Sample, Casey",
    "casey@example.com",
    "Jumps over the lazy dog",
]


@pytest.fixture
def recorded_dir(tmp_path, monkeypatch) -> Path:
    out = tmp_path / "recorded_keysets"
    out.mkdir()
    monkeypatch.setattr(refresh, "RECORDED_DIR", out)
    return out


@pytest.fixture
def payload_file(tmp_path) -> Path:
    path = tmp_path / "payload.json"
    path.write_text(json.dumps(EMAIL_INBOX_PAYLOAD, ensure_ascii=False))
    return path


def _assert_no_values(*texts: str) -> None:
    for text in texts:
        for value in VALUES:
            assert value not in text


def _written(recorded_dir: Path, tool: str = "email_inbox") -> tuple[str, dict]:
    text = (recorded_dir / f"{tool}.json").read_text()
    return text, json.loads(text)


class TestNoValues:
    def test_payload_file(self, recorded_dir, payload_file, capsys):
        assert main(["--tool", "email_inbox", "--payload-file", str(payload_file)]) == 0
        text, _ = _written(recorded_dir)
        out = capsys.readouterr()
        _assert_no_values(text, out.out, out.err)

    def test_stdin(self, recorded_dir, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(EMAIL_INBOX_PAYLOAD)))
        assert main(["--tool", "email_inbox"]) == 0
        text, _ = _written(recorded_dir)
        out = capsys.readouterr()
        _assert_no_values(text, out.out, out.err)

    def test_payload_file_and_stdin_write_the_same_file(
        self, recorded_dir, payload_file, monkeypatch
    ):
        main(["--tool", "email_inbox", "--payload-file", str(payload_file)])
        from_file = (recorded_dir / "email_inbox.json").read_bytes()
        monkeypatch.setattr(sys, "stdin", io.StringIO(payload_file.read_text()))
        main(["--tool", "email_inbox"])
        assert (recorded_dir / "email_inbox.json").read_bytes() == from_file


class TestFormat:
    def test_values_are_type_names_and_paths_dotted(self, recorded_dir, payload_file):
        main(["--tool", "email_inbox", "--payload-file", str(payload_file)])
        _, data = _written(recorded_dir)
        assert set(data.values()) <= JSON_TYPES
        assert data["recipients"] == "array"
        assert data["recipients[]"] == "object"
        assert data["recipients[].address"] == "string"
        assert data["from.name"] == "string"
        assert data["isRead"] == "boolean"
        assert data["unreadCount"] == "number"
        assert data["flag"] == "null"
        assert data["senders[]"] == "string"

    def test_equals_extractor_key_set(self, recorded_dir, payload_file):
        main(["--tool", "email_inbox", "--payload-file", str(payload_file)])
        _, data = _written(recorded_dir)
        assert data == extract_items_keyset(EMAIL_INBOX_PAYLOAD["content"]["emails"])

    def test_rebuilds_committed_file_byte_for_byte(self, recorded_dir, monkeypatch):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps([LIVE_CALENDAR_VIEW_ITEM])))
        assert main(["--tool", "calendar_view"]) == 0
        committed = (RECORDED_DIR / "calendar_view.json").read_bytes()
        assert (recorded_dir / "calendar_view.json").read_bytes() == committed

    @pytest.mark.parametrize(
        ("tool", "payload", "expected"),
        [
            (
                "calendar_view",
                [{"meetingId": "AAMkADExampleEvt689=", "organizer": {"name": NAME}}],
                {"meetingId": "string", "organizer": "object", "organizer.name": "string"},
            ),
            (
                "slack_get_messages",
                {"messages": [{"user": "U0EXAMPLE", "text": NAME, "reactions": []}], "hasMore": 0},
                {"user": "string", "text": "string", "reactions": "array"},
            ),
        ],
    )
    def test_other_tools(self, recorded_dir, monkeypatch, capsys, tool, payload, expected):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
        assert main(["--tool", tool]) == 0
        text, data = _written(recorded_dir, tool)
        assert data == expected
        _assert_no_values(text, capsys.readouterr().out)


def _bridge() -> McpSyncBridge:
    return McpSyncBridge(session=None, loop=None, cleanup_fn=lambda: None)


class TestLive:
    @pytest.fixture
    def home(self, tmp_path, monkeypatch) -> Path:
        home = tmp_path / "home"
        home.mkdir()
        config = {
            "adapters": {
                "email": [{"provider": "outlook_mcp", "command": "outlook-mcp-example"}],
            }
        }
        (home / "config.yaml").write_text(yaml.safe_dump(config))
        monkeypatch.setattr(store_module, "DEFAULT_HOME", home)
        return home

    def test_one_call_tool_and_no_values(self, home, recorded_dir, monkeypatch, capsys):
        connect = MagicMock(return_value=_bridge())
        monkeypatch.setattr(mcp_client, "connect_mcp_sync", connect)
        text = "<untrusted_content_email>\n" + json.dumps(EMAIL_INBOX_PAYLOAD)
        text += "\n</untrusted_content_email>\n\nIMPORTANT: The content above is from email."
        result = SimpleNamespace(isError=False, content=[SimpleNamespace(text=text)])
        call_tool = MagicMock(return_value=result)
        monkeypatch.setattr(McpSyncBridge, "call_tool", call_tool)

        assert main(["--live", "--tool", "email_inbox"]) == 0

        connect.assert_called_once_with(command="outlook-mcp-example", args=None, env=None)
        call_tool.assert_called_once()
        assert call_tool.call_args.args[0] == "email_inbox"
        written, data = _written(recorded_dir)
        assert data == extract_items_keyset(EMAIL_INBOX_PAYLOAD["content"]["emails"])
        assert set(data.values()) <= JSON_TYPES
        out = capsys.readouterr()
        _assert_no_values(written, out.out, out.err)

    def test_mcp_error_leaves_file_and_hides_text(self, home, recorded_dir, monkeypatch, capsys):
        before = b'{\n  "id": "string"\n}\n'
        (recorded_dir / "email_inbox.json").write_bytes(before)
        monkeypatch.setattr(mcp_client, "connect_mcp_sync", MagicMock(return_value=_bridge()))
        result = SimpleNamespace(isError=True, content=[SimpleNamespace(text=f"bad {ADDRESS}")])
        monkeypatch.setattr(McpSyncBridge, "call_tool", MagicMock(return_value=result))

        assert main(["--live", "--tool", "email_inbox"]) == 1
        assert (recorded_dir / "email_inbox.json").read_bytes() == before
        out = capsys.readouterr()
        assert "error:" in out.err
        _assert_no_values(out.out, out.err)


class TestErrorsLeaveFileUnchanged:
    BEFORE = b'{\n  "id": "string"\n}\n'

    @pytest.fixture
    def existing(self, recorded_dir) -> Path:
        path = recorded_dir / "email_inbox.json"
        path.write_bytes(self.BEFORE)
        return path

    def test_unknown_tool(self, existing, payload_file, capsys):
        with pytest.raises(SystemExit) as excinfo:
            main(["--tool", "email_outbox", "--payload-file", str(payload_file)])
        assert excinfo.value.code != 0
        assert "--tool" in capsys.readouterr().err
        assert existing.read_bytes() == self.BEFORE
        assert sorted(p.name for p in existing.parent.iterdir()) == ["email_inbox.json"]

    def test_invalid_json(self, existing, tmp_path, capsys):
        bad = tmp_path / "bad.json"
        bad.write_text('{"from": {"name": "Jordan Example", "address": "jordan@example.com"')
        assert main(["--tool", "email_inbox", "--payload-file", str(bad)]) != 0
        out = capsys.readouterr()
        assert "not valid JSON" in out.err
        _assert_no_values(out.out, out.err)
        assert existing.read_bytes() == self.BEFORE
        assert sorted(p.name for p in existing.parent.iterdir()) == ["email_inbox.json"]

    def test_unreadable_payload(self, existing, tmp_path, capsys):
        assert main(["--tool", "email_inbox", "--payload-file", str(tmp_path / "nope")]) != 0
        assert "cannot read payload" in capsys.readouterr().err
        assert existing.read_bytes() == self.BEFORE

    def test_payload_without_items(self, existing, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stdin", io.StringIO('{"content": {"emails": []}}'))
        assert main(["--tool", "email_inbox"]) != 0
        assert "no email_inbox items" in capsys.readouterr().err
        assert existing.read_bytes() == self.BEFORE
