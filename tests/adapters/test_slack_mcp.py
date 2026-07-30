from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from patina.adapters.slack_mcp import (
    DmChannel,
    SlackMcpAdapter,
    _extract_display_name,
    _parse_activity_ts,
)
from patina.ports.chat import ChatPort


def _make_bridge(responses: dict[str, str] | None = None):
    bridge = MagicMock()
    responses = responses or {}

    def call_tool(name, arguments=None, **kwargs):
        text = responses.get(name, "[]")
        return SimpleNamespace(isError=False, content=[SimpleNamespace(text=text)])

    bridge.call_tool = MagicMock(side_effect=call_tool)
    return bridge


_SLACK_CONTENT_TEXT = (
    '<slack-user-content sender="U00000ALICE" ts="1781651078.945749">'
    "\nHey, can you review the proposal?\n</slack-user-content>"
)

FIXTURES_DM_FLAT = json.dumps(
    [
        {
            "user": "U00000ALICE",
            "text": _SLACK_CONTENT_TEXT,
            "ts": "1781651078.945749",
            "channel": {"id": "D00000DM001", "name": "alice", "is_im": True},
            "reactions": [{"name": "eyes", "users": ["U00000ALICE"]}],
        },
    ]
)

FIXTURES_DM_CATEGORIZED = json.dumps(
    {
        "dms": [
            {
                "user": "U00000DAVE1",
                "text": "Reminder: complete the compliance training",
                "ts": "1781769000.447729",
                "channel": {"id": "D00000DM002", "name": "dave", "is_im": True},
                "reactions": [],
            },
        ],
        "threads": [
            {
                "user": "U00000BOB01",
                "text": "Updated the proposal",
                "ts": "1781800000.123456",
                "thread_ts": "1781600000.000000",
                "channel": {"id": "C00000CH001", "name": "project-alpha", "is_im": False},
                "reactions": [],
            },
        ],
    }
)

FIXTURES_SEARCH_NESTED = json.dumps(
    {
        "messages": {
            "matches": [
                {
                    "user": "U00000EVE01",
                    "text": "Can you join the client call at 3pm?",
                    "ts": "1781900000.111111",
                    "channel": {"id": "C00000CH001", "name": "project-alpha", "is_im": False},
                },
            ],
        },
    }
)

FIXTURES_SEARCH_FLAT = json.dumps(
    [
        {
            "user": "U00000EVE01",
            "text": "Monthly report inputs are due",
            "ts": "1781627745.092109",
            "channel": {"id": "C00000CH003", "name": "team-general"},
            "isDm": False,
        },
    ]
)

FIXTURES_MESSAGES_LIST = json.dumps(
    [
        {
            "user": "U00000BOB01",
            "text": "Proposal update: contract in final review",
            "ts": "1781900100.222222",
            "channel_id": "C00000CH001",
            "channel_name": "project-alpha",
            "reactions": [],
        },
    ]
)

FIXTURES_MESSAGES_DICT = json.dumps(
    {
        "messages": [
            {
                "user": "U00000FRANK",
                "text": "Deploy completed",
                "ts": "1781850000.444444",
                "channel_id": "C00000CH001",
                "reactions": [],
            },
        ],
    }
)

FIXTURES_THREAD_LIST = json.dumps(
    [
        {
            "user": "U00000BOB01",
            "text": "Let's discuss the database architecture",
            "ts": "1781600000.000000",
            "thread_ts": "1781600000.000000",
            "channel_id": "C00000CH001",
            "reactions": [],
        },
        {
            "user": "U00000OWNER",
            "text": "I recommend PostgreSQL",
            "ts": "1781610000.555555",
            "thread_ts": "1781600000.000000",
            "channel_id": "C00000CH001",
            "reactions": [{"name": "thumbsup", "users": ["U00000BOB01"]}],
        },
    ]
)

