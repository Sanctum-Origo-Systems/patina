"""Tests for eval/cognitive/update_changelog.py."""

from __future__ import annotations

import subprocess
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from eval.cognitive.update_changelog import (
    append_entry,
    clean_title,
    daily,
    has_open_changelog_pr,
    main,
    trim_changelog,
)


@pytest.fixture()
def changelog(tmp_path: Path) -> Path:
    return tmp_path / "CHANGELOG.md"


@pytest.fixture()
def archive(tmp_path: Path) -> Path:
    return tmp_path / "changelog-archive.md"


class TestCleanTitle:
    def test_strips_duplicate_fix_prefix(self) -> None:
        assert clean_title("fix: fix: something broken") == "Fix: something broken"

    def test_strips_duplicate_feat_prefix(self) -> None:
        assert clean_title("feat: feat: add new feature") == "Feat: add new feature"

    def test_strips_duplicate_refactor_prefix(self) -> None:
        assert clean_title("refactor: refactor: extract helper") == "Refactor: extract helper"

    def test_strips_duplicate_test_prefix(self) -> None:
        assert clean_title("test: test: add unit tests") == "Test: add unit tests"

    def test_strips_duplicate_docs_prefix(self) -> None:
        assert clean_title("docs: docs: update readme") == "Docs: update readme"

    def test_strips_duplicate_chore_prefix(self) -> None:
        assert clean_title("chore: chore: bump deps") == "Chore: bump deps"

    def test_removes_trailing_issue_ref(self) -> None:
        assert clean_title("fix: something (#123)") == "Fix: something"

    def test_removes_trailing_issue_ref_with_spaces(self) -> None:
        assert clean_title("feat: add feature  (#456) ") == "Feat: add feature"

    def test_both_duplicate_and_issue_ref(self) -> None:
        assert clean_title("fix: fix: something (#123)") == "Fix: something"

    def test_capitalizes_single_prefix(self) -> None:
        assert clean_title("fix: something") == "Fix: something"
        assert clean_title("feat: something") == "Feat: something"
        assert clean_title("refactor: something") == "Refactor: something"

    def test_no_prefix_unchanged(self) -> None:
        assert clean_title("Something else entirely") == "Something else entirely"

    def test_preserves_non_duplicate_nested_prefixes(self) -> None:
        assert clean_title("feat: test: something") == "Feat: test: something"

    def test_preserves_internal_issue_refs(self) -> None:
        assert clean_title("fix: handle (#123) edge case (#456)") == "Fix: handle (#123) edge case"

    def test_whitespace_handling(self) -> None:
        assert clean_title("  fix: fix:  extra spaces  ") == "Fix: extra spaces"

    def test_case_insensitive_duplicate(self) -> None:
        assert clean_title("Fix: fix: something") == "Fix: something"
        assert clean_title("FEAT: feat: something") == "Feat: something"

    def test_real_world_title(self) -> None:
        assert (
            clean_title("fix: fix: store_search fails on queries containing colons (#157)")
            == "Fix: store_search fails on queries containing colons"
        )

    def test_real_world_feat_title(self) -> None:
        assert (
            clean_title("feat: feat: add AutoLoopConfig dataclass and autoloop.toml config  (#121)")
            == "Feat: add AutoLoopConfig dataclass and autoloop.toml config"
        )


