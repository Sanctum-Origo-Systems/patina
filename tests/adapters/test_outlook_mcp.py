from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from patina.adapters._source_facts import get_fact
from patina.adapters.outlook_mcp import (
    OutlookMcpAdapter,
    _calendar_event_from_raw,
    _email_from_raw,
    _is_meeting_message,
    _parse_outlook_datetime,
    _strip_caution_banner,
    _unwrap_email_list,
    normalize_sender,
)
from patina.ingest import _events_to_chat_messages, ingest_live
from patina.models import SourceFactState
from patina.ports.calendar import CalendarPort
from patina.ports.email import EmailPort
from patina.store import connect, get_db_path


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


# Key layout of a live ``calendar_view`` item (#651): no attendee field at all.
LIVE_CALENDAR_VIEW_ITEM = {
    "meetingId": "AAMkADExampleEvt651=",
    "subject": "Weekly Sync — the quick brown fox",
    "start": "2026-11-10T09:00:00-06:00",
    "end": "2026-11-10T09:30:00-06:00",
    "organizer": {"email": "dana.brook@example.com", "name": "Brook, Dana"},
}


class TestCalendarAttendees:
    def test_live_calendar_view_item_has_no_attendees(self):
        bridge = _make_bridge({"calendar_view": json.dumps([LIVE_CALENDAR_VIEW_ITEM])})
        adapter = OutlookMcpAdapter(bridge)
        start = datetime(2026, 11, 10, tzinfo=UTC)
        end = datetime(2026, 11, 11, tzinfo=UTC)
        (event,) = adapter.list_events(start, end)
        assert event.attendees == []
        assert "attendees" not in event.source_facts
        assert event.source_facts == {
            "message_id": "AAMkADExampleEvt651=",
            "sender_key": "dana.brook@example.com",
        }

    def test_display_name_string_attendees_kept_with_punctuation(self):
        raw = {**LIVE_CALENDAR_VIEW_ITEM, "attendees": ["Example, Jordan", "Rivera, Sam (Ext)"]}
        event = _calendar_event_from_raw(raw)
        assert event.attendees == ["Example, Jordan", "Rivera, Sam (Ext)"]
        assert event.source_facts["attendees"] == ["Example, Jordan", "Rivera, Sam (Ext)"]

    def test_dict_attendees_email_else_name(self):
        raw = {
            **LIVE_CALENDAR_VIEW_ITEM,
            "attendees": [
                {"email": "jordan.example@example.com", "name": "Example, Jordan"},
                {"name": "Müller, Avery"},
                {"type": "required"},
            ],
        }
        event = _calendar_event_from_raw(raw)
        assert event.attendees == ["jordan.example@example.com", "Müller, Avery"]

    def test_non_list_attendees_ignored(self):
        event = _calendar_event_from_raw({**LIVE_CALENDAR_VIEW_ITEM, "attendees": "n/a"})
        assert event.attendees == []


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
        assert "This is the preview text." in email.text

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
        assert "Legacy body." in email.text

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


class TestParticipantIndexing:
    def test_all_senders_in_text(self):
        raw = {
            "conversationId": "CONV001",
            "topic": "Launch Planning",
            "senders": ["Martinez, Elena", "Park, David", "Kim, Sonia"],
            "recipients": ["Taylor, Morgan"],
            "lastDeliveryTime": "2026-06-30T00:00:00Z",
            "preview": "Timeline confirmed.",
        }
        email = _email_from_raw(raw)
        assert "Martinez, Elena" in email.text
        assert "Park, David" in email.text
        assert "Kim, Sonia" in email.text

    def test_subject_in_text(self):
        raw = {
            "topic": "Budget Review Q3",
            "senders": ["Park, David"],
            "lastDeliveryTime": "2026-06-30T00:00:00Z",
            "preview": "See attached.",
            "conversationId": "CONV002",
        }
        email = _email_from_raw(raw)
        assert "[Subject: Budget Review Q3]" in email.text

    def test_preview_in_text(self):
        raw = {
            "topic": "Test",
            "senders": ["Park, David"],
            "lastDeliveryTime": "2026-06-30T00:00:00Z",
            "preview": "The actual preview content here.",
            "conversationId": "CONV003",
        }
        email = _email_from_raw(raw)
        assert "The actual preview content here." in email.text

    def test_single_sender_as_participant(self):
        raw = {
            "topic": "Solo Thread",
            "senders": ["Kim, Sonia"],
            "lastDeliveryTime": "2026-06-30T00:00:00Z",
            "preview": "Just me.",
            "conversationId": "CONV004",
        }
        email = _email_from_raw(raw)
        assert "[Participants: Kim, Sonia]" in email.text

    def test_no_senders_falls_back_to_from(self):
        raw = {
            "from": {"email": "legacy@example.com"},
            "subject": "Old Email",
            "receivedDateTime": "2026-06-29T10:00:00Z",
            "bodyPreview": "Legacy content.",
            "id": "AAMk999",
        }
        email = _email_from_raw(raw)
        assert "legacy@example.com" in email.text

    def test_secondary_sender_searchable(self):
        """The key scenario: last sender is auto-reply, but real
        sender is a different participant deeper in the thread."""
        raw = {
            "conversationId": "CONV005",
            "topic": "Conference Planning",
            "senders": [
                "Rivera, Lucia",
                "Nguyen, Marcus",
                "Chen, Wei",
            ],
            "recipients": ["Taylor, Morgan"],
            "lastDeliveryTime": "2026-06-30T12:00:00Z",
            "preview": "Auto-reply: I am out of office.",
        }
        email = _email_from_raw(raw)
        assert email.sender == "Rivera, Lucia"
        assert "Nguyen, Marcus" in email.text
        assert "Chen, Wei" in email.text