FIXTURES_THREAD_DICT = json.dumps(
    {
        "replies": [
            {
                "user": "U00000OWNER",
                "text": "Following up - Frank confirmed the correction",
                "ts": "1781800000.777777",
                "thread_ts": "1781600000.000000",
                "channel_id": "C00000CH001",
                "reactions": [],
            },
        ],
    }
)


class TestProtocolSatisfaction:
    def test_satisfies_chat_port(self):
        bridge = _make_bridge()
        adapter = SlackMcpAdapter(bridge)
        assert isinstance(adapter, ChatPort)

    def test_platform(self):
        bridge = _make_bridge()
        adapter = SlackMcpAdapter(bridge)
        assert adapter.platform == "slack_mcp"


class TestListDmMessages:
    def test_flat_list_format(self):
        bridge = _make_bridge({"get_unreads": FIXTURES_DM_FLAT})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_dm_messages(since=0.0)
        assert len(msgs) == 1
        assert msgs[0].user_id == "U00000ALICE"
        assert "review the proposal" in msgs[0].text
        assert "<slack-user-content" not in msgs[0].text

    def test_categorized_dict_format(self):
        bridge = _make_bridge({"get_unreads": FIXTURES_DM_CATEGORIZED})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_dm_messages(since=0.0)
        dm_msgs = [m for m in msgs if m.channel_id.startswith("D")]
        assert len(dm_msgs) == 1
        assert dm_msgs[0].user_id == "U00000DAVE1"

    def test_filters_by_since(self):
        bridge = _make_bridge({"get_unreads": FIXTURES_DM_FLAT})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_dm_messages(since=9999999999.0)
        assert len(msgs) == 0

    def test_returns_empty_on_error(self):
        bridge = MagicMock()
        bridge.call_tool = MagicMock(side_effect=Exception("connection failed"))
        adapter = SlackMcpAdapter(bridge)
        assert adapter.list_dm_messages(since=0.0) == []


class TestListMentions:
    def test_nested_matches_format(self):
        bridge = _make_bridge({"search": FIXTURES_SEARCH_NESTED})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_mentions(since=0.0)
        assert len(msgs) == 1
        assert msgs[0].user_id == "U00000EVE01"

    def test_flat_list_format(self):
        bridge = _make_bridge({"search": FIXTURES_SEARCH_FLAT})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_mentions(since=0.0)
        assert len(msgs) == 1

    def test_calls_search_with_query(self):
        bridge = _make_bridge({"search": "[]"})
        adapter = SlackMcpAdapter(bridge)
        adapter.list_mentions(since=1781600000.0)
        call_args = bridge.call_tool.call_args
        assert call_args[0][0] == "search"
        assert "to:me" in call_args[0][1]["query"]


