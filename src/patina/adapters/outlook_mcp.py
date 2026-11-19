from __future__ import annotations

import re
from datetime import datetime

from patina.adapters._mcp_client import (
    McpClientError,
    McpSyncBridge,
    parse_outlook_content,
)
from patina.adapters._source_facts import get_fact, put_fact
from patina.models import CalendarEvent, EmailMessage, SourceFactState


class OutlookMcpAdapter:
    def __init__(self, bridge: McpSyncBridge) -> None:
        self._bridge = bridge
        self._raw_inbox: dict[str, dict] | None = None

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
        # Undated emails pass through so ingest can count them as skipped.
        return [e for e in emails if e.timestamp is None or e.timestamp >= since]

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

    def get_raw_message(self, source_id: str) -> dict | None:
        """Return the raw inbox payload whose ``conversationId``/``id`` matches, or None.

        Read-only: lists the inbox once per adapter instance (no meeting filter)
        and looks the ID up in that listing.
        """
        if self._raw_inbox is None:
            self._raw_inbox = {}
            try:
                result = self._bridge.call_tool(
                    "email_inbox", {"limit": _REFETCH_LIMIT, "unreadOnly": False}
                )
                raw = parse_outlook_content(result)
            except Exception:
                return None
            for item in _unwrap_email_list(raw):
                if not isinstance(item, dict):
                    continue
                item_id = item.get("conversationId", item.get("id"))
                if item_id:
                    self._raw_inbox.setdefault(item_id, item)
        return self._raw_inbox.get(source_id)


_REFETCH_LIMIT = 500

_MEETING_CLASS_PREFIX = "IPM.Schedule.Meeting."


def _is_meeting_message(raw: dict) -> bool:
    """Return True when the item is a meeting request, response or cancellation.

    Live ``email_inbox`` conversations carry ``itemClasses``, a list of the
    message classes in the thread. A conversation counts as a meeting only when
    *every* entry starts with ``IPM.Schedule.Meeting.``; any other entry (such as
    ``IPM.Note``) means a real email is in the thread, so it is kept. A missing,
    empty or non-list ``itemClasses`` falls back to the single-message
    ``messageClass`` / ``message_class`` field.
    """
    item_classes = raw.get("itemClasses")
    if isinstance(item_classes, list) and item_classes:
        return all(isinstance(c, str) and c.startswith(_MEETING_CLASS_PREFIX) for c in item_classes)
    msg_class = raw.get("messageClass", raw.get("message_class", ""))
    return isinstance(msg_class, str) and msg_class.startswith(_MEETING_CLASS_PREFIX)


def _parse_outlook_datetime(dt_str: str) -> float:
    dt_str = dt_str.strip()
    try:
        return datetime.fromisoformat(dt_str).timestamp()
    except ValueError:
        return 0.0


def _parse_optional_datetime(dt_str) -> float | None:
    """Parse a source time string; ``None`` when absent or unparseable, never 0.0 or now."""
    if not isinstance(dt_str, str) or not dt_str.strip():
        return None
    return _parse_outlook_datetime(dt_str) or None


def _put_payload_fact(facts: dict, raw: dict, payload_key: str, fact_key: str) -> None:
    """Record ``raw[payload_key]`` under ``fact_key`` with its fact state.

    ``[]``/``""`` is ``empty``, ``null`` is ``unavailable`` and a missing key
    stores nothing.
    """
    put_fact(facts, fact_key, raw.get(payload_key), present=payload_key in raw)


def _unknown_or_none(facts: dict, key: str | None) -> str | None:
    """``"none"`` for a fact sent empty, ``"unknown"`` for one sent ``null`` or
    left out, ``None`` when the source sent a value.
    """
    fact = get_fact(facts, key) if key else None
    if fact is None or fact.state is SourceFactState.UNAVAILABLE:
        return "unknown"
    if fact.state is SourceFactState.EMPTY:
        return "none"
    return None


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


_LEGACY_DN_RE = re.compile(r"^/[Oo]=")
_PAREN_SUFFIX_RE = re.compile(r"\s*\(.*$")


def normalize_sender(sender: str) -> str:
    if not sender:
        return sender
    if _LEGACY_DN_RE.match(sender):
        return ""
    return _PAREN_SUFFIX_RE.sub("", sender).strip()


def _message_id(raw: dict) -> str | None:
    """The item's source id: ``id``, else the first ``itemIds`` entry, else ``conversationId``.

    Live ``email_inbox`` conversations send no ``id``, only an ``itemIds`` list,
    so stored source facts would otherwise never carry an id.
    """
    if raw.get("id"):
        return raw["id"]
    item_ids = raw.get("itemIds")
    if isinstance(item_ids, list):
        for item_id in item_ids:
            if isinstance(item_id, str) and item_id:
                return item_id
    return raw.get("conversationId") or None