class TestStripCautionBanner:
    def test_strips_multiline_banner(self):
        body = (
            "CAUTION: This email originated from outside of the organization. "
            "Do not click links or open attachments unless you recognize the sender "
            "and know the content is safe.\n\n"
            "++ Dana"
        )
        assert _strip_caution_banner(body) == "++ Dana"

    def test_strips_banner_with_confirm_variant(self):
        body = (
            "CAUTION: This email originated from outside of the organization. "
            "Do not click links or open attachments unless you can confirm the sender "
            "and know the content is safe.\n"
            "Looks good, thanks"
        )
        assert _strip_caution_banner(body) == "Looks good, thanks"

    def test_strips_short_banner(self):
        body = (
            "CAUTION: This email originated from outside of the organization.\n\n"
            "Please review the attached."
        )
        assert _strip_caution_banner(body) == "Please review the attached."

    def test_no_banner_unchanged(self):
        body = "Just a normal email body with no banner."
        assert _strip_caution_banner(body) == body

    def test_empty_string(self):
        assert _strip_caution_banner("") == ""

    def test_banner_only_returns_empty(self):
        body = (
            "CAUTION: This email originated from outside of the organization. "
            "Do not click links or open attachments unless you recognize the sender "
            "and know the content is safe."
        )
        assert _strip_caution_banner(body) == ""

    def test_case_insensitive(self):
        body = (
            "caution: this email originated from outside of the organization. "
            "do not click links or open attachments unless you can confirm the sender "
            "and know the content is safe.\n"
            "Approved."
        )
        assert _strip_caution_banner(body) == "Approved."


class TestEmailFromRawCautionBanner:
    def test_banner_stripped_from_preview(self):
        raw = {
            "conversationId": "CONV_EXT001",
            "topic": "Re: Invoice Approval",
            "senders": ["Patel, Ravi"],
            "recipients": ["Taylor, Morgan"],
            "lastDeliveryTime": "2026-07-01T09:00:00Z",
            "preview": (
                "CAUTION: This email originated from outside of the organization. "
                "Do not click links or open attachments unless you recognize the sender "
                "and know the content is safe.\n\n"
                "++ Dana"
            ),
        }
        email = _email_from_raw(raw)
        assert "CAUTION" not in email.text
        assert "++ Dana" in email.text

    def test_banner_stripped_from_body_preview(self):
        raw = {
            "id": "AAMkEXT002",
            "from": {"name": "Chen, Li", "email": "lchen@example.com"},
            "subject": "Re: Contract Draft",
            "receivedDateTime": "2026-07-01T10:00:00Z",
            "bodyPreview": (
                "CAUTION: This email originated from outside of the organization. "
                "Do not click links or open attachments unless you can confirm the sender "
                "and know the content is safe.\n"
                "Looks good, thanks"
            ),
        }
        email = _email_from_raw(raw)
        assert "CAUTION" not in email.text
        assert "Looks good, thanks" in email.text

    def test_no_banner_unaffected(self):
        raw = {
            "conversationId": "CONV_INT001",
            "topic": "Team Lunch",
            "senders": ["Kim, Sonia"],
            "recipients": ["Taylor, Morgan"],
            "lastDeliveryTime": "2026-07-01T11:00:00Z",
            "preview": "How about noon at the cafe?",
        }
        email = _email_from_raw(raw)
        assert "How about noon at the cafe?" in email.text