class TestListChannelMessages:
    def test_list_format(self):
        bridge = _make_bridge({"get_messages": FIXTURES_MESSAGES_LIST})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_channel_messages("C00000CH001", since=0.0)
        assert len(msgs) == 1
        assert msgs[0].user_id == "U00000BOB01"

    def test_dict_wrapped_format(self):
        bridge = _make_bridge({"get_messages": FIXTURES_MESSAGES_DICT})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_channel_messages("C00000CH001", since=0.0)
        assert len(msgs) == 1
        assert msgs[0].user_id == "U00000FRANK"

    def test_calls_correct_tool(self):
        bridge = _make_bridge({"get_messages": "[]"})
        adapter = SlackMcpAdapter(bridge)
        adapter.list_channel_messages("C00000CH001", since=1781600000.0)
        call_args = bridge.call_tool.call_args
        assert call_args[0][0] == "get_messages"
        assert call_args[0][1]["channel"] == "C00000CH001"

    def test_passes_limit_and_include_thread_replies(self):
        bridge = _make_bridge({"get_messages": "[]"})
        adapter = SlackMcpAdapter(bridge)
        adapter.list_channel_messages("C00000CH001", since=0.0)
        call_args = bridge.call_tool.call_args
        assert call_args[0][1]["limit"] == 200
        assert call_args[0][1]["includeThreadReplies"] is False

    def test_paginates_across_multiple_pages(self):
        page1 = json.dumps(
            {
                "messages": [
                    {
                        "user": "U00000ALICE",
                        "text": "Message from page one",
                        "ts": "1781900300.333333",
                        "channel_id": "C00000CH001",
                        "reactions": [],
                    },
                    {
                        "user": "U00000BOB01",
                        "text": "Another page one message",
                        "ts": "1781900200.222222",
                        "channel_id": "C00000CH001",
                        "reactions": [],
                    },
                ],
                "hasMore": True,
                "nextCursor": "cursor_page2",
            }
        )
        page2 = json.dumps(
            {
                "messages": [
                    {
                        "user": "U00000FRANK",
                        "text": "Message from page two",
                        "ts": "1781900100.111111",
                        "channel_id": "C00000CH001",
                        "reactions": [],
                    },
                ],
                "hasMore": False,
            }
        )
        pages = [page1, page2]
        call_index = {"n": 0}

        bridge = MagicMock()

        def call_tool(name, arguments=None, **kwargs):
            idx = call_index["n"]
            call_index["n"] += 1
            text = pages[idx] if idx < len(pages) else "[]"
            return SimpleNamespace(isError=False, content=[SimpleNamespace(text=text)])

        bridge.call_tool = MagicMock(side_effect=call_tool)
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_channel_messages("C00000CH001", since=0.0)

        assert len(msgs) == 3
        assert msgs[0].user_id == "U00000ALICE"
        assert msgs[1].user_id == "U00000BOB01"
        assert msgs[2].user_id == "U00000FRANK"
        get_msg_calls = [c for c in bridge.call_tool.call_args_list if c[0][0] == "get_messages"]
        assert len(get_msg_calls) == 2
        assert get_msg_calls[1][0][1]["cursor"] == "cursor_page2"

    def test_stops_when_has_more_false(self):
        page = json.dumps(
            {
                "messages": [
                    {
                        "user": "U00000ALICE",
                        "text": "Only page",
                        "ts": "1781900100.111111",
                        "channel_id": "C00000CH001",
                        "reactions": [],
                    },
                ],
                "hasMore": False,
            }
        )
        bridge = _make_bridge({"get_messages": page})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_channel_messages("C00000CH001", since=0.0)
        assert len(msgs) == 1
        get_msg_calls = [c for c in bridge.call_tool.call_args_list if c[0][0] == "get_messages"]
        assert len(get_msg_calls) == 1

    def test_stops_when_all_page_messages_older_than_since(self):
        page1 = json.dumps(
            {
                "messages": [
                    {
                        "user": "U00000ALICE",
                        "text": "Recent message",
                        "ts": "1781900300.333333",
                        "channel_id": "C00000CH001",
                        "reactions": [],
                    },
                ],
                "hasMore": True,
                "nextCursor": "cursor_page2",
            }
        )
        page2 = json.dumps(
            {
                "messages": [
                    {
                        "user": "U00000BOB01",
                        "text": "Old message",
                        "ts": "1000000000.111111",
                        "channel_id": "C00000CH001",
                        "reactions": [],
                    },
                ],
                "hasMore": True,
                "nextCursor": "cursor_page3",
            }
        )
        pages = [page1, page2]
        call_index = {"n": 0}

        bridge = MagicMock()

        def call_tool(name, arguments=None, **kwargs):
            idx = call_index["n"]
            call_index["n"] += 1
            text = pages[idx] if idx < len(pages) else "[]"
            return SimpleNamespace(isError=False, content=[SimpleNamespace(text=text)])

        bridge.call_tool = MagicMock(side_effect=call_tool)
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_channel_messages("C00000CH001", since=1781900000.0)

        assert len(msgs) == 2
        get_msg_calls = [c for c in bridge.call_tool.call_args_list if c[0][0] == "get_messages"]
        assert len(get_msg_calls) == 2

    def test_max_pages_safety_cap(self):
        always_more = json.dumps(
            {
                "messages": [
                    {
                        "user": "U00000ALICE",
                        "text": "Repeated page",
                        "ts": "1781900100.111111",
                        "channel_id": "C00000CH001",
                        "reactions": [],
                    },
                ],
                "hasMore": True,
                "nextCursor": "cursor_next",
            }
        )

        bridge = MagicMock()

        def call_tool(name, arguments=None, **kwargs):
            return SimpleNamespace(isError=False, content=[SimpleNamespace(text=always_more)])

        bridge.call_tool = MagicMock(side_effect=call_tool)
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_channel_messages("C00000CH001", since=0.0)

        get_msg_calls = [c for c in bridge.call_tool.call_args_list if c[0][0] == "get_messages"]
        assert len(get_msg_calls) == 50
        assert len(msgs) == 50

    def test_stops_on_missing_next_cursor(self):
        page = json.dumps(
            {
                "messages": [
                    {
                        "user": "U00000ALICE",
                        "text": "Page with hasMore but no cursor",
                        "ts": "1781900100.111111",
                        "channel_id": "C00000CH001",
                        "reactions": [],
                    },
                ],
                "hasMore": True,
            }
        )
        bridge = _make_bridge({"get_messages": page})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_channel_messages("C00000CH001", since=0.0)
        assert len(msgs) == 1
        get_msg_calls = [c for c in bridge.call_tool.call_args_list if c[0][0] == "get_messages"]
        assert len(get_msg_calls) == 1