class TestAppendEntry:
    def test_creates_file_with_version_header(self, changelog: Path) -> None:
        today = date(2026, 7, 30)
        append_entry(
            42,
            "Fix login bug",
            1.23,
            version="0.10.0",
            changelog_path=changelog,
            today=today,
        )
        text = changelog.read_text()
        assert "## v0.10.0 (2026-07-30)" in text
        assert "- #42: Fix login bug ($1.23)" in text
        assert "Total: 1 PRs, $1.23" in text

    def test_cleans_title_on_write(self, changelog: Path) -> None:
        today = date(2026, 7, 30)
        append_entry(
            42,
            "fix: fix: something broken (#99)",
            1.00,
            version="0.10.0",
            changelog_path=changelog,
            today=today,
        )
        text = changelog.read_text()
        assert "Fix: something broken" in text
        assert "fix: fix:" not in text
        assert "(#99)" not in text

    def test_appends_to_existing_version_block(self, changelog: Path) -> None:
        today = date(2026, 7, 30)
        append_entry(42, "First", 1.00, version="0.10.0", changelog_path=changelog, today=today)
        append_entry(43, "Second", 2.00, version="0.10.0", changelog_path=changelog, today=today)
        text = changelog.read_text()
        assert text.count("## v0.10.0") == 1
        assert "- #42: First ($1.00)" in text
        assert "- #43: Second ($2.00)" in text
        assert "Total: 2 PRs, $3.00" in text

    def test_new_version_prepended(self, changelog: Path) -> None:
        today = date(2026, 7, 30)
        append_entry(42, "First", 1.00, version="0.9.0", changelog_path=changelog, today=today)
        append_entry(43, "Second", 2.00, version="0.10.0", changelog_path=changelog, today=today)
        text = changelog.read_text()
        idx_10 = text.index("## v0.10.0")
        idx_9 = text.index("## v0.9.0")
        assert idx_10 < idx_9

    def test_multiple_entries_same_version(self, changelog: Path) -> None:
        today = date(2026, 7, 30)
        for i in range(5):
            append_entry(
                i,
                f"PR {i}",
                float(i),
                version="1.0.0",
                changelog_path=changelog,
                today=today,
            )
        text = changelog.read_text()
        assert text.count("## v1.0.0") == 1
        assert "Total: 5 PRs, $10.00" in text

    def test_cost_formatted_two_decimal_places(self, changelog: Path) -> None:
        today = date(2026, 7, 30)
        append_entry(42, "Fix bug", 0.5, version="1.0.0", changelog_path=changelog, today=today)
        text = changelog.read_text()
        assert "$0.50" in text

    def test_empty_file_creates_block(self, changelog: Path) -> None:
        changelog.write_text("")
        today = date(2026, 7, 30)
        append_entry(42, "First", 1.00, version="1.0.0", changelog_path=changelog, today=today)
        text = changelog.read_text()
        assert "## v1.0.0 (2026-07-30)" in text
        assert "Total: 1 PRs, $1.00" in text


