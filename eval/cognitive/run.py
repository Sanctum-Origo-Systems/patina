"""Cognitive eval: collect metrics and write a snapshot to latest.json.

Run: python eval/cognitive/run.py
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from eval.cognitive import EvalSnapshot, MetricValue

_DEFAULT_STORE = Path.home() / ".patina" / "store.db"


def collect_merge_rate(store_path: Path | str | None = None) -> MetricValue:
    now = datetime.now(UTC).isoformat()
    try:
        path = Path(store_path) if store_path is not None else _DEFAULT_STORE
        if not path.is_file():
            return MetricValue(value=0.0, collected_at=now)
        conn = sqlite3.connect(str(path))
        try:
            if not conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='pull_requests'"
            ).fetchone():
                return MetricValue(value=0.0, collected_at=now)
            total = conn.execute("SELECT COUNT(*) FROM pull_requests").fetchone()[0]
            if total == 0:
                return MetricValue(value=0.0, collected_at=now)
            merged_clean = conn.execute(
                "SELECT COUNT(*) FROM pull_requests WHERE merged = 1 AND rework = 0"
            ).fetchone()[0]
            return MetricValue(value=merged_clean / total, collected_at=now)
        finally:
            conn.close()
    except Exception:
        return MetricValue(value=0.0, collected_at=now)


def collect_time_to_implement(store_path: Path | str | None = None) -> MetricValue:
    now = datetime.now(UTC).isoformat()
    try:
        path = Path(store_path) if store_path is not None else _DEFAULT_STORE
        if not path.is_file():
            return MetricValue(value=0.0, collected_at=now)
        conn = sqlite3.connect(str(path))
        try:
            for table in ("issues", "pull_requests"):
                if not conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone():
                    return MetricValue(value=0.0, collected_at=now)
            rows = conn.execute(
                "SELECT i.filed_at, p.opened_at "
                "FROM issues i "
                "JOIN pull_requests p ON p.issue_number = i.number "
                "WHERE i.filed_at IS NOT NULL AND p.opened_at IS NOT NULL"
            ).fetchall()
            if not rows:
                return MetricValue(value=0.0, collected_at=now)
            hours = []
            for filed_at, opened_at in rows:
                filed = datetime.fromisoformat(filed_at)
                opened = datetime.fromisoformat(opened_at)
                hours.append((opened - filed).total_seconds() / 3600)
            return MetricValue(value=statistics.median(hours), collected_at=now)
        finally:
            conn.close()
    except Exception:
        return MetricValue(value=0.0, collected_at=now)


def collect_tool_reliability(log_path: Path | str | None = None) -> MetricValue:
    now = datetime.now(UTC).isoformat()

    if log_path is None:
        log_path = Path.home() / ".patina" / "mcp_call_log.jsonl"
    else:
        log_path = Path(log_path)

    try:
        text = log_path.read_text()
    except OSError:
        return MetricValue(value=0.0, collected_at=now, unavailable=True)

    total = 0
    successes = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        total += 1
        if record.get("success"):
            successes += 1

    if total == 0:
        return MetricValue(value=0.0, collected_at=now)

    return MetricValue(value=successes / total, collected_at=now)


def main() -> None:
    snapshot = EvalSnapshot(
        metrics={
            "merge_rate": collect_merge_rate(),
            "time_to_implement": collect_time_to_implement(),
            "tool_reliability": collect_tool_reliability(),
        }
    )
    out = Path(__file__).resolve().parent / "latest.json"
    tmp = out.with_name("latest.json.tmp")
    tmp.write_text(snapshot.model_dump_json(indent=2))
    tmp.replace(out)


if __name__ == "__main__":
    main()