class TestGetThread:
    def test_list_format(self):
        bridge = _make_bridge({"get_thread": FIXTURES_THREAD_LIST})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.get_thread("C00000CH001", "1781600000.000000")
        assert len(msgs) == 2
        assert msgs[0].user_id == "U00000BOB01"

    def test_dict_wrapped_format(self):
        bridge = _make_bridge({"get_thread": FIXTURES_THREAD_DICT})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.get_thread("C00000CH001", "1781600000.000000")
        assert len(msgs) == 1
        assert "Frank confirmed" in msgs[0].text

    def test_calls_with_thread_ts(self):
        bridge = _make_bridge({"get_thread": "[]"})
        adapter = SlackMcpAdapter(bridge)
        adapter.get_thread("C00000CH001", "1781600000.000000")
        call_args = bridge.call_tool.call_args
        assert call_args[0][0] == "get_thread"
        assert call_args[0][1]["threadTs"] == "1781600000.000000"


class TestMessageParsing:
    def test_dict_channel_field(self):
        bridge = _make_bridge({"get_unreads": FIXTURES_DM_FLAT})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_dm_messages(since=0.0)
        assert msgs[0].channel_id == "D00000DM001"
        assert msgs[0].channel_name == "alice"

    def test_string_channel_field(self):
        raw = json.dumps(
            [
                {
                    "user": "U001",
                    "text": "test",
                    "ts": "1781900000.111111",
                    "channel_id": "C001",
                    "channel_name": "general",
                }
            ]
        )
        bridge = _make_bridge({"get_messages": raw})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_channel_messages("C001", since=0.0)
        assert msgs[0].channel_id == "C001"

    def test_dict_user_field(self):
        raw = json.dumps(
            [
                {
                    "user": {"id": "U00000CAROL", "name": "carol"},
                    "text": "hello",
                    "ts": "1781570237.143369",
                    "channel": "C002",
                }
            ]
        )
        bridge = _make_bridge({"get_messages": raw})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_channel_messages("C002", since=0.0)
        assert msgs[0].user_id == "U00000CAROL"

    def test_reactions_preserved(self):
        bridge = _make_bridge({"get_unreads": FIXTURES_DM_FLAT})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_dm_messages(since=0.0)
        assert len(msgs[0].reactions) == 1
        assert msgs[0].reactions[0]["name"] == "eyes"

    def test_thread_id_set_when_different_from_ts(self):
        bridge = _make_bridge({"get_thread": FIXTURES_THREAD_LIST})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.get_thread("C001", "1781600000.000000")
        assert msgs[0].thread_id is None
        assert msgs[1].thread_id == "1781600000.000000"

    def test_user_name_extracted_from_dict_user(self):
        raw = json.dumps(
            [
                {
                    "user": {"id": "U00000CAROL", "real_name": "Carol Reeves"},
                    "text": "hello",
                    "ts": "1781570237.143369",
                    "channel": "C002",
                }
            ]
        )
        bridge = _make_bridge({"get_messages": raw})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_channel_messages("C002", since=0.0)
        assert msgs[0].user_name == "Carol Reeves"

    def test_user_name_from_username_field(self):
        raw = json.dumps(
            [
                {
                    "user": "U00000BOB01",
                    "username": "Roberta Marsh",
                    "text": "test",
                    "ts": "1781900000.111111",
                    "channel_id": "C001",
                }
            ]
        )
        bridge = _make_bridge({"get_messages": raw})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_channel_messages("C001", since=0.0)
        assert msgs[0].user_name == "Roberta Marsh"