def _email_from_raw(raw: dict) -> EmailMessage:
    senders = raw.get("senders", [])
    sender_dn = None
    for s in senders:
        if s and _LEGACY_DN_RE.match(s):
            sender_dn = s
            break
    clean_senders = [s for s in (normalize_sender(s) for s in senders) if s]
    sender = clean_senders[0] if clean_senders else ""
    sender_name = sender if sender else None
    sender_key = next((s for s in senders if normalize_sender(s)), None)

    if not sender:
        from_raw = raw.get("from", {})
        if isinstance(from_raw, dict):
            sender = from_raw.get("email", from_raw.get("name", ""))
            raw_name = from_raw.get("name", "")
            if raw_name:
                normalized = normalize_sender(raw_name)
                sender_name = normalized if normalized else None
        elif from_raw:
            sender = str(from_raw)
        sender_key = sender or next((s for s in senders if s), None)

    # Live ``email_inbox`` items send ``recipients``; others send ``toRecipients``.
    if "recipients" in raw:
        recipients_key = "recipients"
    elif "toRecipients" in raw:
        recipients_key = "to"
    else:
        recipients_key = None
    raw_recipients = raw.get("recipients", raw.get("toRecipients"))
    recipients = []
    for r in raw_recipients if isinstance(raw_recipients, list) else []:
        if isinstance(r, dict):
            recipients.append(r.get("email", r.get("name", "")))
        elif isinstance(r, str):
            recipients.append(r)

    received = raw.get("lastDeliveryTime", raw.get("receivedDateTime", ""))
    # No usable received (else sent) time -> None, never 0.0 or the ingest
    # time; ingest skips these under the ``missing_timestamp`` reason.
    timestamp = _parse_optional_datetime(received) or _parse_optional_datetime(
        raw.get("sentDateTime")
    )

    item_class = raw.get("itemClasses", raw.get("messageClass", raw.get("message_class")))
    source_facts: dict = {}
    put_fact(source_facts, "message_id", _message_id(raw))
    put_fact(source_facts, "item_class", item_class)
    put_fact(source_facts, "sender_key", sender_key)
    _put_payload_fact(source_facts, raw, "toRecipients", "to")
    _put_payload_fact(source_facts, raw, "ccRecipients", "cc")
    # Live ``email_inbox`` items send only ``recipients``: display-name strings
    # with no To/Cc split and no distribution-list flag. Kept as given.
    _put_payload_fact(source_facts, raw, "recipients", "recipients")
    put_fact(source_facts, "received_raw", received)
    _put_payload_fact(source_facts, raw, "sentDateTime", "sent_raw")

    subject = raw.get("topic", raw.get("subject", ""))
    preview = raw.get("preview", raw.get("bodyPreview", raw.get("body", "")))
    preview = _strip_caution_banner(preview)
    participants_text = ", ".join(clean_senders) if clean_senders else sender
    header = f"[Subject: {subject}] [Participants: {participants_text}]"
    # Recipients the source sent are not repeated here; only "none" (sent
    # empty) or "unknown" (sent null or left out) is spelled out.
    recipients_text = _unknown_or_none(source_facts, recipients_key)
    if recipients_text:
        header += f" [Recipients: {recipients_text}]"
    if timestamp is None:
        header += " [Sent: unknown]"
    text = f"{header}\n{preview}"

    return EmailMessage(
        id=raw.get("conversationId", raw.get("id", "")),
        sender=sender,
        subject=subject,
        text=text,
        timestamp=timestamp,
        recipients=recipients,
        conversation_id=raw.get("conversationId"),
        sender_name=sender_name,
        sender_dn=sender_dn,
        source_facts=source_facts,
        thread_participants=[s for s in senders if isinstance(s, str) and s],
    )


def _calendar_event_from_raw(raw: dict) -> CalendarEvent:
    """Map one ``calendar_view`` item to a ``CalendarEvent``.

    Live ``calendar_view`` items carry ``meetingId``, ``subject``, ``start``,
    ``end`` and ``organizer`` only: no attendee field. Every live calendar row
    to date (#651) was stored with no ``attendees`` source fact, so attendees
    are unavailable from this tool and ``attendees`` stays empty. When an item
    does carry ``attendees``, each entry is read as a dict (``email``, else
    ``name``) or a display-name string such as ``"Example, Jordan"``. An
    ``attendees`` sent as ``[]`` is stored ``empty`` and one sent ``null``
    ``unavailable``. A missing or unparseable ``start``/``end`` is ``None``,
    never the epoch.
    """
    organizer_raw = raw.get("organizer", {})
    if isinstance(organizer_raw, dict):
        organizer = organizer_raw.get("email", organizer_raw.get("name", ""))
    else:
        organizer = str(organizer_raw)

    start = _parse_optional_datetime(raw.get("start"))
    end = _parse_optional_datetime(raw.get("end"))

    attendees = []
    raw_attendees = raw.get("attendees")
    for att in raw_attendees if isinstance(raw_attendees, list) else []:
        if isinstance(att, dict):
            att = att.get("email") or att.get("name") or ""
        if isinstance(att, str) and att.strip():
            attendees.append(att.strip())

    source_facts: dict = {}
    put_fact(source_facts, "message_id", raw.get("meetingId", raw.get("id")))
    put_fact(source_facts, "sender_key", organizer)
    _put_payload_fact(source_facts, raw, "attendees", "attendees")

    return CalendarEvent(
        id=raw.get("meetingId", ""),
        subject=raw.get("subject", ""),
        start=start,
        end=end,
        attendees=attendees,
        organizer=organizer,
        organizer_dn=organizer if organizer else None,
        source_facts=source_facts,
    )