FIXTURE_INBOX_WITH_MEETING_REQUEST = json.dumps(
    [
        {
            "id": "AAMkNORM001",
            "subject": "Quarterly Budget Discussion",
            "from": {"name": "Park, David", "email": "dpark@example.com"},
            "receivedDateTime": "2026-07-10T09:00:00Z",
            "bodyPreview": "Please review the attached figures.",
            "conversationId": "CONV_NORM001",
            "toRecipients": [{"name": "Taylor, Morgan", "email": "mtaylor@example.com"}],
            "messageClass": "IPM.Note",
        },
        {
            "id": "AAMkMTG001",
            "subject": "Weekly Standup",
            "from": {"name": "Kim, Sonia", "email": "skim@example.com"},
            "receivedDateTime": "2026-07-10T10:00:00Z",
            "bodyPreview": "When: Wednesday 10:00 AM",
            "conversationId": "CONV_MTG001",
            "toRecipients": [{"name": "Taylor, Morgan", "email": "mtaylor@example.com"}],
            "messageClass": "IPM.Schedule.Meeting.Request",
        },
        {
            "id": "AAMkMTG002",
            "subject": "Re: Weekly Standup",
            "from": {"name": "Rivera, Lucia", "email": "lrivera@example.com"},
            "receivedDateTime": "2026-07-10T10:05:00Z",
            "bodyPreview": "Accepted",
            "conversationId": "CONV_MTG002",
            "toRecipients": [{"name": "Taylor, Morgan", "email": "mtaylor@example.com"}],
            "messageClass": "IPM.Schedule.Meeting.Resp.Pos",
        },
        {
            "id": "AAMkMTG003",
            "subject": "Cancelled: Weekly Standup",
            "from": {"name": "Kim, Sonia", "email": "skim@example.com"},
            "receivedDateTime": "2026-07-10T10:10:00Z",
            "bodyPreview": "This meeting has been cancelled.",
            "conversationId": "CONV_MTG003",
            "toRecipients": [{"name": "Taylor, Morgan", "email": "mtaylor@example.com"}],
            "messageClass": "IPM.Schedule.Meeting.Canceled",
        },
    ]
)


class TestIsMeetingMessage:
    def test_meeting_request(self):
        assert _is_meeting_message({"messageClass": "IPM.Schedule.Meeting.Request"})

    def test_meeting_response_positive(self):
        assert _is_meeting_message({"messageClass": "IPM.Schedule.Meeting.Resp.Pos"})

    def test_meeting_canceled(self):
        assert _is_meeting_message({"messageClass": "IPM.Schedule.Meeting.Canceled"})

    def test_normal_email(self):
        assert not _is_meeting_message({"messageClass": "IPM.Note"})

    def test_no_message_class(self):
        assert not _is_meeting_message({"subject": "Hello"})

    def test_empty_message_class(self):
        assert not _is_meeting_message({"messageClass": ""})

    def test_snake_case_key(self):
        assert _is_meeting_message({"message_class": "IPM.Schedule.Meeting.Request"})


class TestMeetingRequestFilter:
    def test_meeting_request_skipped_in_inbox(self):
        bridge = _make_bridge({"email_inbox": FIXTURE_INBOX_WITH_MEETING_REQUEST})
        adapter = OutlookMcpAdapter(bridge)
        emails = adapter.list_inbox(since=0.0)
        assert len(emails) == 1
        assert emails[0].subject == "Quarterly Budget Discussion"

    def test_normal_email_returned_in_inbox(self):
        fixture = json.dumps(
            [
                {
                    "id": "AAMkNOTE001",
                    "subject": "Project Status Update",
                    "from": {"name": "Chen, Wei", "email": "wchen@example.com"},
                    "receivedDateTime": "2026-07-10T08:00:00Z",
                    "bodyPreview": "Everything is on track.",
                    "conversationId": "CONV_NOTE001",
                    "toRecipients": [{"name": "Taylor, Morgan", "email": "mtaylor@example.com"}],
                    "messageClass": "IPM.Note",
                }
            ]
        )
        bridge = _make_bridge({"email_inbox": fixture})
        adapter = OutlookMcpAdapter(bridge)
        emails = adapter.list_inbox(since=0.0)
        assert len(emails) == 1
        assert emails[0].subject == "Project Status Update"

    def test_emails_without_message_class_still_returned(self):
        fixture = json.dumps(
            [
                {
                    "id": "AAMkNOCLASS001",
                    "subject": "No Class Field",
                    "from": {"name": "Park, David", "email": "dpark@example.com"},
                    "receivedDateTime": "2026-07-10T08:00:00Z",
                    "bodyPreview": "This item has no messageClass.",
                    "conversationId": "CONV_NOCLASS001",
                    "toRecipients": [],
                }
            ]
        )
        bridge = _make_bridge({"email_inbox": fixture})
        adapter = OutlookMcpAdapter(bridge)
        emails = adapter.list_inbox(since=0.0)
        assert len(emails) == 1


