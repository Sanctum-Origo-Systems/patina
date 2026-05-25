from __future__ import annotations

import json
import zipfile

import pytest

from patina.export_parser import parse_slack_export


@pytest.fixture
def slack_zip(tmp_path):
    zip_path = tmp_path / "export.zip"
    users = [
        {"id": "U001", "real_name": "Alice Smith", "name": "alice"},
        {"id": "U002", "real_name": "Bob Jones", "name": "bob"},
    ]
    channels = [
        {"id": "C001", "name": "general"},
        {"id": "C002", "name": "project-x"},
    ]
    general_msgs = [
        {"user": "U001", "text": "Hello everyone!", "ts": "1700000100.000"},
        {"user": "U002", "text": "Hey Alice", "ts": "1700000200.000"},
        {
            "user": "U001",
            "text": "Thread reply",
            "ts": "1700000300.000",
            "thread_ts": "1700000100.000",
        },
        {"subtype": "bot_message", "text": "Bot says hi", "ts": "1700000400.000"},
        {"subtype": "channel_join", "user": "U001", "text": "joined", "ts": "1700000500.000"},
        {"user": "", "text": "no user", "ts": "1700000600.000"},
        {"user": "U001", "text": "", "ts": "1700000700.000"},
        {
            "user": "U002",
            "text": "Nice work!",
            "ts": "1700000800.000",
            "reactions": [{"name": "thumbsup", "users": ["U001"]}],
        },
    ]
    project_msgs = [
        {"user": "U001", "text": "Starting sprint", "ts": "1700001000.000"},
    ]

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("users.json", json.dumps(users))
        zf.writestr("channels.json", json.dumps(channels))
        zf.writestr("general/2023-11-15.json", json.dumps(general_msgs))
        zf.writestr("project-x/2023-11-15.json", json.dumps(project_msgs))

    return zip_path


def test_parses_messages(slack_zip):
    messages, users, channels = parse_slack_export(slack_zip)
    assert len(messages) == 5


def test_returns_user_dict(slack_zip):
    _, users, _ = parse_slack_export(slack_zip)
    assert users["U001"] == "Alice Smith"
    assert users["U002"] == "Bob Jones"


def test_returns_channel_dict(slack_zip):
    _, _, channels = parse_slack_export(slack_zip)
    assert channels["C001"] == "general"
    assert channels["C002"] == "project-x"


def test_sorted_by_timestamp(slack_zip):
    messages, _, _ = parse_slack_export(slack_zip)
    timestamps = [m.timestamp for m in messages]
    assert timestamps == sorted(timestamps)


def test_thread_reply_has_thread_id(slack_zip):
    messages, _, _ = parse_slack_export(slack_zip)
    thread_replies = [m for m in messages if m.thread_id is not None]
    assert len(thread_replies) == 1
    assert thread_replies[0].text == "Thread reply"
    assert thread_replies[0].thread_id == "1700000100.000"


def test_top_level_no_thread_id(slack_zip):
    messages, _, _ = parse_slack_export(slack_zip)
    top_level = [m for m in messages if m.thread_id is None]
    assert len(top_level) == 4


def test_reactions_captured(slack_zip):
    messages, _, _ = parse_slack_export(slack_zip)
    with_reactions = [m for m in messages if m.reactions]
    assert len(with_reactions) == 1
    assert with_reactions[0].reactions[0]["name"] == "thumbsup"


def test_bot_messages_skipped(slack_zip):
    messages, _, _ = parse_slack_export(slack_zip)
    assert all(m.text != "Bot says hi" for m in messages)


def test_empty_user_text_skipped(slack_zip):
    messages, _, _ = parse_slack_export(slack_zip)
    assert all(m.user_id != "" for m in messages)
    assert all(m.text != "" for m in messages)
