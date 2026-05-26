from __future__ import annotations

from typing import Protocol, runtime_checkable

from patina.models import ChatMessage


@runtime_checkable
class ChatPort(Protocol):
    @property
    def platform(self) -> str: ...

    def list_dm_messages(self, since: float) -> list[ChatMessage]: ...

    def list_mentions(self, since: float) -> list[ChatMessage]: ...

    def list_channel_messages(self, channel_id: str, since: float) -> list[ChatMessage]: ...

    def get_thread(self, channel_id: str, thread_id: str) -> list[ChatMessage]: ...