class TestTrimChangelog:
    def _write_version_block(
        self, path: Path, version: str, block_date: date, entries: list[tuple[int, str, float]]
    ) -> None:
        total = sum(c for _, _, c in entries)
        block = f"## v{version} ({block_date.isoformat()})\n"
        for num, title, cost in entries:
            block += f"- #{num}: {title} (${cost:.2f})\n"
        block += f"Total: {len(entries)} PRs, ${total:.2f}\n"
        with open(path, "a") as f:
            f.write(block)

    def test_archives_old_version_block(self, changelog: Path, archive: Path) -> None:
        today = date(2026, 7, 30)
        old_date = today - timedelta(days=20)
        recent_date = today - timedelta(days=5)

        changelog.write_text(
            f"## v0.9.0 ({recent_date.isoformat()})\n"
            f"- #2: Recent fix ($0.75)\n"
            f"Total: 1 PRs, $0.75\n"
            f"\n"
            f"## v0.8.0 ({old_date.isoformat()})\n"
            f"- #1: Old fix ($0.50)\n"
            f"Total: 1 PRs, $0.50\n"
        )

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        cl_text = changelog.read_text()
        assert "v0.9.0" in cl_text
        assert "v0.8.0" not in cl_text

        ar_text = archive.read_text()
        assert "v0.8.0" in ar_text
        assert "#1: Old fix" in ar_text

    def test_preserves_version_block_integrity(self, changelog: Path, archive: Path) -> None:
        """A version block with multiple entries is never split."""
        today = date(2026, 7, 30)
        old_date = today - timedelta(days=20)

        changelog.write_text(
            f"## v0.8.0 ({old_date.isoformat()})\n"
            f"- #1: First ($0.50)\n"
            f"- #2: Second ($0.75)\n"
            f"- #3: Third ($1.00)\n"
            f"Total: 3 PRs, $2.25\n"
        )

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        ar_text = archive.read_text()
        assert "## v0.8.0" in ar_text
        assert "#1: First" in ar_text
        assert "#2: Second" in ar_text
        assert "#3: Third" in ar_text
        assert "Total: 3 PRs, $2.25" in ar_text

    def test_all_recent_leaves_unchanged(self, changelog: Path, archive: Path) -> None:
        today = date(2026, 7, 30)
        recent = today - timedelta(days=3)

        changelog.write_text(
            f"## v0.9.0 ({recent.isoformat()})\n"
            f"- #1: Recent A ($0.50)\n"
            f"- #2: Recent B ($0.75)\n"
            f"Total: 2 PRs, $1.25\n"
        )
        original = changelog.read_bytes()

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        assert changelog.read_bytes() == original
        assert not archive.exists()

    def test_all_old_clears_changelog(self, changelog: Path, archive: Path) -> None:
        today = date(2026, 7, 30)
        old = today - timedelta(days=30)

        changelog.write_text(
            f"## v0.7.0 ({old.isoformat()})\n"
            f"- #1: Old A ($0.50)\n"
            f"Total: 1 PRs, $0.50\n"
            f"\n"
            f"## v0.6.0 ({old.isoformat()})\n"
            f"- #2: Old B ($0.75)\n"
            f"Total: 1 PRs, $0.75\n"
        )

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        assert changelog.read_text() == ""
        ar_text = archive.read_text()
        assert "v0.7.0" in ar_text
        assert "v0.6.0" in ar_text

    def test_archive_appends_not_overwrites(self, changelog: Path, archive: Path) -> None:
        today = date(2026, 7, 30)
        old = today - timedelta(days=20)

        archive.write_text(
            "## v0.5.0 (2026-01-01)\n- #0: Preexisting ($0.10)\nTotal: 1 PRs, $0.10\n"
        )
        changelog.write_text(
            f"## v0.8.0 ({old.isoformat()})\n- #1: Old fix ($0.50)\nTotal: 1 PRs, $0.50\n"
        )

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        ar_text = archive.read_text()
        assert "v0.5.0" in ar_text
        assert "#0: Preexisting" in ar_text
        assert "v0.8.0" in ar_text
        assert "#1: Old fix" in ar_text

    def test_no_duplicates_between_files(self, changelog: Path, archive: Path) -> None:
        today = date(2026, 7, 30)
        old = today - timedelta(days=20)
        recent = today - timedelta(days=1)

        changelog.write_text(
            f"## v0.9.0 ({recent.isoformat()})\n"
            f"- #2: Recent ($0.75)\n"
            f"Total: 1 PRs, $0.75\n"
            f"\n"
            f"## v0.8.0 ({old.isoformat()})\n"
            f"- #1: Old ($0.50)\n"
            f"Total: 1 PRs, $0.50\n"
        )

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        cl_text = changelog.read_text()
        ar_text = archive.read_text()
        assert "#1: Old" not in cl_text
        assert "#1: Old" in ar_text
        assert "#2: Recent" in cl_text
        assert "#2: Recent" not in ar_text

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
        today = date(2026, 7, 30)
        boundary = today - timedelta(days=14)

        changelog.write_text(
            f"## v0.8.0 ({boundary.isoformat()})\n- #1: Boundary ($0.50)\nTotal: 1 PRs, $0.50\n"
        )

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        assert "#1: Boundary" in changelog.read_text()
        assert not archive.exists()

    def test_block_without_date_kept(self, changelog: Path, archive: Path) -> None:
        """Blocks with no parseable date in the header are never archived."""
        today = date(2026, 7, 30)
        old = today - timedelta(days=20)

        changelog.write_text(
            f"## v0.8.0\n"
            f"- #1: No date ($0.50)\n"
            f"Total: 1 PRs, $0.50\n"
            f"\n"
            f"## v0.7.0 ({old.isoformat()})\n"
            f"- #2: Old ($0.75)\n"
            f"Total: 1 PRs, $0.75\n"
        )

        trim_changelog(days=14, changelog_path=changelog, archive_path=archive, today=today)

        cl_text = changelog.read_text()
        assert "v0.8.0" in cl_text
        assert "#1: No date" in cl_text
        ar_text = archive.read_text()
        assert "v0.7.0" in ar_text


class TestHasOpenChangelogPr:
    def test_returns_true_when_open_pr_exists(self) -> None:
        fake = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='[{"number": 197}]', stderr=""
        )
        with patch("eval.cognitive.update_changelog.subprocess.run", return_value=fake) as mock:
            assert has_open_changelog_pr("owner/repo") is True
        args = mock.call_args[0][0]
        assert "--state" in args
        assert args[args.index("--state") + 1] == "open"
        assert "head:chore/changelog-" in args

    def test_returns_false_when_no_open_pr(self) -> None:
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="[]", stderr="")
        with patch("eval.cognitive.update_changelog.subprocess.run", return_value=fake):
            assert has_open_changelog_pr("owner/repo") is False

    def test_returns_false_on_gh_failure(self) -> None:
        fake = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="error")
        with patch("eval.cognitive.update_changelog.subprocess.run", return_value=fake):
            assert has_open_changelog_pr("owner/repo") is False