def _conversation(item_classes=..., preview: str = "", topic: str = "The quick brown fox sync"):
    conv = {
        "conversationId": "CONV_ITEMCLASS001",
        "topic": topic,
        "senders": ["Example, Jordan"],
        "recipients": ["Taylor, Morgan"],
        "preview": preview,
        "receivedDateTime": "2026-11-01T15:04:05Z",
    }
    if item_classes is not ...:
        conv["itemClasses"] = item_classes
    return conv


def _inbox_with(*conversations) -> str:
    return json.dumps({"success": True, "content": {"emails": list(conversations)}})


class TestIsMeetingMessageItemClasses:
    def test_meeting_response_positive(self):
        assert _is_meeting_message(_conversation(["IPM.Schedule.Meeting.Resp.Pos"]))

    def test_meeting_request(self):
        assert _is_meeting_message(_conversation(["IPM.Schedule.Meeting.Request"]))

    def test_meeting_canceled(self):
        assert _is_meeting_message(_conversation(["IPM.Schedule.Meeting.Canceled"]))

    def test_all_meeting_classes(self):
        classes = ["IPM.Schedule.Meeting.Request", "IPM.Schedule.Meeting.Resp.Pos"]
        assert _is_meeting_message(_conversation(classes))

    def test_note(self):
        assert not _is_meeting_message(_conversation(["IPM.Note"]))

    def test_mixed_note_and_meeting(self):
        classes = ["IPM.Note", "IPM.Schedule.Meeting.Resp.Pos"]
        assert not _is_meeting_message(_conversation(classes))

    def test_missing(self):
        assert not _is_meeting_message(_conversation())

    def test_empty_list(self):
        assert not _is_meeting_message(_conversation([]))

    def test_none(self):
        assert not _is_meeting_message(_conversation(None))

    def test_non_list_string(self):
        assert not _is_meeting_message(_conversation("IPM.Schedule.Meeting.Resp.Pos"))

    def test_non_list_dict(self):
        assert not _is_meeting_message(_conversation({"class": "IPM.Note"}))

    def test_non_string_entry(self):
        assert not _is_meeting_message(_conversation([None, "IPM.Schedule.Meeting.Request"]))

    def test_falls_back_to_message_class_when_item_classes_empty(self):
        conv = _conversation([])
        conv["messageClass"] = "IPM.Schedule.Meeting.Request"
        assert _is_meeting_message(conv)


class TestMeetingFilterItemClasses:
    def _list_inbox(self, *conversations):
        bridge = _make_bridge({"email_inbox": _inbox_with(*conversations)})
        return OutlookMcpAdapter(bridge).list_inbox(since=0.0)

    def test_meeting_acceptance_filtered(self):
        assert self._list_inbox(_conversation(["IPM.Schedule.Meeting.Resp.Pos"])) == []

    def test_meeting_request_filtered(self):
        assert self._list_inbox(_conversation(["IPM.Schedule.Meeting.Request"])) == []

    def test_meeting_canceled_filtered(self):
        assert self._list_inbox(_conversation(["IPM.Schedule.Meeting.Canceled"])) == []

    def test_note_kept(self):
        emails = self._list_inbox(_conversation(["IPM.Note"], preview="Jumps over the lazy dog."))
        assert len(emails) == 1
        assert emails[0].subject == "The quick brown fox sync"
        assert "Jumps over the lazy dog." in emails[0].text

    def test_mixed_note_and_meeting_kept(self):
        classes = ["IPM.Note", "IPM.Schedule.Meeting.Resp.Pos"]
        emails = self._list_inbox(_conversation(classes, preview="Agenda attached."))
        assert len(emails) == 1

    def test_missing_empty_none_and_non_list_kept(self):
        emails = self._list_inbox(
            _conversation(),
            _conversation([]),
            _conversation(None),
            _conversation("IPM.Schedule.Meeting.Resp.Pos"),
        )
        assert len(emails) == 4

    def test_mixed_inbox_page(self):
        emails = self._list_inbox(
            _conversation(["IPM.Note"], preview="Jumps over the lazy dog.", topic="Fox notes"),
            _conversation(["IPM.Schedule.Meeting.Resp.Pos"]),
            _conversation(["IPM.Schedule.Meeting.Request"], topic="Dog walk"),
        )
        assert [e.subject for e in emails] == ["Fox notes"]


