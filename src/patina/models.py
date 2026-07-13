from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Entity:
    id: str
    type: str
    name: str
    aliases: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    first_seen: str = ""
    last_seen: str = ""
    decay_rate: float = 0.02

    def __post_init__(self) -> None:
        if not self.first_seen:
            self.first_seen = _now_iso()
        if not self.last_seen:
            self.last_seen = _now_iso()


@dataclass
class Relationship:
    id: str
    subject_id: str
    predicate: str
    object_id: str
    confidence: float = 0.5
    first_seen: str = ""
    last_confirmed: str = ""
    source_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.first_seen:
            self.first_seen = _now_iso()
        if not self.last_confirmed:
            self.last_confirmed = _now_iso()


@dataclass
class Claim:
    id: str
    subject_id: str
    predicate: str
    object: str
    confidence: float = 0.5
    first_asserted: str = ""
    last_confirmed: str = ""
    decay_rate: float = 0.02
    source_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.first_asserted:
            self.first_asserted = _now_iso()
        if not self.last_confirmed:
            self.last_confirmed = _now_iso()


@dataclass
class Observation:
    id: str
    source: str
    channel_id: str | None
    thread_id: str | None
    timestamp: float
    sender_entity_id: str | None
    text: str | None
    metadata: dict = field(default_factory=dict)
    ingested_at: str = ""
    processed: int = 0

    def __post_init__(self) -> None:
        if not self.ingested_at:
            self.ingested_at = _now_iso()


@dataclass
class ChatMessage:
    user_id: str
    text: str
    timestamp: float
    channel_id: str
    thread_id: str | None = None
    user_name: str | None = None
    channel_name: str | None = None
    reactions: list[dict] = field(default_factory=list)
    is_bot: bool = False


@dataclass
class DmChannel:
    channel_id: str
    is_group: bool = False
    last_activity_ts: float = 0.0


@dataclass
class EmailMessage:
    id: str
    sender: str
    subject: str
    text: str
    timestamp: float
    recipients: list[str] = field(default_factory=list)
    conversation_id: str | None = None


@dataclass
class CalendarEvent:
    id: str
    subject: str
    start: float
    end: float
    attendees: list[str] = field(default_factory=list)
    organizer: str = ""
