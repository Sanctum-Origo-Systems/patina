"""Tests for eval/cognitive/update_changelog.py."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from eval.cognitive.update_changelog import append_entry, trim_changelog


@pytest.fixture()
def changelog(tmp_path: Path) -> Path:
    return tmp_path / "CHANGELOG.md"


@pytest.fixture()
def archive(tmp_path: Path) -> Path:
    return tmp_path / "changelog-archive.md"


class TestAppendEntry:
    def test_creates_file_and_appends(self, changelog: Path) -> None:
        append_entry(42, "Fix login bug", 1.23, changelog_path=changelog)
        lines = changelog.read_text().splitlines()
        assert len(lines) == 1
        assert lines[0].startswith("- #42: Fix login bug ($1.23)")

    def test_exact_format_with_datestamp(self, changelog: Path) -> None:
        today = date(2026, 7, 6)
        append_entry(42, "Fix login bug", 1.23, changelog_path=changelog, today=today)
        assert changelog.read_text() == "- #42: Fix login bug ($1.23) [2026-07-06]\n"

    def test_appends_without_modifying_existing(self, changelog: Path) -> None:
        today = date(2026, 7, 6)
        changelog.write_text("- #1: First ($0.50) [2026-07-05]\n")
        append_entry(2, "Second", 0.75, changelog_path=changelog, today=today)
        lines = changelog.read_text().splitlines()
        assert len(lines) == 2
        assert lines[0] == "- #1: First ($0.50) [2026-07-05]"
        assert lines[1] == "- #2: Second ($0.75) [2026-07-06]"

    def test_multiple_appends(self, changelog: Path) -> None:
        today = date(2026, 7, 6)
        for i in range(5):
            append_entry(i, f"PR {i}", float(i), changelog_path=changelog, today=today)
        lines = changelog.read_text().splitlines()
        assert len(lines) == 5


class TestTrimChangelog:
    def _write_entries(self, path: Path, entries: list[tuple[int, str, float, date]]) -> None:
        with open(path, "w") as f:
            for num, title, cost, d in entries:
                f.write(f"- #{num}: {title} (${cost}) [{d.isoformat()}]\n")

    def test_moves_old_entries_to_archive(self, changelog: Path, archive: Path) -> None:
        today = date(2026, 7, 6)
        old = today - timedelta(days=20)
        recent = today - timedelta(days=5)
        self._write_entries(
            changelog,
            [
                (1, "Old fix", 0.50, old),
                (2, "Recent fix", 0.75, recent),
            ],
        )

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        cl_lines = changelog.read_text().splitlines()
        assert len(cl_lines) == 1
        assert "#2: Recent fix" in cl_lines[0]

        ar_lines = archive.read_text().splitlines()
        assert len(ar_lines) == 1
        assert "#1: Old fix" in ar_lines[0]

    def test_all_recent_leaves_unchanged(self, changelog: Path, archive: Path) -> None:
        today = date(2026, 7, 6)
        recent = today - timedelta(days=3)
        self._write_entries(
            changelog,
            [
                (1, "Recent A", 0.50, recent),
                (2, "Recent B", 0.75, today),
            ],
        )
        original = changelog.read_bytes()

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        assert changelog.read_bytes() == original
        assert not archive.exists()

    def test_all_old_clears_changelog(self, changelog: Path, archive: Path) -> None:
        today = date(2026, 7, 6)
        old = today - timedelta(days=30)
        self._write_entries(
            changelog,
            [
                (1, "Old A", 0.50, old),
                (2, "Old B", 0.75, old),
            ],
        )

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        assert changelog.read_text() == ""
        ar_lines = archive.read_text().splitlines()
        assert len(ar_lines) == 2

    def test_archive_appends_not_overwrites(self, changelog: Path, archive: Path) -> None:
        today = date(2026, 7, 6)
        old = today - timedelta(days=20)
        archive.write_text("- #0: Preexisting ($0.10) [2026-01-01]\n")
        self._write_entries(changelog, [(1, "Old fix", 0.50, old)])

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        ar_lines = archive.read_text().splitlines()
        assert len(ar_lines) == 2
        assert "#0: Preexisting" in ar_lines[0]
        assert "#1: Old fix" in ar_lines[1]

    def test_no_duplicates_between_files(self, changelog: Path, archive: Path) -> None:
        today = date(2026, 7, 6)
        old = today - timedelta(days=20)
        recent = today - timedelta(days=1)
        self._write_entries(
            changelog,
            [
                (1, "Old", 0.50, old),
                (2, "Recent", 0.75, recent),
            ],
        )

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        cl_text = changelog.read_text()
        ar_text = archive.read_text()
        assert "#1: Old" not in cl_text
        assert "#1: Old" in ar_text
        assert "#2: Recent" in cl_text
        assert "#2: Recent" not in ar_text

    def test_remaining_entries_within_window(self, changelog: Path, archive: Path) -> None:
        today = date(2026, 7, 6)
        entries = [(i, f"PR {i}", float(i), today - timedelta(days=i)) for i in range(30)]
        self._write_entries(changelog, entries)

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        for line in changelog.read_text().splitlines():
            bracket_start = line.rfind("[")
            bracket_end = line.rfind("]")
            entry_date = date.fromisoformat(line[bracket_start + 1 : bracket_end])
            age = (today - entry_date).days
            assert age <= 14, f"Entry too old ({age} days): {line}"

    def test_entries_verbatim_in_archive(self, changelog: Path, archive: Path) -> None:
        today = date(2026, 7, 6)
        old = today - timedelta(days=20)
        self._write_entries(
            changelog,
            [
                (1, "Old fix", 0.50, old),
                (2, "Recent", 0.75, today),
            ],
        )
        original_lines = changelog.read_text().splitlines()
        old_line = original_lines[0]

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        assert old_line in archive.read_text().splitlines()

    def test_missing_changelog_is_noop(self, changelog: Path, archive: Path) -> None:
        trim_changelog(days=14, changelog_path=changelog, archive_path=archive)
        assert not changelog.exists()
        assert not archive.exists()

    def test_empty_changelog_is_noop(self, changelog: Path, archive: Path) -> None:
        changelog.write_text("")
        trim_changelog(days=14, changelog_path=changelog, archive_path=archive)
        assert changelog.read_text() == ""
        assert not archive.exists()

    def test_boundary_exactly_14_days_kept(self, changelog: Path, archive: Path) -> None:
        today = date(2026, 7, 6)
        boundary = today - timedelta(days=14)
        self._write_entries(changelog, [(1, "Boundary", 0.50, boundary)])

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        assert "#1: Boundary" in changelog.read_text()
        assert not archive.exists()
