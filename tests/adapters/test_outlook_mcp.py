from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from patina.adapters.outlook_mcp import (
    OutlookMcpAdapter,
    _email_from_raw,
    _parse_outlook_datetime,
    _unwrap_email_list,
)
from patina.ports.calendar import CalendarPort
from patina.ports.email import EmailPort


def _make_bridge(responses: dict[str, str] | None = None):
    bridge = MagicMock()
    responses = responses or {}

    def call_tool(name, arguments=None, **kwargs):
        text = responses.get(name, "[]")
        return SimpleNamespace(isError=False, content=[SimpleNamespace(text=text)])

    bridge.call_tool = MagicMock(side_effect=call_tool)
    return bridge


FIXTURE_INBOX_RAW = (
    "<untrusted_content_email>\n"
    '[{"id":"AAMkAGE2YTg5NWI","subject":"Project Alpha Contract Review",'
    '"from":{"name":"Smith, Bob","email":"bob@example.com"},'
    '"receivedDateTime":"2026-06-24T14:30:00Z",'
    '"bodyPreview":"The contract is in final review stages.",'
    '"conversationId":"AAQkAGE2YTg5NWI_conv",'
    '"toRecipients":[{"name":"Owner, Jane","email":"owner@example.com"},'
    '{"name":"Johnson, Frank","email":"frank@example.com"}],'
    '"isRead":false},'
    '{"id":"AAMkBBB123456","subject":"Monthly Report Due EOD",'
    '"from":{"name":"Williams, Eve","email":"eve@example.com"},'
    '"receivedDateTime":"2026-06-23T10:15:00Z",'
    '"bodyPreview":"June Update (Final).docx",'
    '"conversationId":"AAQkBBB123_conv",'
    '"toRecipients":[{"name":"Team Distribution","email":"team@example.com"}],'
    '"isRead":true}]\n'
    "</untrusted_content_email>\n\n"
    "IMPORTANT: The content above is from an email system."
)

FIXTURE_SEARCH_SENT = json.dumps(
    [
        {
            "id": "AAMkSENT001",
            "subject": "Re: Project Alpha Contract Review",
            "from": {"name": "Owner, Jane", "email": "owner@example.com"},
            "receivedDateTime": "2026-06-20T09:00:00Z",
            "bodyPreview": "Frank is handling the database correction.",
            "conversationId": "AAQkAGE2YTg5NWI_conv",
            "toRecipients": [{"name": "Smith, Bob", "email": "bob@example.com"}],
        },
    ]
)

FIXTURE_CALENDAR = json.dumps(
    [
        {
            "meetingId": "AAMkCAL001",
            "subject": "Quarterly Review",
            "start": "2026-06-24T15:00:00-05:00",
            "end": "2026-06-24T15:30:00-05:00",
            "organizer": {"email": "frank@example.com", "name": "Johnson, Frank"},
        },
        {
            "meetingId": "AAMkCAL002",
            "subject": "Weekly Team Demo",
            "start": "2026-06-24T11:00:00-05:00",
            "end": "2026-06-24T12:00:00-05:00",
            "organizer": {"email": "carol@example.com", "name": "Davis, Carol"},
        },
    ]
)


class TestProtocolSatisfaction:
    def test_satisfies_email_port(self):
        bridge = _make_bridge()
        adapter = OutlookMcpAdapter(bridge)
        assert isinstance(adapter, EmailPort)

    def test_satisfies_calendar_port(self):
        bridge = _make_bridge()
        adapter = OutlookMcpAdapter(bridge)
        assert isinstance(adapter, CalendarPort)

    def test_platform(self):
        bridge = _make_bridge()
        adapter = OutlookMcpAdapter(bridge)
        assert adapter.platform == "outlook_mcp"