class TestDailySkipsOnOpenPr:
    def test_skips_when_open_changelog_pr_exists(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch(
                "eval.cognitive.update_changelog.has_open_changelog_pr", return_value=True
            ) as mock_check,
            patch("eval.cognitive.update_changelog.fetch_merged_prs") as mock_fetch,
        ):
            from eval.cognitive.update_changelog import daily

            daily("owner/repo")

        mock_check.assert_called_once_with("owner/repo")
        mock_fetch.assert_not_called()
        assert "skipping" in capsys.readouterr().out.lower()

    def test_proceeds_when_no_open_changelog_pr(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("eval.cognitive.update_changelog.has_open_changelog_pr", return_value=False),
            patch("eval.cognitive.update_changelog.fetch_merged_prs", return_value=[]),
        ):
            from eval.cognitive.update_changelog import daily

            daily("owner/repo")

        assert "no new merged prs" in capsys.readouterr().out.lower()


class TestUvLockSync:
    """After bump_version(), both daily() and single must run `uv lock`."""

    def test_daily_calls_uv_lock_and_stages_lockfile(self, tmp_path: Path) -> None:
        changelog = tmp_path / "CHANGELOG.md"
        archive = tmp_path / "changelog-archive.md"
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "patina"\nversion = "0.15.0"\n')

        fake_pr = {
            "number": 100,
            "title": "feat: add widget",
            "body": "- Cost: $1.00",
        }

        calls: list[list[str]] = []

        def track_subprocess(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:3] == ["git", "diff", "--cached"]:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch("eval.cognitive.update_changelog.has_open_changelog_pr", return_value=False),
            patch("eval.cognitive.update_changelog.fetch_merged_prs", return_value=[fake_pr]),
            patch("eval.cognitive.update_changelog.existing_pr_numbers", return_value=set()),
            patch("eval.cognitive.update_changelog.CHANGELOG_PATH", changelog),
            patch("eval.cognitive.update_changelog.ARCHIVE_PATH", archive),
            patch("eval.cognitive.update_changelog.PYPROJECT_PATH", pyproject),
            patch("eval.cognitive.update_changelog.subprocess.run", side_effect=track_subprocess),
        ):
            daily("owner/repo")

        uv_lock_calls = [c for c in calls if c[:2] == ["uv", "lock"]]
        assert uv_lock_calls, "uv lock must be called after bump_version()"

        git_add_calls = [c for c in calls if c[:2] == ["git", "add"]]
        staged_files = [c[2] for c in git_add_calls]
        assert "uv.lock" in staged_files, "uv.lock must be staged"

    def test_daily_skips_uv_lock_when_no_bump(self, tmp_path: Path) -> None:
        changelog = tmp_path / "CHANGELOG.md"
        archive = tmp_path / "changelog-archive.md"
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "patina"\nversion = "0.15.0"\n')

        fake_pr = {
            "number": 100,
            "title": "chore: update deps",
            "body": "- Cost: $0.50",
        }

        calls: list[list[str]] = []

        def track_subprocess(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:3] == ["git", "diff", "--cached"]:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch("eval.cognitive.update_changelog.has_open_changelog_pr", return_value=False),
            patch("eval.cognitive.update_changelog.fetch_merged_prs", return_value=[fake_pr]),
            patch("eval.cognitive.update_changelog.existing_pr_numbers", return_value=set()),
            patch("eval.cognitive.update_changelog.CHANGELOG_PATH", changelog),
            patch("eval.cognitive.update_changelog.ARCHIVE_PATH", archive),
            patch("eval.cognitive.update_changelog.PYPROJECT_PATH", pyproject),
            patch("eval.cognitive.update_changelog.subprocess.run", side_effect=track_subprocess),
        ):
            daily("owner/repo")

        uv_lock_calls = [c for c in calls if c[:2] == ["uv", "lock"]]
        assert not uv_lock_calls, "uv lock should not be called when no version bump"

    def test_single_calls_uv_lock_on_version_bump(self, tmp_path: Path) -> None:
        changelog = tmp_path / "CHANGELOG.md"
        archive = tmp_path / "changelog-archive.md"
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "patina"\nversion = "0.15.0"\n')

        calls: list[list[str]] = []

        def track_subprocess(cmd, **kwargs):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch("eval.cognitive.update_changelog.CHANGELOG_PATH", changelog),
            patch("eval.cognitive.update_changelog.ARCHIVE_PATH", archive),
            patch("eval.cognitive.update_changelog.PYPROJECT_PATH", pyproject),
            patch("eval.cognitive.update_changelog.subprocess.run", side_effect=track_subprocess),
        ):
            main(["single", "--number", "100", "--title", "feat: add widget", "--cost", "1.0"])

        uv_lock_calls = [c for c in calls if c[:2] == ["uv", "lock"]]
        assert uv_lock_calls, "uv lock must be called after bump_version() in single path"
