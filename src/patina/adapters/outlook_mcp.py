from __future__ import annotations

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
            result = self._bridge.call_tool("email_inbox")
        except Exception:
            return []
        try:
            raw = parse_outlook_content(result)
        except McpClientError:
            return []
        if not isinstance(raw, list):
            raw = [raw] if isinstance(raw, dict) else []
        emails = [_email_from_raw(item) for item in raw if isinstance(item, dict)]
        return [e for e in emails if e.timestamp >= since]

    def search_sent(self, query: str) -> list[EmailMessage]:
        try:
            result = self._bridge.call_tool(
                "email_search", {"query": query, "folder": "Sent Items"}
            )
        except Exception:
            return []
        try:
            raw = parse_outlook_content(result)
        except McpClientError:
            return []
        if not isinstance(raw, list):
            raw = [raw] if isinstance(raw, dict) else []
        return [_email_from_raw(item) for item in raw if isinstance(item, dict)]

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


def _parse_outlook_datetime(dt_str: str) -> float:
    dt_str = dt_str.strip()
    try:
        return datetime.fromisoformat(dt_str).timestamp()
    except ValueError:
        return 0.0


def _email_from_raw(raw: dict) -> EmailMessage:
    from_raw = raw.get("from", {})
    if isinstance(from_raw, dict):
        sender = from_raw.get("email", from_raw.get("name", ""))
    else:
        sender = str(from_raw)

    recipients = []
    for r in raw.get("toRecipients", []):
        if isinstance(r, dict):
            recipients.append(r.get("email", r.get("name", "")))

    received = raw.get("receivedDateTime", "")
    timestamp = _parse_outlook_datetime(received) if received else 0.0

    return EmailMessage(
        id=raw.get("id", ""),
        sender=sender,
        subject=raw.get("subject", ""),
        text=raw.get("bodyPreview", raw.get("body", "")),
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