class TestUserIdResolution:
    def test_w_prefix_id_resolved_via_profile(self):
        profile_response = json.dumps({"real_name": "Jianwei Nakamura"})
        messages = json.dumps(
            [
                {
                    "user": "W0USERID001",
                    "text": "Design review is ready",
                    "ts": "1781900000.111111",
                    "channel": {"id": "D00000DM003", "name": "dm-jianwei", "is_im": True},
                }
            ]
        )
        bridge = _make_bridge({"get_unreads": messages, "get_user_profile": profile_response})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_dm_messages(since=0.0)
        assert len(msgs) == 1
        assert msgs[0].user_id == "W0USERID001"
        assert msgs[0].user_name == "Jianwei Nakamura"

    def test_u_prefix_id_resolved_via_profile(self):
        profile_response = json.dumps({"real_name": "Amara Okonkwo"})
        messages = json.dumps(
            [
                {
                    "user": "U00000ALICE",
                    "text": "Sync later?",
                    "ts": "1781900000.111111",
                    "channel": {"id": "D00000DM001", "name": "dm-amara", "is_im": True},
                }
            ]
        )
        bridge = _make_bridge({"get_unreads": messages, "get_user_profile": profile_response})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_dm_messages(since=0.0)
        assert msgs[0].user_name == "Amara Okonkwo"

    def test_resolution_cached_across_messages(self):
        profile_response = json.dumps({"real_name": "Kenji Soderberg"})
        messages = json.dumps(
            [
                {
                    "user": "W0USERID002",
                    "text": "First message",
                    "ts": "1781900000.111111",
                    "channel_id": "C001",
                },
                {
                    "user": "W0USERID002",
                    "text": "Second message",
                    "ts": "1781900001.222222",
                    "channel_id": "C001",
                },
            ]
        )
        bridge = _make_bridge({"get_messages": messages, "get_user_profile": profile_response})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_channel_messages("C001", since=0.0)
        assert msgs[0].user_name == "Kenji Soderberg"
        assert msgs[1].user_name == "Kenji Soderberg"
        profile_calls = [
            c for c in bridge.call_tool.call_args_list if c[0][0] == "get_user_profile"
        ]
        assert len(profile_calls) == 1

    def test_resolution_failure_falls_back_gracefully(self):
        messages = json.dumps(
            [
                {
                    "user": "W0USERID003",
                    "text": "Bot message",
                    "ts": "1781900000.111111",
                    "channel_id": "C001",
                }
            ]
        )
        bridge = MagicMock()
        call_count = {"n": 0}

        def call_tool(name, arguments=None, **kwargs):
            call_count["n"] += 1
            if name == "get_user_profile":
                raise Exception("API error")
            if name == "get_messages":
                return SimpleNamespace(isError=False, content=[SimpleNamespace(text=messages)])
            return SimpleNamespace(isError=False, content=[SimpleNamespace(text="[]")])

        bridge.call_tool = MagicMock(side_effect=call_tool)
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_channel_messages("C001", since=0.0)
        assert len(msgs) == 1
        assert msgs[0].user_id == "W0USERID003"
        assert msgs[0].user_name is None

    def test_resolution_skips_non_user_ids(self):
        messages = json.dumps(
            [
                {
                    "user": "BBOT00001",
                    "text": "Automated alert",
                    "ts": "1781900000.111111",
                    "channel_id": "C001",
                }
            ]
        )
        bridge = _make_bridge({"get_messages": messages})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_channel_messages("C001", since=0.0)
        assert msgs[0].user_name is None
        profile_calls = [
            c for c in bridge.call_tool.call_args_list if c[0][0] == "get_user_profile"
        ]
        assert len(profile_calls) == 0

    def test_resolution_skips_when_name_already_set(self):
        messages = json.dumps(
            [
                {
                    "user": {"id": "W0USERID001", "real_name": "Priya Lindqvist"},
                    "text": "Already named",
                    "ts": "1781900000.111111",
                    "channel_id": "C001",
                }
            ]
        )
        bridge = _make_bridge({"get_messages": messages})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_channel_messages("C001", since=0.0)
        assert msgs[0].user_name == "Priya Lindqvist"
        profile_calls = [
            c for c in bridge.call_tool.call_args_list if c[0][0] == "get_user_profile"
        ]
        assert len(profile_calls) == 0

    def test_w_prefix_in_mentions(self):
        profile_response = json.dumps({"display_name": "Tomoko Alvarez"})
        search_results = json.dumps(
            [
                {
                    "user": "W0USERID001",
                    "text": "Please review the deployment plan",
                    "ts": "1781900000.111111",
                    "channel": {"id": "C001", "name": "ops"},
                }
            ]
        )
        bridge = _make_bridge({"search": search_results, "get_user_profile": profile_response})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.list_mentions(since=0.0)
        assert msgs[0].user_name == "Tomoko Alvarez"

    def test_w_prefix_in_thread(self):
        profile_response = json.dumps({"name": "Dmitri Okafor"})
        thread_messages = json.dumps(
            [
                {
                    "user": "W0USERID003",
                    "text": "Thread reply",
                    "ts": "1781900000.111111",
                    "thread_ts": "1781800000.000000",
                    "channel_id": "C001",
                }
            ]
        )
        bridge = _make_bridge({"get_thread": thread_messages, "get_user_profile": profile_response})
        adapter = SlackMcpAdapter(bridge)
        msgs = adapter.get_thread("C001", "1781800000.000000")
        assert msgs[0].user_name == "Dmitri Okafor"


