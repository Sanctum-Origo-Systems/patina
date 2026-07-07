"""Tests for cognitive eval metric collectors."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from eval.cognitive.run import (
    collect_merge_rate,
    collect_time_to_implement,
    collect_tool_reliability,
)


def test_tool_reliability_populated_log(tmp_path):
    log = tmp_path / "call_log.jsonl"
    records = [
        {"tool": "beliefs", "success": True},
        {"tool": "priorities", "success": True},
        {"tool": "relationships", "success": False},
        {"tool": "store_search", "success": True},
        {"tool": "beliefs", "success": False},
    ]
    log.write_text("\n".join(json.dumps(r) for r in records))

    result = collect_tool_reliability(log_path=log)

    assert result.value == 0.6
    assert isinstance(result.value, float)
    datetime.fromisoformat(result.collected_at)


def test_tool_reliability_empty_log(tmp_path):
    log = tmp_path / "call_log.jsonl"
    log.write_text("")

    result = collect_tool_reliability(log_path=log)

    assert result.value == 0.0
    datetime.fromisoformat(result.collected_at)


def test_tool_reliability_missing_path(tmp_path):
    missing = tmp_path / "nonexistent" / "call_log.jsonl"

    result = collect_tool_reliability(log_path=missing)

    assert result.value == 0.0
    assert result.unavailable is True
    datetime.fromisoformat(result.collected_at)


# --- merge_rate and time_to_implement tests ---


def _create_store(tmp_path: Path) -> Path:
    db = tmp_path / "store.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE pull_requests (
            number INTEGER PRIMARY KEY,
            merged INTEGER NOT NULL DEFAULT 0,
            rework INTEGER NOT NULL DEFAULT 0,
            opened_at TEXT,
            issue_number INTEGER
        );
        CREATE TABLE issues (
            number INTEGER PRIMARY KEY,
            filed_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()
    return db


class TestCollectMergeRate:
    def test_multiple_prs_with_and_without_rework(self, tmp_path: Path) -> None:
        db = _create_store(tmp_path)
        conn = sqlite3.connect(str(db))
        conn.executemany(
            "INSERT INTO pull_requests (number, merged, rework) VALUES (?, ?, ?)",
            [
                (1, 1, 0),  # merged, no rework
                (2, 1, 0),  # merged, no rework
                (3, 1, 1),  # merged, with rework
                (4, 0, 0),  # not merged
            ],
        )
        conn.commit()
        conn.close()

        result = collect_merge_rate(db)
        assert result.value == pytest.approx(0.5)
        datetime.fromisoformat(result.collected_at)

    def test_empty_store(self, tmp_path: Path) -> None:
        db = _create_store(tmp_path)
        result = collect_merge_rate(db)
        assert result.value == 0.0
        datetime.fromisoformat(result.collected_at)

    def test_invalid_store_path(self) -> None:
        result = collect_merge_rate(Path("/nonexistent/path/store.db"))
        assert result.value == 0.0
        datetime.fromisoformat(result.collected_at)

    def test_all_merged_no_rework(self, tmp_path: Path) -> None:
        db = _create_store(tmp_path)
        conn = sqlite3.connect(str(db))
        conn.executemany(
            "INSERT INTO pull_requests (number, merged, rework) VALUES (?, ?, ?)",
            [(1, 1, 0), (2, 1, 0), (3, 1, 0)],
        )
        conn.commit()
        conn.close()

        result = collect_merge_rate(db)
        assert result.value == pytest.approx(1.0)

    def test_all_rework(self, tmp_path: Path) -> None:
        db = _create_store(tmp_path)
        conn = sqlite3.connect(str(db))
        conn.executemany(
            "INSERT INTO pull_requests (number, merged, rework) VALUES (?, ?, ?)",
            [(1, 1, 1), (2, 1, 1)],
        )
        conn.commit()
        conn.close()

        result = collect_merge_rate(db)
        assert result.value == 0.0

    def test_collected_at_iso_format(self, tmp_path: Path) -> None:
        db = _create_store(tmp_path)
        result = collect_merge_rate(db)
        parsed = datetime.fromisoformat(result.collected_at)
        assert parsed is not None

    def test_no_pull_requests_table(self, tmp_path: Path) -> None:
        db = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE dummy (id INTEGER)")
        conn.commit()
        conn.close()

        result = collect_merge_rate(db)
        assert result.value == 0.0


class TestCollectTimeToImplement:
    def test_multiple_issue_pr_pairs(self, tmp_path: Path) -> None:
        db = _create_store(tmp_path)
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO issues (number, filed_at) VALUES (?, ?)",
            (1, "2025-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO pull_requests (number, merged, rework, opened_at, issue_number)"
            " VALUES (?, ?, ?, ?, ?)",
            (10, 1, 0, "2025-01-01T10:00:00+00:00", 1),
        )
        conn.execute(
            "INSERT INTO issues (number, filed_at) VALUES (?, ?)",
            (2, "2025-01-02T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO pull_requests (number, merged, rework, opened_at, issue_number)"
            " VALUES (?, ?, ?, ?, ?)",
            (11, 1, 0, "2025-01-02T20:00:00+00:00", 2),
        )
        conn.execute(
            "INSERT INTO issues (number, filed_at) VALUES (?, ?)",
            (3, "2025-01-03T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO pull_requests (number, merged, rework, opened_at, issue_number)"
            " VALUES (?, ?, ?, ?, ?)",
            (12, 1, 0, "2025-01-04T06:00:00+00:00", 3),
        )
        conn.commit()
        conn.close()

        result = collect_time_to_implement(db)
        # Hours: 10, 20, 30 → median = 20
        assert result.value == pytest.approx(20.0)
        datetime.fromisoformat(result.collected_at)

    def test_no_timestamp_data(self, tmp_path: Path) -> None:
        db = _create_store(tmp_path)
        result = collect_time_to_implement(db)
        assert result.value == 0.0
        datetime.fromisoformat(result.collected_at)

    def test_invalid_store_path(self) -> None:
        result = collect_time_to_implement(Path("/nonexistent/path/store.db"))
        assert result.value == 0.0
        datetime.fromisoformat(result.collected_at)

    def test_single_pair(self, tmp_path: Path) -> None:
        db = _create_store(tmp_path)
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO issues (number, filed_at) VALUES (?, ?)",
            (1, "2025-06-01T12:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO pull_requests (number, merged, rework, opened_at, issue_number)"
            " VALUES (?, ?, ?, ?, ?)",
            (5, 1, 0, "2025-06-01T18:00:00+00:00", 1),
        )
        conn.commit()
        conn.close()

        result = collect_time_to_implement(db)
        assert result.value == pytest.approx(6.0)

    def test_even_number_of_pairs(self, tmp_path: Path) -> None:
        db = _create_store(tmp_path)
        conn = sqlite3.connect(str(db))
        for i, hours in enumerate([10, 20], start=1):
            conn.execute(
                "INSERT INTO issues (number, filed_at) VALUES (?, ?)",
                (i, "2025-01-01T00:00:00+00:00"),
            )
            conn.execute(
                "INSERT INTO pull_requests (number, merged, rework, opened_at, issue_number)"
                " VALUES (?, ?, ?, ?, ?)",
                (100 + i, 1, 0, f"2025-01-01T{hours:02d}:00:00+00:00", i),
            )
        conn.commit()
        conn.close()

        result = collect_time_to_implement(db)
        # Hours: 10, 20 → median = 15
        assert result.value == pytest.approx(15.0)

    def test_collected_at_iso_format(self, tmp_path: Path) -> None:
        db = _create_store(tmp_path)
        result = collect_time_to_implement(db)
        parsed = datetime.fromisoformat(result.collected_at)
        assert parsed is not None

    def test_prs_without_matching_issues(self, tmp_path: Path) -> None:
        db = _create_store(tmp_path)
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO pull_requests (number, merged, rework, opened_at, issue_number)"
            " VALUES (?, ?, ?, ?, ?)",
            (1, 1, 0, "2025-01-01T10:00:00+00:00", 999),
        )
        conn.commit()
        conn.close()

        result = collect_time_to_implement(db)
        assert result.value == 0.0

    def test_no_issues_table(self, tmp_path: Path) -> None:
        db = tmp_path / "partial.db"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE pull_requests "
            "(number INTEGER PRIMARY KEY, opened_at TEXT, issue_number INTEGER)"
        )
        conn.commit()
        conn.close()

        result = collect_time_to_implement(db)
        assert result.value == 0.0