class TestGetRawMessage:
    def test_returns_unfiltered_meeting_payload(self):
        conv = _conversation(["IPM.Schedule.Meeting.Resp.Pos"])
        bridge = _make_bridge({"email_inbox": _inbox_with(conv)})
        adapter = OutlookMcpAdapter(bridge)

        assert adapter.get_raw_message("CONV_ITEMCLASS001") == conv
        assert adapter.get_raw_message("CONV_MISSING") is None
        assert bridge.call_tool.call_count == 1
        assert bridge.call_tool.call_args.args[0] == "email_inbox"

    def test_matches_message_id(self):
        raw = {"id": "AAMk_MSG001", "messageClass": "IPM.Schedule.Meeting.Request"}
        bridge = _make_bridge({"email_inbox": _inbox_with(raw)})
        assert OutlookMcpAdapter(bridge).get_raw_message("AAMk_MSG001") == raw

    def test_bridge_error_returns_none(self):
        bridge = MagicMock()
        bridge.call_tool.side_effect = RuntimeError("down")
        assert OutlookMcpAdapter(bridge).get_raw_message("CONV_ITEMCLASS001") is None


class TestNormalizeSender:
    def test_legacy_dn_returns_empty(self):
        dn = (
            "/O=EXCHANGELABS/OU=EXCHANGE ADMINISTRATIVE GROUP"
            " (FYDIBOHF23SPDLT)/CN=RECIPIENTS/CN=abc123def456"
        )
        assert normalize_sender(dn) == ""

    def test_legacy_dn_lowercase(self):
        assert normalize_sender("/o=EXCHANGELABS/ou=GROUP/cn=abc") == ""

    def test_parenthetical_stripped(self):
        assert normalize_sender("Brook, Dana (Marketing)") == "Brook, Dana"

    def test_truncated_bracket_stripped(self):
        assert normalize_sender("Brook, Dana (") == "Brook, Dana"

    def test_clean_name_unchanged(self):
        assert normalize_sender("Park, David") == "Park, David"

    def test_empty_unchanged(self):
        assert normalize_sender("") == ""

    def test_email_address_unchanged(self):
        assert normalize_sender("dpark@example.com") == "dpark@example.com"