class TestExtractDisplayName:
    def test_real_name_at_top_level(self):
        assert _extract_display_name({"real_name": "Anya Petrova"}) == "Anya Petrova"

    def test_display_name_at_top_level(self):
        assert _extract_display_name({"display_name": "Anya"}) == "Anya"

    def test_name_at_top_level(self):
        assert _extract_display_name({"name": "anya.petrova"}) == "anya.petrova"

    def test_nested_under_user(self):
        assert _extract_display_name({"user": {"real_name": "Anya Petrova"}}) == "Anya Petrova"

    def test_nested_under_user_profile(self):
        raw = {"user": {"profile": {"display_name": "Anya"}}}
        assert _extract_display_name(raw) == "Anya"

    def test_nested_under_profile(self):
        assert _extract_display_name({"profile": {"real_name": "Anya Petrova"}}) == "Anya Petrova"

    def test_returns_none_for_non_dict(self):
        assert _extract_display_name([]) is None
        assert _extract_display_name("string") is None
        assert _extract_display_name(None) is None

    def test_returns_none_for_empty_dict(self):
        assert _extract_display_name({}) is None

    def test_ignores_empty_string_values(self):
        assert _extract_display_name({"real_name": "", "name": "fallback"}) == "fallback"

    def test_prefers_real_name_over_display_name(self):
        raw = {"real_name": "Anya Petrova", "display_name": "Anya"}
        assert _extract_display_name(raw) == "Anya Petrova"


