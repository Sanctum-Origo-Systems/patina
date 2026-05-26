from __future__ import annotations

from typing import Protocol, runtime_checkable

from patina.models import EmailMessage


@runtime_checkable
class EmailPort(Protocol):
    @property
    def platform(self) -> str: ...

    def list_inbox(self, since: float) -> list[EmailMessage]: ...

    def search_sent(self, query: str) -> list[EmailMessage]: ...