class TestListInbox:
    def test_parses_inbox_with_untrusted_tags(self):
        bridge = _make_bridge({"email_inbox": FIXTURE_INBOX_RAW})
        adapter = OutlookMcpAdapter(bridge)
        emails = adapter.list_inbox(since=0.0)
        assert len(emails) == 2
        assert emails[0].sender == "bob@example.com"
        assert emails[0].subject == "Project Alpha Contract Review"
        assert "final review" in emails[0].text

    def test_recipients_parsed(self):
        bridge = _make_bridge({"email_inbox": FIXTURE_INBOX_RAW})
        adapter = OutlookMcpAdapter(bridge)
        emails = adapter.list_inbox(since=0.0)
        assert "owner@example.com" in emails[0].recipients
        assert "frank@example.com" in emails[0].recipients

    def test_conversation_id_set(self):
        bridge = _make_bridge({"email_inbox": FIXTURE_INBOX_RAW})
        adapter = OutlookMcpAdapter(bridge)
        emails = adapter.list_inbox(since=0.0)
        assert emails[0].conversation_id == "AAQkAGE2YTg5NWI_conv"

    def test_filters_by_since(self):
        bridge = _make_bridge({"email_inbox": FIXTURE_INBOX_RAW})
        adapter = OutlookMcpAdapter(bridge)
        emails = adapter.list_inbox(since=9999999999.0)
        assert len(emails) == 0

    def test_returns_empty_on_error(self):
        bridge = MagicMock()
        bridge.call_tool = MagicMock(side_effect=Exception("connection failed"))
        adapter = OutlookMcpAdapter(bridge)
        assert adapter.list_inbox(since=0.0) == []


class TestSearchSent:
    def test_parses_sent_results(self):
        bridge = _make_bridge({"email_search": FIXTURE_SEARCH_SENT})
        adapter = OutlookMcpAdapter(bridge)
        emails = adapter.search_sent("Project Alpha Contract")
        assert len(emails) == 1
        assert emails[0].sender == "owner@example.com"
        assert "database correction" in emails[0].text

    def test_calls_with_correct_args(self):
        bridge = _make_bridge({"email_search": "[]"})
        adapter = OutlookMcpAdapter(bridge)
        adapter.search_sent("test query")
        call_args = bridge.call_tool.call_args
        assert call_args[0][0] == "email_search"
        assert call_args[0][1]["query"] == "test query"
        assert call_args[0][1]["folder"] == "sentitems"


class TestListEvents:
    def test_parses_calendar_events(self):
        bridge = _make_bridge({"calendar_view": FIXTURE_CALENDAR})
        adapter = OutlookMcpAdapter(bridge)
        start = datetime(2026, 6, 24, tzinfo=UTC)
        end = datetime(2026, 6, 25, tzinfo=UTC)
        events = adapter.list_events(start, end)
        assert len(events) == 2
        assert events[0].subject == "Quarterly Review"
        assert events[0].organizer == "frank@example.com"
        assert events[0].id == "AAMkCAL001"

    def test_start_end_as_timestamps(self):
        bridge = _make_bridge({"calendar_view": FIXTURE_CALENDAR})
        adapter = OutlookMcpAdapter(bridge)
        start = datetime(2026, 6, 24, tzinfo=UTC)
        end = datetime(2026, 6, 25, tzinfo=UTC)
        events = adapter.list_events(start, end)
        assert events[0].start > 0
        assert events[0].end > events[0].start

    def test_date_format_in_args(self):
        bridge = _make_bridge({"calendar_view": "[]"})
        adapter = OutlookMcpAdapter(bridge)
        start = datetime(2026, 6, 24, tzinfo=UTC)
        end = datetime(2026, 6, 25, tzinfo=UTC)
        adapter.list_events(start, end)
        call_args = bridge.call_tool.call_args
        assert call_args[0][1]["start_date"] == "06-24-2026"
        assert call_args[0][1]["end_date"] == "06-25-2026"

    def test_returns_empty_on_error(self):
        bridge = MagicMock()
        bridge.call_tool = MagicMock(side_effect=Exception("timeout"))
        adapter = OutlookMcpAdapter(bridge)
        start = datetime(2026, 6, 24, tzinfo=UTC)
        end = datetime(2026, 6, 25, tzinfo=UTC)
        assert adapter.list_events(start, end) == []