FIXTURES_DMS = json.dumps(
    [
        {
            "channelId": "D00000DM001",
            "isGroup": False,
            "lastActivity": "2026-06-19T10:13:20.111Z",
        },
        {
            "channelId": "G00000GRP01",
            "isGroup": True,
            "lastActivity": "2026-06-18T20:20:00.222Z",
        },
    ]
)


class TestListDms:
    def test_returns_typed_dm_channel_objects(self):
        bridge = _make_bridge({"list_dms": FIXTURES_DMS})
        adapter = SlackMcpAdapter(bridge)
        result = adapter.list_dms()
        assert len(result) == 2
        assert all(isinstance(ch, DmChannel) for ch in result)

    def test_parses_fields_correctly(self):
        bridge = _make_bridge({"list_dms": FIXTURES_DMS})
        adapter = SlackMcpAdapter(bridge)
        result = adapter.list_dms()
        assert result[0].channel_id == "D00000DM001"
        assert result[0].is_group is False
        assert result[0].last_activity_ts > 0.0
        assert result[1].channel_id == "G00000GRP01"
        assert result[1].is_group is True
        assert result[1].last_activity_ts > 0.0
        assert result[0].last_activity_ts > result[1].last_activity_ts

    def test_default_passes_include_dormant_false(self):
        bridge = _make_bridge({"list_dms": "[]"})
        adapter = SlackMcpAdapter(bridge)
        adapter.list_dms()
        call_args = bridge.call_tool.call_args
        assert call_args[0][0] == "list_dms"
        assert call_args[0][1] == {"includeDormant": False}

    def test_include_dormant_true_passes_correctly(self):
        bridge = _make_bridge({"list_dms": "[]"})
        adapter = SlackMcpAdapter(bridge)
        adapter.list_dms(include_dormant=True)
        call_args = bridge.call_tool.call_args
        assert call_args[0][0] == "list_dms"
        assert call_args[0][1] == {"includeDormant": True}

    def test_returns_empty_on_bridge_exception(self):
        bridge = MagicMock()
        bridge.call_tool = MagicMock(side_effect=Exception("connection failed"))
        adapter = SlackMcpAdapter(bridge)
        assert adapter.list_dms() == []

    def test_returns_empty_on_non_json_payload(self):
        bridge = _make_bridge({"list_dms": "not valid json {"})
        adapter = SlackMcpAdapter(bridge)
        assert adapter.list_dms() == []

    def test_dict_wrapped_response(self):
        wrapped = json.dumps(
            {
                "channels": [
                    {
                        "channelId": "D00000DM005",
                        "isGroup": False,
                        "lastActivity": "2026-06-16T15:06:40.333Z",
                    },
                ],
            }
        )
        bridge = _make_bridge({"list_dms": wrapped})
        adapter = SlackMcpAdapter(bridge)
        result = adapter.list_dms()
        assert len(result) == 1
        assert result[0].channel_id == "D00000DM005"

    def test_iso8601_last_activity_parsed_to_epoch(self):
        fixture = json.dumps(
            [
                {
                    "channelId": "D00000DM010",
                    "isGroup": False,
                    "lastActivity": "2026-07-28T13:47:54.920Z",
                },
            ]
        )
        bridge = _make_bridge({"list_dms": fixture})
        adapter = SlackMcpAdapter(bridge)
        result = adapter.list_dms()
        assert len(result) == 1
        assert result[0].last_activity_ts > 1_000_000_000.0
        assert result[0].last_activity_ts != 0.0

    def test_stale_iso8601_produces_old_epoch(self):
        fixture = json.dumps(
            [
                {
                    "channelId": "D00000DM011",
                    "isGroup": False,
                    "lastActivity": "2020-01-01T00:00:00.000Z",
                },
            ]
        )
        bridge = _make_bridge({"list_dms": fixture})
        adapter = SlackMcpAdapter(bridge)
        result = adapter.list_dms()
        assert result[0].last_activity_ts < 1_600_000_000.0

    def test_snake_case_fields_still_supported(self):
        fixture = json.dumps(
            [
                {
                    "channel_id": "D00000DM012",
                    "is_group": False,
                    "last_activity_ts": 1781900000.0,
                },
            ]
        )
        bridge = _make_bridge({"list_dms": fixture})
        adapter = SlackMcpAdapter(bridge)
        result = adapter.list_dms()
        assert result[0].channel_id == "D00000DM012"
        assert result[0].last_activity_ts == 1781900000.0

    def test_filter_group_dms_via_is_group(self):
        bridge = _make_bridge({"list_dms": FIXTURES_DMS})
        adapter = SlackMcpAdapter(bridge)
        result = adapter.list_dms()
        group_dms = [ch for ch in result if ch.is_group]
        one_on_one = [ch for ch in result if not ch.is_group]
        assert len(group_dms) == 1
        assert group_dms[0].channel_id == "G00000GRP01"
        assert len(one_on_one) == 1
        assert one_on_one[0].channel_id == "D00000DM001"

    def test_is_group_defaults_to_false(self):
        fixture = json.dumps(
            [
                {
                    "channelId": "D00000DM020",
                    "lastActivity": "2026-06-19T10:00:00.000Z",
                },
            ]
        )
        bridge = _make_bridge({"list_dms": fixture})
        adapter = SlackMcpAdapter(bridge)
        result = adapter.list_dms()
        assert len(result) == 1
        assert result[0].is_group is False

    def test_all_group_dms_filtered(self):
        fixture = json.dumps(
            [
                {
                    "channelId": "G00000GRP10",
                    "isGroup": True,
                    "lastActivity": "2026-06-19T10:00:00.000Z",
                },
                {
                    "channelId": "G00000GRP11",
                    "isGroup": True,
                    "lastActivity": "2026-06-18T10:00:00.000Z",
                },
                {
                    "channelId": "D00000DM030",
                    "isGroup": False,
                    "lastActivity": "2026-06-17T10:00:00.000Z",
                },
            ]
        )
        bridge = _make_bridge({"list_dms": fixture})
        adapter = SlackMcpAdapter(bridge)
        result = adapter.list_dms()
        group_dms = [ch for ch in result if ch.is_group]
        one_on_one = [ch for ch in result if not ch.is_group]
        assert len(group_dms) == 2
        assert len(one_on_one) == 1

    def test_no_deprecated_methods_on_adapter(self):
        bridge = _make_bridge()
        adapter = SlackMcpAdapter(bridge)
        assert not hasattr(adapter, "list_mpim_channels")
        assert not hasattr(adapter, "list_participant_channels")
        assert not hasattr(adapter, "list_group_dms")


class TestParseActivityTs:
    def test_iso8601_with_z_suffix(self):
        ts = _parse_activity_ts("2026-07-28T13:47:54.920Z")
        assert ts > 1_000_000_000.0

    def test_iso8601_with_offset(self):
        ts = _parse_activity_ts("2026-07-28T13:47:54.920+00:00")
        assert ts > 1_000_000_000.0

    def test_numeric_float_passthrough(self):
        assert _parse_activity_ts(1781900000.111) == 1781900000.111

    def test_numeric_int_passthrough(self):
        assert _parse_activity_ts(1781900000) == 1781900000.0

    def test_invalid_string_returns_zero(self):
        assert _parse_activity_ts("not-a-date") == 0.0

    def test_none_returns_zero(self):
        assert _parse_activity_ts(None) == 0.0

    def test_zero_fallback(self):
        assert _parse_activity_ts(0.0) == 0.0