class TestSenderNormalizationInEmail:
    def test_legacy_dn_falls_back_to_from_email(self):
        raw = {
            "senders": ["/O=EXCHANGELABS/OU=EXCHANGE ADMINISTRATIVE GROUP/CN=RECIPIENTS/CN=abc123"],
            "from": {"name": "Brook, Dana", "email": "dbrook@example.com"},
            "topic": "Contract Review",
            "lastDeliveryTime": "2026-10-01T09:00:00Z",
            "conversationId": "CONV_DN001",
        }
        email = _email_from_raw(raw)
        assert email.sender == "dbrook@example.com"
        assert email.sender_name == "Brook, Dana"
        assert "/O=" not in email.text

    def test_legacy_dn_no_from_fallback(self):
        raw = {
            "senders": ["/O=EXCHANGELABS/OU=GROUP/CN=RECIPIENTS/CN=xyz789"],
            "topic": "Orphan DN",
            "lastDeliveryTime": "2026-10-01T09:00:00Z",
            "conversationId": "CONV_DN002",
        }
        email = _email_from_raw(raw)
        assert email.sender == ""
        assert email.sender_name is None

    def test_parenthetical_stripped_from_senders(self):
        raw = {
            "senders": ["Brook, Dana (Marketing)"],
            "topic": "Team Update",
            "lastDeliveryTime": "2026-10-01T09:00:00Z",
            "conversationId": "CONV_PAR001",
        }
        email = _email_from_raw(raw)
        assert email.sender == "Brook, Dana"
        assert email.sender_name == "Brook, Dana"

    def test_truncated_bracket_stripped(self):
        raw = {
            "senders": ["Brook, Dana ("],
            "topic": "Bracket Test",
            "lastDeliveryTime": "2026-10-01T09:00:00Z",
            "conversationId": "CONV_PAR002",
        }
        email = _email_from_raw(raw)
        assert email.sender == "Brook, Dana"

    def test_sender_name_from_dict(self):
        raw = {
            "from": {"name": "Brook, Dana", "email": "dbrook@example.com"},
            "subject": "Direct Email",
            "receivedDateTime": "2026-10-01T09:00:00Z",
            "id": "AAMk_SN001",
        }
        email = _email_from_raw(raw)
        assert email.sender == "dbrook@example.com"
        assert email.sender_name == "Brook, Dana"

    def test_sender_name_none_when_no_display_name(self):
        raw = {
            "from": {"email": "unknown@example.com"},
            "subject": "No Name",
            "receivedDateTime": "2026-10-01T09:00:00Z",
            "id": "AAMk_SN002",
        }
        email = _email_from_raw(raw)
        assert email.sender == "unknown@example.com"
        assert email.sender_name is None

    def test_mixed_senders_dn_filtered(self):
        raw = {
            "senders": [
                "/O=EXCHANGELABS/OU=GROUP/CN=RECIPIENTS/CN=hex001",
                "Park, David",
            ],
            "topic": "Mixed Senders",
            "lastDeliveryTime": "2026-10-01T09:00:00Z",
            "conversationId": "CONV_MIX001",
        }
        email = _email_from_raw(raw)
        assert email.sender == "Park, David"
        assert "/O=" not in email.text
        assert "Park, David" in email.text

    def test_clean_sender_preserves_name(self):
        raw = {
            "senders": ["Martinez, Elena"],
            "topic": "Normal",
            "lastDeliveryTime": "2026-10-01T09:00:00Z",
            "conversationId": "CONV_OK001",
        }
        email = _email_from_raw(raw)
        assert email.sender == "Martinez, Elena"
        assert email.sender_name == "Martinez, Elena"


# Anonymized live-shape payload (#658): same field layout as the live item,
# with ``sentDateTime`` and no ``toRecipients`` key at all.
LIVE_SHAPE_MESSAGE = {
    "id": "msg-0001",
    "subject": "The quick brown fox — café meeting",
    "from": {"name": "Jordan Example", "email": "jordan@example.invalid"},
    "sentDateTime": "2026-11-14T09:30:00Z",
}

# A message whose only recipient field would be ``toRecipients``.
TO_RECIPIENTS_MESSAGE = {
    "id": "msg-0002",
    "subject": "Jumps over the lazy dog",
    "from": {"name": "Casey Sample", "email": "casey@example.invalid"},
    "receivedDateTime": "2026-11-14T10:00:00Z",
    "bodyPreview": "How vexingly quick daft zebras jump.",
}

_FROZEN_NOW = 1_800_000_000.0
_EPOCH_STRINGS = ("1970-01-01", "1970-01-01T00:00:00Z")


def _without(raw: dict, *keys: str) -> dict:
    return {k: v for k, v in raw.items() if k not in keys}


def _ingest_inbox(items: list[dict], home) -> tuple[dict, list]:
    """Ingest ``items`` as an Outlook inbox page; return the result and stored rows."""
    bridge = _make_bridge({"email_inbox": json.dumps(items)})
    result = ingest_live(
        port=OutlookMcpAdapter(bridge),
        source="outlook_mcp_email",
        home=home,
        lookback_days=10000,
    )
    conn = connect(get_db_path(home))
    rows = conn.execute("SELECT text, timestamp, metadata FROM observations").fetchall()
    conn.close()
    return result, rows