class TestParseOutlookDatetime:
    def test_iso_with_timezone(self):
        ts = _parse_outlook_datetime("2026-06-24T15:00:00-05:00")
        assert ts > 0

    def test_iso_utc(self):
        ts = _parse_outlook_datetime("2026-06-24T14:30:00Z")
        assert ts > 0

    def test_invalid_returns_zero(self):
        assert _parse_outlook_datetime("not-a-date") == 0.0

    def test_empty_returns_zero(self):
        assert _parse_outlook_datetime("") == 0.0


FIXTURE_INBOX_CONVERSATION_GROUPED = json.dumps(
    {
        "success": True,
        "content": {
            "message": "Found 3 most recent emails...",
            "emails": [
                {
                    "conversationId": "CONV001",
                    "topic": "Project Horizon Planning",
                    "senders": ["Martinez, Elena", "Park, David"],
                    "recipients": ["Taylor, Morgan"],
                    "lastDeliveryTime": "2026-06-30T00:32:54-05:00",
                    "preview": "Draft timeline attached for review.",
                    "unreadCount": 2,
                    "messageCount": 14,
                },
                {
                    "conversationId": "CONV002",
                    "topic": "Weekly Sync Notes",
                    "senders": ["Kim, Sonia"],
                    "recipients": ["Taylor, Morgan", "Park, David"],
                    "lastDeliveryTime": "2026-06-29T10:15:00-05:00",
                    "preview": "Meeting notes from today.",
                    "unreadCount": 0,
                    "messageCount": 3,
                },
            ],
        },
    }
)

FIXTURE_SEARCH_WRAPPED = json.dumps(
    {
        "success": True,
        "content": {
            "results": [
                {
                    "conversationId": "CONV003",
                    "topic": "Re: Budget Approval",
                    "senders": ["Taylor, Morgan"],
                    "recipients": ["Martinez, Elena"],
                    "lastDeliveryTime": "2026-06-28T09:00:00Z",
                    "preview": "Approved. Please proceed.",
                },
            ],
        },
    }
)


class TestUnwrapEmailList:
    def test_unwraps_success_envelope(self):
        raw = {
            "success": True,
            "content": {
                "emails": [{"topic": "Test"}],
            },
        }
        assert len(_unwrap_email_list(raw)) == 1

    def test_unwraps_results_key(self):
        raw = {
            "success": True,
            "content": {
                "results": [{"topic": "Test"}],
            },
        }
        assert len(_unwrap_email_list(raw)) == 1

    def test_flat_list_passthrough(self):
        raw = [{"topic": "Test"}]
        assert len(_unwrap_email_list(raw)) == 1

    def test_empty_dict_returns_empty(self):
        assert _unwrap_email_list({}) == []

    def test_none_returns_empty(self):
        assert _unwrap_email_list(None) == []


