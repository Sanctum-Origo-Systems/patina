"""Find and remove ``outlook_mcp_email`` observations that are meeting messages.

Selection is decided solely by ``_is_meeting_message`` from the Outlook adapter.
Its input per row comes from stored class fields in metadata, else a read-only
re-fetch of the source payload, else the row is undetermined and never removed.
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


def _source_id(meta: dict) -> str | None:
    sid = meta.get("conversationId", meta.get("id"))
    return sid if isinstance(sid, str) and sid else None


def _matching_classes(payload: dict) -> list[str]:
    item_classes = payload.get("itemClasses")
    if isinstance(item_classes, list) and item_classes:
        return [c for c in item_classes if isinstance(c, str)]
    msg_class = payload.get("messageClass", payload.get("message_class", ""))
    return [msg_class] if isinstance(msg_class, str) and msg_class else []


def classification_input(metadata: dict, adapter: RawMessageFetcher | None) -> dict | None:
    """Build the dict passed to ``_is_meeting_message``, or None when undetermined."""
    if _has_class_field(metadata):
        return metadata
    sid = _source_id(metadata)
    if sid is None or adapter is None:
        return None
    raw = adapter.get_raw_message(sid)
    if not isinstance(raw, dict) or not _has_class_field(raw):
        return None
    return raw


def classify(metadata: dict, adapter: RawMessageFetcher | None) -> tuple[str, list[str]]:
    payload = classification_input(metadata, adapter)
    if payload is None:
        return UNDETERMINED, []
    if outlook_mcp._is_meeting_message(payload):
        return SELECTED, _matching_classes(payload)
    return NOT_MEETING, []


def _load_metadata(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        meta = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return meta if isinstance(meta, dict) else {}


def _citation_counts(conn: sqlite3.Connection, obs_ids: set[str]) -> dict[str, int]:
    counts = dict.fromkeys(obs_ids, 0)
    if not obs_ids:
        return counts
    for row in conn.execute(
        "SELECT source_ids FROM claims WHERE source_ids IS NOT NULL"
    ).fetchall():
        sids = json.loads(row["source_ids"])
        for sid in set(sids):
            if sid in counts:
                counts[sid] += 1
    return counts


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
            "SELECT id, timestamp, metadata, processed FROM observations"
            " WHERE source = ? ORDER BY timestamp, id",
            (SOURCE,),
        ).fetchall()

        picked: list[tuple[sqlite3.Row, list[str]]] = []
        undetermined = UndeterminedBucket()
        not_meeting = 0
        for row in rows:
            verdict, classes = classify(_load_metadata(row["metadata"]), adapter)
            if verdict == SELECTED:
                picked.append((row, classes))
            elif verdict == UNDETERMINED:
                ts = row["timestamp"]
                undetermined.count += 1
                undetermined.observation_ids.append(row["id"])
                undetermined.earliest = (
                    ts if undetermined.earliest is None else min(undetermined.earliest, ts)
                )
                undetermined.latest = (
                    ts if undetermined.latest is None else max(undetermined.latest, ts)
                )
            else:
                not_meeting += 1

        citations = _citation_counts(conn, {r["id"] for r, _ in picked})
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

        current = _citation_counts(conn, set(ids))
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
