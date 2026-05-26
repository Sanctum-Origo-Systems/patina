from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from patina.models import CalendarEvent


@runtime_checkable
class CalendarPort(Protocol):
    @property
    def platform(self) -> str: ...

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]: ...
