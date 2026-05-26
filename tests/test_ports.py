from __future__ import annotations

from patina.models import CalendarEvent, ChatMessage, EmailMessage
from patina.ports.calendar import CalendarPort
from patina.ports.chat import ChatPort
from patina.ports.email import EmailPort


class MockChat:
    @property
    def platform(self) -> str:
        return "mock"

    def list_dm_messages(self, since: float) -> list[ChatMessage]:
        return []

    def list_mentions(self, since: float) -> list[ChatMessage]:
        return []

    def list_channel_messages(self, channel_id: str, since: float) -> list[ChatMessage]:
        return []

    def get_thread(self, channel_id: str, thread_id: str) -> list[ChatMessage]:
        return []


class MockEmail:
    @property
    def platform(self) -> str:
        return "mock"

    def list_inbox(self, since: float) -> list[EmailMessage]:
        return []

    def search_sent(self, query: str) -> list[EmailMessage]:
        return []


class MockCalendar:
    @property
    def platform(self) -> str:
        return "mock"

    def list_events(self, start, end) -> list[CalendarEvent]:
        return []


def test_chat_port_runtime_checkable():
    assert isinstance(MockChat(), ChatPort)


def test_email_port_runtime_checkable():
    assert isinstance(MockEmail(), EmailPort)


def test_calendar_port_runtime_checkable():
    assert isinstance(MockCalendar(), CalendarPort)