class TestRecipientStates:
    def test_empty_to_recipients(self):
        email = _email_from_raw({**TO_RECIPIENTS_MESSAGE, "toRecipients": []})
        fact = get_fact(email.source_facts, "to")
        assert fact.state is SourceFactState.EMPTY
        assert fact.value == []
        assert "Recipients: none" in email.text
        assert "Recipients: unknown" not in email.text

    def test_absent_to_recipients(self):
        email = _email_from_raw(TO_RECIPIENTS_MESSAGE)
        assert get_fact(email.source_facts, "to") is None
        assert get_fact(email.source_facts, "recipients") is None
        assert "Recipients: unknown" in email.text
        assert "Recipients: none" not in email.text

    def test_null_to_recipients(self):
        email = _email_from_raw({**TO_RECIPIENTS_MESSAGE, "toRecipients": None})
        fact = get_fact(email.source_facts, "to")
        assert fact.state is SourceFactState.UNAVAILABLE
        assert fact.value is None
        assert "to" not in email.source_facts
        assert email.recipients == []
        assert "Recipients: unknown" in email.text
        assert "Recipients: none" not in email.text

    def test_present_to_recipients_text_unchanged(self):
        to = [{"name": "Owner, Jane", "email": "owner@example.invalid"}]
        email = _email_from_raw({**TO_RECIPIENTS_MESSAGE, "toRecipients": to})
        assert get_fact(email.source_facts, "to").state is SourceFactState.PRESENT
        assert email.source_facts["to"] == to
        assert email.text == (
            "[Subject: Jumps over the lazy dog] [Participants: casey@example.invalid]\n"
            "How vexingly quick daft zebras jump."
        )

    def test_live_recipients_field_states(self):
        raw = {
            "conversationId": "CONV-0003",
            "topic": "The quick brown fox",
            "senders": ["Example, Jordan"],
            "lastDeliveryTime": "2026-11-14T09:30:00Z",
            "preview": "Jumps over.",
        }
        empty = _email_from_raw({**raw, "recipients": []})
        assert get_fact(empty.source_facts, "recipients").state is SourceFactState.EMPTY
        assert "Recipients: none" in empty.text

        null = _email_from_raw({**raw, "recipients": None})
        assert get_fact(null.source_facts, "recipients").state is SourceFactState.UNAVAILABLE
        assert "Recipients: unknown" in null.text

        present = _email_from_raw({**raw, "recipients": ["Taylor, Morgan"]})
        assert present.source_facts["recipients"] == ["Taylor, Morgan"]
        assert "Recipients:" not in present.text

    def test_cc_recipients_states(self):
        empty = _email_from_raw({**TO_RECIPIENTS_MESSAGE, "ccRecipients": []})
        assert get_fact(empty.source_facts, "cc").state is SourceFactState.EMPTY
        null = _email_from_raw({**TO_RECIPIENTS_MESSAGE, "ccRecipients": None})
        assert get_fact(null.source_facts, "cc").state is SourceFactState.UNAVAILABLE
        assert get_fact(_email_from_raw(TO_RECIPIENTS_MESSAGE).source_facts, "cc") is None


class TestLiveShapeMessage:
    def test_adapter_stores_no_recipients_fact(self):
        bridge = _make_bridge({"email_inbox": json.dumps([LIVE_SHAPE_MESSAGE])})
        (email,) = OutlookMcpAdapter(bridge).list_inbox(since=0.0)
        assert get_fact(email.source_facts, "to") is None
        assert get_fact(email.source_facts, "recipients") is None
        assert "_state" not in email.source_facts
        assert email.source_facts["message_id"] == "msg-0001"
        assert email.source_facts["sent_raw"] == "2026-11-14T09:30:00Z"
        assert email.timestamp == datetime(2026, 11, 14, 9, 30, tzinfo=UTC).timestamp()
        assert "Recipients: unknown" in email.text
        assert "Recipients: none" not in email.text
        assert email.subject == "The quick brown fox — café meeting"

    def test_ingest_round_trip(self, tmp_path):
        result, rows = _ingest_inbox([LIVE_SHAPE_MESSAGE], tmp_path / "patina_home")
        assert result["messages_inserted"] == 1
        (row,) = rows
        source = json.loads(row["metadata"])["source"]
        assert "to" not in source
        assert "recipients" not in source
        assert "_state" not in source
        assert source["sent_raw"] == "2026-11-14T09:30:00Z"
        assert row["timestamp"] == datetime(2026, 11, 14, 9, 30, tzinfo=UTC).timestamp()
        assert row["text"].startswith(
            "[Subject: The quick brown fox — café meeting]"
            " [Participants: jordan@example.invalid] [Recipients: unknown]"
        )
        assert "Recipients: none" not in row["text"]

    def test_empty_to_recipients_variant(self, tmp_path):
        raw = {**LIVE_SHAPE_MESSAGE, "toRecipients": []}
        _, (row,) = _ingest_inbox([raw], tmp_path / "patina_home")
        fact = get_fact(json.loads(row["metadata"])["source"], "to")
        assert fact.state is SourceFactState.EMPTY
        assert fact.value == []
        assert "Recipients: none" in row["text"]

    def test_null_to_recipients_variant(self, tmp_path):
        raw = {**LIVE_SHAPE_MESSAGE, "toRecipients": None}
        _, (row,) = _ingest_inbox([raw], tmp_path / "patina_home")
        source = json.loads(row["metadata"])["source"]
        fact = get_fact(source, "to")
        assert fact.state is SourceFactState.UNAVAILABLE
        assert fact.value is None
        assert "to" not in source
        assert "Recipients: unknown" in row["text"]
        assert "Recipients: none" not in row["text"]