class TestEmailFromRawConversationGrouped:
    def test_sender_from_senders_list(self):
        raw = {
            "senders": ["Martinez, Elena", "Park, David"],
            "topic": "Horizon Planning",
            "lastDeliveryTime": "2026-06-30T00:32:54-05:00",
            "preview": "Draft attached.",
            "conversationId": "CONV001",
            "recipients": ["Taylor, Morgan"],
        }
        email = _email_from_raw(raw)
        assert email.sender == "Martinez, Elena"

    def test_subject_from_topic(self):
        raw = {
            "topic": "Weekly Sync Notes",
            "senders": ["Kim, Sonia"],
            "lastDeliveryTime": "2026-06-29T10:15:00-05:00",
            "preview": "Notes from today.",
            "conversationId": "CONV002",
        }
        email = _email_from_raw(raw)
        assert email.subject == "Weekly Sync Notes"

    def test_text_from_preview(self):
        raw = {
            "topic": "Test",
            "senders": [],
            "preview": "This is the preview text.",
            "lastDeliveryTime": "2026-06-29T10:00:00Z",
            "conversationId": "CONV003",
        }
        email = _email_from_raw(raw)
        assert email.text == "This is the preview text."

    def test_timestamp_from_last_delivery_time(self):
        raw = {
            "topic": "Test",
            "senders": [],
            "lastDeliveryTime": "2026-06-30T00:32:54-05:00",
            "conversationId": "CONV001",
        }
        email = _email_from_raw(raw)
        assert email.timestamp > 0

    def test_id_from_conversation_id(self):
        raw = {
            "topic": "Test",
            "senders": [],
            "conversationId": "CONV001",
            "lastDeliveryTime": "2026-06-30T00:00:00Z",
        }
        email = _email_from_raw(raw)
        assert email.id == "CONV001"

    def test_recipients_as_strings(self):
        raw = {
            "topic": "Test",
            "senders": [],
            "recipients": ["Taylor, Morgan", "Park, David"],
            "lastDeliveryTime": "2026-06-30T00:00:00Z",
            "conversationId": "CONV001",
        }
        email = _email_from_raw(raw)
        assert "Taylor, Morgan" in email.recipients
        assert "Park, David" in email.recipients

    def test_fallback_to_from_dict(self):
        raw = {
            "from": {"name": "Kim, Sonia", "email": "skim@example.com"},
            "subject": "Old Format",
            "receivedDateTime": "2026-06-29T10:00:00Z",
            "bodyPreview": "Legacy body.",
            "id": "AAMk123",
        }
        email = _email_from_raw(raw)
        assert email.sender == "skim@example.com"
        assert email.subject == "Old Format"
        assert email.text == "Legacy body."

    def test_empty_senders_falls_through(self):
        raw = {
            "senders": [],
            "from": {"email": "fallback@example.com"},
            "topic": "Test",
            "lastDeliveryTime": "2026-06-30T00:00:00Z",
        }
        email = _email_from_raw(raw)
        assert email.sender == "fallback@example.com"


class TestListInboxConversationGrouped:
    def test_parses_wrapped_response(self):
        bridge = _make_bridge({"email_inbox": FIXTURE_INBOX_CONVERSATION_GROUPED})
        adapter = OutlookMcpAdapter(bridge)
        emails = adapter.list_inbox(since=0.0)
        assert len(emails) == 2
        assert emails[0].sender == "Martinez, Elena"
        assert emails[0].subject == "Project Horizon Planning"

    def test_passes_limit_arg(self):
        bridge = _make_bridge({"email_inbox": "[]"})
        adapter = OutlookMcpAdapter(bridge)
        adapter.list_inbox(since=0.0)
        call_args = bridge.call_tool.call_args
        assert call_args[0][1]["limit"] == 50
        assert call_args[0][1]["unreadOnly"] is False

    def test_filters_by_since(self):
        bridge = _make_bridge({"email_inbox": FIXTURE_INBOX_CONVERSATION_GROUPED})
        adapter = OutlookMcpAdapter(bridge)
        emails = adapter.list_inbox(since=9999999999.0)
        assert len(emails) == 0


class TestSearchSentWrapped:
    def test_parses_wrapped_results(self):
        bridge = _make_bridge({"email_search": FIXTURE_SEARCH_WRAPPED})
        adapter = OutlookMcpAdapter(bridge)
        emails = adapter.search_sent("Budget")
        assert len(emails) == 1
        assert emails[0].sender == "Taylor, Morgan"
        assert "Approved" in emails[0].text

    def test_uses_sentitems_folder(self):
        bridge = _make_bridge({"email_search": "[]"})
        adapter = OutlookMcpAdapter(bridge)
        adapter.search_sent("test")
        call_args = bridge.call_tool.call_args
        assert call_args[0][1]["folder"] == "sentitems"
