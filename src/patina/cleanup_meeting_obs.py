"""Find and remove ``outlook_mcp_email`` observations that are meeting messages.

Selection is decided solely by ``_is_meeting_message`` from the Outlook adapter.
Its input per row comes from stored class fields in metadata, else a read-only
re-fetch of the source payload, else the row is undetermined and never removed.
The re-fetch ID is ``conversationId``/``id`` in metadata, else ``thread_id``,
else ``channel_id`` without its ``email:`` prefix (where ingest stores it).
A claim or relationship cites a row only when its ``source_ids`` hold that
row's observation id; rows citing no existing observation are reported as
unknown provenance, never matched by text or time.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from patina.adapters import outlook_mcp
from patina.maintenance import backup_store
from patina.store import connect, connect_readonly, delete_observations

SOURCE = "outlook_mcp_email"

SELECTED = "selected"
UNDETERMINED = "undetermined"
NOT_MEETING = "not_meeting"

_CLASS_KEYS = ("itemClasses", "messageClass", "message_class")
_CHANNEL_PREFIX = "email:"

# Why a row is undetermined.
NO_SOURCE_ID = "no_source_id"
NOT_IN_CURRENT_INBOX = "not_in_current_inbox"
NO_CLASS_FIELDS = "no_class_fields"
REFETCH_UNAVAILABLE = "refetch_unavailable"
UNDETERMINED_REASONS = (NO_SOURCE_ID, NOT_IN_CURRENT_INBOX, NO_CLASS_FIELDS, REFETCH_UNAVAILABLE)


class RawMessageFetcher(Protocol):
    def get_raw_message(self, source_id: str) -> dict | None: ...


@dataclass
class SelectedRow:
    observation_id: str
    timestamp: float
    item_classes: list[str]
    processed: bool
    citing_claims: int


@dataclass
class UndeterminedBucket:
    count: int = 0
    earliest: float | None = None
    latest: float | None = None
    observation_ids: list[str] = field(default_factory=list)
    reasons: dict[str, int] = field(default_factory=lambda: dict.fromkeys(UNDETERMINED_REASONS, 0))
    # Rows dated 0 (1970-01-01) are counted here and kept out of earliest/latest.
    zero_timestamp: int = 0


@dataclass
class Selection:
    selected: list[SelectedRow]
    total_citations: int
    earliest: float | None
    latest: float | None
    processed_count: int
    unprocessed_count: int
    undetermined: UndeterminedBucket
    not_meeting_count: int
    # Claims and relationships whose source_ids name no existing observation.
    unknown_provenance: int = 0

    @property
    def selected_count(self) -> int:
        return len(self.selected)


@dataclass
class RemovalResult:
    backup_path: Path | None
    deleted: int
    before_count: int
    after_count: int


class RemovalRefused(Exception):
    """Raised when selected rows are still cited by claims; nothing is changed."""

    def __init__(self, rows: list[SelectedRow]) -> None:
        self.rows = rows
        ids = ", ".join(r.observation_id for r in rows)
        super().__init__(f"{len(rows)} selected observation(s) have citing claims: {ids}")


def _has_class_field(payload: dict) -> bool:
    return any(k in payload for k in _CLASS_KEYS)


def _source_id(
    meta: dict, thread_id: str | None = None, channel_id: str | None = None
) -> str | None:
    sid = meta.get("conversationId", meta.get("id"))
    if isinstance(sid, str) and sid:
        return sid
    if isinstance(thread_id, str) and thread_id:
        return thread_id
    if isinstance(channel_id, str) and channel_id.startswith(_CHANNEL_PREFIX):
        return channel_id.removeprefix(_CHANNEL_PREFIX) or None
    return None


def _matching_classes(payload: dict) -> list[str]:
    item_classes = payload.get("itemClasses")
    if isinstance(item_classes, list) and item_classes:
        return [c for c in item_classes if isinstance(c, str)]
    msg_class = payload.get("messageClass", payload.get("message_class", ""))
    return [msg_class] if isinstance(msg_class, str) and msg_class else []


def _resolve_input(
    metadata: dict,
    adapter: RawMessageFetcher | None,
    thread_id: str | None,
    channel_id: str | None,
) -> tuple[dict | None, str | None]:
    """Return ``(payload, None)``, or ``(None, reason)`` when undetermined."""
    if _has_class_field(metadata):
        return metadata, None
    sid = _source_id(metadata, thread_id, channel_id)
    if sid is None:
        return None, NO_SOURCE_ID
    if adapter is None:
        return None, REFETCH_UNAVAILABLE
    raw = adapter.get_raw_message(sid)
    if not isinstance(raw, dict):
        return None, NOT_IN_CURRENT_INBOX
    if not _has_class_field(raw):
        return None, NO_CLASS_FIELDS
    return raw, None


def classification_input(
    metadata: dict,
    adapter: RawMessageFetcher | None,
    thread_id: str | None = None,
    channel_id: str | None = None,
) -> dict | None:
    """Build the dict passed to ``_is_meeting_message``, or None when undetermined."""
    return _resolve_input(metadata, adapter, thread_id, channel_id)[0]


def _classify_with_reason(
    metadata: dict,
    adapter: RawMessageFetcher | None,
    thread_id: str | None = None,
    channel_id: str | None = None,
) -> tuple[str, list[str], str | None]:
    payload, reason = _resolve_input(metadata, adapter, thread_id, channel_id)
    if payload is None:
        return UNDETERMINED, [], reason
    if outlook_mcp._is_meeting_message(payload):
        return SELECTED, _matching_classes(payload), None
    return NOT_MEETING, [], None


def classify(
    metadata: dict,
    adapter: RawMessageFetcher | None,
    thread_id: str | None = None,
    channel_id: str | None = None,
) -> tuple[str, list[str]]:
    verdict, classes, _ = _classify_with_reason(metadata, adapter, thread_id, channel_id)
    return verdict, classes


def _load_metadata(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        meta = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return meta if isinstance(meta, dict) else {}


def _load_source_ids(raw: str | None) -> set[str]:
    if not raw:
        return set()
    try:
        sids = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    return {s for s in sids if isinstance(s, str)} if isinstance(sids, list) else set()


def _citation_counts(conn: sqlite3.Connection, obs_ids: set[str]) -> tuple[dict[str, int], int]:
    """Return ``(citing rows per selected id, unknown-provenance row count)``.

    Claims and relationships are both counted. Only source ids that name an
    existing observation are citations; method labels such as ``"extraction"``
    are not. A row with no such id has unknown provenance.
    """
    counts = dict.fromkeys(obs_ids, 0)
    known = {r["id"] for r in conn.execute("SELECT id FROM observations").fetchall()}
    unknown = 0
    for table in ("claims", "relationships"):
        for row in conn.execute(f"SELECT source_ids FROM {table}").fetchall():
            real = _load_source_ids(row["source_ids"]) & known
            if not real:
                unknown += 1
            for sid in real:
                if sid in counts:
                    counts[sid] += 1
    return counts, unknown


def _count_source_rows(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS c FROM observations WHERE source = ?", (SOURCE,)
    ).fetchone()["c"]


def select_meeting_observations(
    db_path: Path, adapter: RawMessageFetcher | None = None
) -> Selection:
    """Classify every ``outlook_mcp_email`` observation; the store is opened read-only."""
    conn = connect_readonly(db_path)
    try:
        rows = conn.execute(
            "SELECT id, timestamp, metadata, processed, thread_id, channel_id FROM observations"
            " WHERE source = ? ORDER BY timestamp, id",
            (SOURCE,),
        ).fetchall()

        picked: list[tuple[sqlite3.Row, list[str]]] = []
        undetermined = UndeterminedBucket()
        not_meeting = 0
        for row in rows:
            verdict, classes, reason = _classify_with_reason(
                _load_metadata(row["metadata"]), adapter, row["thread_id"], row["channel_id"]
            )
            if verdict == SELECTED:
                picked.append((row, classes))
            elif verdict == UNDETERMINED:
                ts = row["timestamp"]
                undetermined.count += 1
                undetermined.observation_ids.append(row["id"])
                undetermined.reasons[reason] += 1
                if not ts:
                    undetermined.zero_timestamp += 1
                    continue
                undetermined.earliest = (
                    ts if undetermined.earliest is None else min(undetermined.earliest, ts)
                )
                undetermined.latest = (
                    ts if undetermined.latest is None else max(undetermined.latest, ts)
                )
            else:
                not_meeting += 1

        citations, unknown_provenance = _citation_counts(conn, {r["id"] for r, _ in picked})
    finally:
        conn.close()

    selected = [
        SelectedRow(
            observation_id=r["id"],
            timestamp=r["timestamp"],
            item_classes=classes,
            processed=bool(r["processed"]),
            citing_claims=citations[r["id"]],
        )
        for r, classes in picked
    ]
    timestamps = [s.timestamp for s in selected]
    processed = sum(1 for s in selected if s.processed)
    return Selection(
        selected=selected,
        total_citations=sum(s.citing_claims for s in selected),
        earliest=min(timestamps) if timestamps else None,
        latest=max(timestamps) if timestamps else None,
        processed_count=processed,
        unprocessed_count=len(selected) - processed,
        undetermined=undetermined,
        not_meeting_count=not_meeting,
        unknown_provenance=unknown_provenance,
    )


def remove_meeting_observations(db_path: Path, selection: Selection) -> RemovalResult:
    """Back up the store, then delete only the selected rows.

    Raises ``RemovalRefused`` without touching the store when any selected row is
    cited by a claim, either in the selection or in the store as it is now.
    """
    cited = [s for s in selection.selected if s.citing_claims > 0]
    if cited:
        raise RemovalRefused(cited)

    ids = [s.observation_id for s in selection.selected]
    conn = connect(db_path)
    try:
        before = _count_source_rows(conn)
        if not ids:
            return RemovalResult(
                backup_path=None, deleted=0, before_count=before, after_count=before
            )

        current, _ = _citation_counts(conn, set(ids))
        cited_now = [s for s in selection.selected if current[s.observation_id] > 0]
        if cited_now:
            raise RemovalRefused(cited_now)

        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        backup_path = backup_store(db_path)

        placeholders = ",".join("?" for _ in ids)
        source_ids = [
            r["id"]
            for r in conn.execute(
                f"SELECT id FROM observations WHERE source = ? AND id IN ({placeholders})",
                [SOURCE, *ids],
            ).fetchall()
        ]
        try:
            deleted = delete_observations(conn, source_ids)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        after = _count_source_rows(conn)
    finally:
        conn.close()

    return RemovalResult(
        backup_path=backup_path, deleted=deleted, before_count=before, after_count=after
    )