def _calendar_text(raw: dict) -> str:
    (msg,) = _events_to_chat_messages([_calendar_event_from_raw(raw)])
    return msg.text


class TestCalendarAttendeeStates:
    def test_empty_attendees(self):
        raw = {**LIVE_CALENDAR_VIEW_ITEM, "attendees": []}
        fact = get_fact(_calendar_event_from_raw(raw).source_facts, "attendees")
        assert fact.state is SourceFactState.EMPTY
        assert fact.value == []
        assert _calendar_text(raw).endswith(", Attendees: none")

    def test_absent_attendees(self):
        event = _calendar_event_from_raw(LIVE_CALENDAR_VIEW_ITEM)
        assert get_fact(event.source_facts, "attendees") is None
        assert "Attendees" not in _calendar_text(LIVE_CALENDAR_VIEW_ITEM)

    def test_null_attendees(self):
        raw = {**LIVE_CALENDAR_VIEW_ITEM, "attendees": None}
        event = _calendar_event_from_raw(raw)
        fact = get_fact(event.source_facts, "attendees")
        assert fact.state is SourceFactState.UNAVAILABLE
        assert fact.value is None
        assert "attendees" not in event.source_facts
        text = _calendar_text(raw)
        assert "Attendees: unknown" in text
        assert "Attendees: none" not in text

    def test_present_attendees_listed(self):
        raw = {**LIVE_CALENDAR_VIEW_ITEM, "attendees": ["Example, Jordan"]}
        fact = get_fact(_calendar_event_from_raw(raw).source_facts, "attendees")
        assert fact.state is SourceFactState.PRESENT
        assert _calendar_text(raw).endswith(", Attendees: Example, Jordan")


class TestMissingTimestamps:
    def test_message_without_sent_time(self, monkeypatch):
        monkeypatch.setattr("time.time", lambda: _FROZEN_NOW)
        email = _email_from_raw(_without(LIVE_SHAPE_MESSAGE, "sentDateTime"))
        assert email.timestamp is None
        assert get_fact(email.source_facts, "sent_raw") is None
        assert get_fact(email.source_facts, "received_raw") is None
        assert "[Sent: unknown]" in email.text
        for value in email.source_facts.values():
            assert value not in (_FROZEN_NOW, 0.0, *_EPOCH_STRINGS)
        assert "1970" not in email.text

    def test_message_without_sent_time_never_stored(self, tmp_path, monkeypatch):
        monkeypatch.setattr("time.time", lambda: _FROZEN_NOW)
        raw = _without(LIVE_SHAPE_MESSAGE, "sentDateTime")
        result, rows = _ingest_inbox([raw], tmp_path / "patina_home")
        assert result["messages_inserted"] == 0
        assert result["skip_reasons"] == {"missing_timestamp": 1}
        assert rows == []

    def test_null_sent_time_is_unavailable(self):
        email = _email_from_raw({**LIVE_SHAPE_MESSAGE, "sentDateTime": None})
        assert email.timestamp is None
        assert get_fact(email.source_facts, "sent_raw").state is SourceFactState.UNAVAILABLE
        assert "sent_raw" not in email.source_facts
        assert "[Sent: unknown]" in email.text

    def test_sent_time_present_renders_no_unknown(self):
        assert "Sent: unknown" not in _email_from_raw(LIVE_SHAPE_MESSAGE).text

    def test_calendar_event_without_start(self, monkeypatch):
        monkeypatch.setattr("time.time", lambda: _FROZEN_NOW)
        event = _calendar_event_from_raw(_without(LIVE_CALENDAR_VIEW_ITEM, "start"))
        assert event.start is None
        for value in event.source_facts.values():
            assert value not in (_FROZEN_NOW, 0.0, *_EPOCH_STRINGS)

        skip_reasons: dict[str, int] = {}
        assert _events_to_chat_messages([event], skip_reasons) == []
        assert skip_reasons == {"missing_timestamp": 1}

    def test_calendar_event_with_unparseable_start(self):
        event = _calendar_event_from_raw({**LIVE_CALENDAR_VIEW_ITEM, "start": "not-a-date"})
        assert event.start is None
