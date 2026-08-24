from __future__ import annotations

import re
from datetime import datetime

from patina.adapters._mcp_client import (
    McpClientError,
    McpSyncBridge,
    parse_outlook_content,
)
from patina.models import CalendarEvent, EmailMessage


class OutlookMcpAdapter:
    def __init__(self, bridge: McpSyncBridge) -> None:
        self._bridge = bridge

    @property
    def platform(self) -> str:
        return "outlook_mcp"

    def close(self) -> None:
        self._bridge.close()

    def list_inbox(self, since: float) -> list[EmailMessage]:
        try:
            result = self._bridge.call_tool("email_inbox", {"limit": 50, "unreadOnly": False})
        except Exception:
            return []
        try:
            raw = parse_outlook_content(result)
        except McpClientError:
            return []

        email_list = _unwrap_email_list(raw)
        emails = [
            _email_from_raw(item)
            for item in email_list
            if isinstance(item, dict) and not _is_meeting_message(item)
        ]
        return [e for e in emails if e.timestamp >= since]

    def search_sent(self, query: str) -> list[EmailMessage]:
        try:
            result = self._bridge.call_tool("email_search", {"query": query, "folder": "sentitems"})
        except Exception:
            return []
        try:
            raw = parse_outlook_content(result)
        except McpClientError:
            return []

        email_list = _unwrap_email_list(raw)
        return [_email_from_raw(item) for item in email_list if isinstance(item, dict)]

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        start_str = start.strftime("%m-%d-%Y")
        end_str = end.strftime("%m-%d-%Y")
        try:
            result = self._bridge.call_tool(
                "calendar_view", {"start_date": start_str, "end_date": end_str, "view": "day"}
            )
        except Exception:
            return []
        try:
            raw = parse_outlook_content(result)
        except McpClientError:
            return []
        if not isinstance(raw, list):
            raw = [raw] if isinstance(raw, dict) else []
        return [_calendar_event_from_raw(item) for item in raw if isinstance(item, dict)]


_MEETING_CLASS_PREFIX = "IPM.Schedule.Meeting."


def _is_meeting_message(raw: dict) -> bool:
    msg_class = raw.get("messageClass", raw.get("message_class", ""))
    return isinstance(msg_class, str) and msg_class.startswith(_MEETING_CLASS_PREFIX)


def _parse_outlook_datetime(dt_str: str) -> float:
    dt_str = dt_str.strip()
    try:
        return datetime.fromisoformat(dt_str).timestamp()
    except ValueError:
        return 0.0


def _unwrap_email_list(raw) -> list:
    if isinstance(raw, dict):
        content = raw.get("content", raw)
        return content.get("emails", content.get("results", []))
    if isinstance(raw, list):
        return raw
    return []


_CAUTION_BANNER_RE = re.compile(
    r"CAUTION:.*?(?:confirm the sender and know the content is safe\.?\s*|"
    r"organization\.? *Do not click links or open attachments "
    r"unless you (?:recognize|can confirm) the sender"
    r" and know the content is safe\.?\s*|"
    r"organization\.?\s*)",
    re.DOTALL | re.IGNORECASE,
)


def _strip_caution_banner(text: str) -> str:
    return _CAUTION_BANNER_RE.sub("", text).strip()


def _email_from_raw(raw: dict) -> EmailMessage:
    senders = raw.get("senders", [])
    sender = senders[0] if senders else ""

    if not sender:
        from_raw = raw.get("from", {})
        if isinstance(from_raw, dict):
            sender = from_raw.get("email", from_raw.get("name", ""))
        elif from_raw:
            sender = str(from_raw)

    recipients = []
    for r in raw.get("recipients", raw.get("toRecipients", [])):
        if isinstance(r, dict):
            recipients.append(r.get("email", r.get("name", "")))
        elif isinstance(r, str):
            recipients.append(r)

    received = raw.get("lastDeliveryTime", raw.get("receivedDateTime", ""))
    timestamp = _parse_outlook_datetime(received) if received else 0.0

    subject = raw.get("topic", raw.get("subject", ""))
    preview = raw.get("preview", raw.get("bodyPreview", raw.get("body", "")))
    preview = _strip_caution_banner(preview)
    participants_text = ", ".join(senders) if senders else sender
    text = f"[Subject: {subject}] [Participants: {participants_text}]\n{preview}"

    return EmailMessage(
        id=raw.get("conversationId", raw.get("id", "")),
        sender=sender,
        subject=subject,
        text=text,
        timestamp=timestamp,
        recipients=recipients,
        conversation_id=raw.get("conversationId"),
    )


def _calendar_event_from_raw(raw: dict) -> CalendarEvent:
    organizer_raw = raw.get("organizer", {})
    if isinstance(organizer_raw, dict):
        organizer = organizer_raw.get("email", organizer_raw.get("name", ""))
    else:
        organizer = str(organizer_raw)

    start = _parse_outlook_datetime(raw.get("start", ""))
    end = _parse_outlook_datetime(raw.get("end", ""))

    attendees = []
    for att in raw.get("attendees", []):
        if isinstance(att, dict):
            attendees.append(att.get("email", ""))

    return CalendarEvent(
        id=raw.get("meetingId", ""),
        subject=raw.get("subject", ""),
        start=start,
        end=end,
        attendees=attendees,
        organizer=organizer,
    )
