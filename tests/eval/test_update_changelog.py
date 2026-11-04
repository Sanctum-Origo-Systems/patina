"""Tests for eval/cognitive/update_changelog.py."""

from __future__ import annotations

import json
import subprocess
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from eval.cognitive.update_changelog import (
    append_entry,
    clean_title,
    daily,
    find_open_changelog_pr,
    has_open_changelog_pr,
    lookback_days,
    main,
    top_block,
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


class TestFindOpenChangelogPr:
    def test_returns_number_and_branch(self) -> None:
        fake = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='[{"number": 591, "headRefName": "chore/changelog-2026-11-03"}]',
            stderr="",
        )
        with patch("eval.cognitive.update_changelog.subprocess.run", return_value=fake) as mock:
            assert find_open_changelog_pr("owner/repo") == {
                "number": 591,
                "headRefName": "chore/changelog-2026-11-03",
            }
        args = mock.call_args[0][0]
        assert "number,headRefName" in args

    def test_returns_none_when_no_open_pr(self) -> None:
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="[]", stderr="")
        with patch("eval.cognitive.update_changelog.subprocess.run", return_value=fake):
            assert find_open_changelog_pr("owner/repo") is None


class TestLookbackDays:
    def test_covers_since_latest_block(self, changelog: Path) -> None:
        today = date(2026, 11, 3)
        changelog.write_text("## v0.34.0 (2026-10-31)\n- #1: Fix: a ($0.10)\nTotal: 1 PRs, $0.10\n")
        assert lookback_days(1, changelog_path=changelog, today=today) == 3

    def test_never_shorter_than_since_days(self, changelog: Path) -> None:
        today = date(2026, 11, 3)
        changelog.write_text("## v0.34.0 (2026-11-03)\n- #1: Fix: a ($0.10)\nTotal: 1 PRs, $0.10\n")
        assert lookback_days(1, changelog_path=changelog, today=today) == 1

    def test_falls_back_to_seven_days(self, changelog: Path) -> None:
        assert lookback_days(1, changelog_path=changelog, today=date(2026, 11, 3)) == 7


class TestDailyNoOpenPr:
    def test_proceeds_when_no_open_changelog_pr(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("eval.cognitive.update_changelog.find_open_changelog_pr", return_value=None),
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
            patch("eval.cognitive.update_changelog.find_open_changelog_pr", return_value=None),
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
            patch("eval.cognitive.update_changelog.find_open_changelog_pr", return_value=None),
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


BRANCH = "chore/changelog-2026-11-03"
TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)

MAIN_CHANGELOG = (
    f"## v0.34.0 ({YESTERDAY.isoformat()})\n"
    "- #572: Feat: add the quick brown fox ($0.96)\n"
    "- #571: Feat: jump over the lazy dog ($0.66)\n"
    "Total: 2 PRs, $1.62\n"
)


def _pyproject(version: str) -> str:
    return f'[project]\nname = "patina"\nversion = "{version}"\n'


def _merged(number: int, title: str, cost: float) -> dict:
    return {
        "number": number,
        "title": title,
        "body": f"## Summary\n- Cost: ${cost:.2f}\n",
        "mergedAt": f"{TODAY.isoformat()}T09:00:00Z",
    }


class TestDailyUpdatesOpenPr:
    """With an open chore/changelog-* PR, daily() adds late merges to that PR's branch."""

    def _run(
        self,
        tmp_path: Path,
        *,
        branch_block: str,
        branch_version: str,
        merged: list[dict],
        main_changelog: str = MAIN_CHANGELOG,
        main_version: str = "0.34.0",
        open_prs: list[dict] | None = None,
        fail_on: list[str] | None = None,
    ) -> tuple[list[list[str]], Path, Path]:
        changelog = tmp_path / "CHANGELOG.md"
        archive = tmp_path / "changelog-archive.md"
        pyproject = tmp_path / "pyproject.toml"
        changelog.write_text(main_changelog)
        pyproject.write_text(_pyproject(main_version))
        if open_prs is None:
            open_prs = [{"number": 591, "headRefName": BRANCH}]

        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            out, code = "", 0
            if cmd[:3] == ["gh", "pr", "list"]:
                state = cmd[cmd.index("--state") + 1]
                out = json.dumps(open_prs if state == "open" else merged)
            elif cmd == ["git", "checkout", BRANCH]:
                # Simulate switching the working tree to the PR branch.
                changelog.write_text(branch_block + "\n" + main_changelog)
                pyproject.write_text(_pyproject(branch_version))
            elif cmd[:3] == ["git", "diff", "--cached"]:
                code = 1
            if fail_on and cmd[:2] == ["git", fail_on[0]]:
                code = 1
            return subprocess.CompletedProcess(args=cmd, returncode=code, stdout=out, stderr="")

        with (
            patch("eval.cognitive.update_changelog.CHANGELOG_PATH", changelog),
            patch("eval.cognitive.update_changelog.ARCHIVE_PATH", archive),
            patch("eval.cognitive.update_changelog.PYPROJECT_PATH", pyproject),
            patch("eval.cognitive.update_changelog.subprocess.run", side_effect=fake_run),
        ):
            daily("owner/repo")

        return calls, changelog, pyproject

    @staticmethod
    def _pr_edit(calls: list[list[str]]) -> list[str]:
        edits = [c for c in calls if c[:3] == ["gh", "pr", "edit"]]
        assert len(edits) == 1
        return edits[0]

    def test_late_feats_promote_patch_block_to_minor(self, tmp_path: Path) -> None:
        branch_block = (
            f"## v0.34.1 ({TODAY.isoformat()})\n"
            "- #590: Docs: fix the quick brown fox example ($0.50)\n"
            "Total: 1 PRs, $0.50\n"
        )
        merged = [
            _merged(592, "feat: add Jordan Example's widget (#580)", 1.00),
            _merged(593, "feat: feat: résumé parser handles “smart quotes”", 2.00),
            _merged(594, "feat: add lazy dog filter", 0.25),
            _merged(595, "feat: add sample gadget", 0.75),
        ]

        calls, changelog, pyproject = self._run(
            tmp_path, branch_block=branch_block, branch_version="0.34.1", merged=merged
        )

        text = changelog.read_text()
        assert f"## v0.35.0 ({TODAY.isoformat()})" in text
        assert "v0.34.1" not in text
        assert "v0.35.1" not in text
        version, entries = top_block(changelog)
        assert version == "0.35.0"
        assert [n for n, _ in entries] == [590, 592, 593, 594, 595]
        assert "- #593: Feat: résumé parser handles “smart quotes” ($2.00)" in text
        assert "Total: 5 PRs, $4.50" in text
        # main's block is untouched
        assert "## v0.34.0" in text
        assert "Total: 2 PRs, $1.62" in text

        assert 'version = "0.35.0"' in pyproject.read_text()
        assert ["uv", "lock"] in calls
        assert ["git", "add", "pyproject.toml"] in calls
        assert ["git", "add", "uv.lock"] in calls

        commits = [c for c in calls if c[:2] == ["git", "commit"]]
        assert commits == [
            ["git", "commit", "-m", "chore: add #592, #593, #594, #595 to v0.35.0 changelog"]
        ]
        assert ["git", "push", "origin", BRANCH] in calls

        edit = self._pr_edit(calls)
        assert edit[3] == "591"
        assert edit[edit.index("--title") + 1] == "chore: update changelog and version (v0.35.0)"
        assert edit[edit.index("--body") + 1].endswith("5 PR(s) added.")
        assert not any(c[:3] == ["gh", "pr", "create"] for c in calls)

    def test_fix_on_minor_block_keeps_version(self, tmp_path: Path) -> None:
        main_changelog = (
            f"## v0.33.0 ({YESTERDAY.isoformat()})\n"
            "- #565: Fix: the quick brown fox ($0.64)\n"
            "Total: 1 PRs, $0.64\n"
        )
        branch_block = (
            f"## v0.34.0 ({TODAY.isoformat()})\n"
            "- #572: Feat: add the quick brown fox ($0.96)\n"
            "Total: 1 PRs, $0.96\n"
        )
        merged = [_merged(573, "fix: lazy dog crashes on empty input", 0.40)]

        calls, changelog, pyproject = self._run(
            tmp_path,
            branch_block=branch_block,
            branch_version="0.34.0",
            merged=merged,
            main_changelog=main_changelog,
            main_version="0.33.0",
        )

        version, entries = top_block(changelog)
        assert version == "0.34.0"
        assert [n for n, _ in entries] == [572, 573]
        assert "Total: 2 PRs, $1.36" in changelog.read_text()
        assert 'version = "0.34.0"' in pyproject.read_text()
        assert ["uv", "lock"] not in calls
        assert ["git", "add", "pyproject.toml"] not in calls
        assert ["git", "commit", "-m", "chore: add #573 to v0.34.0 changelog"] in calls
        edit = self._pr_edit(calls)
        assert edit[edit.index("--title") + 1] == "chore: update changelog and version (v0.34.0)"

    def test_skips_prs_on_branch_or_main(self, tmp_path: Path) -> None:
        branch_block = (
            f"## v0.35.0 ({TODAY.isoformat()})\n"
            "- #580: Feat: add sample gadget ($1.00)\n"
            "Total: 1 PRs, $1.00\n"
        )
        merged = [
            _merged(572, "feat: add the quick brown fox", 0.96),  # in main's CHANGELOG
            _merged(580, "feat: add sample gadget", 1.00),  # in branch's block
            _merged(581, "fix: lazy dog edge case", 0.20),  # new
        ]

        calls, changelog, _ = self._run(
            tmp_path, branch_block=branch_block, branch_version="0.35.0", merged=merged
        )

        text = changelog.read_text()
        assert text.count("- #572:") == 1
        assert text.count("- #580:") == 1
        assert text.count("- #581:") == 1
        _, entries = top_block(changelog)
        assert [n for n, _ in entries] == [580, 581]
        assert "Total: 2 PRs, $1.20" in text
        assert ["git", "commit", "-m", "chore: add #581 to v0.35.0 changelog"] in calls

    def test_no_new_merges_no_commit_or_push(self, tmp_path: Path) -> None:
        branch_block = (
            f"## v0.35.0 ({TODAY.isoformat()})\n"
            "- #580: Feat: add sample gadget ($1.00)\n"
            "Total: 1 PRs, $1.00\n"
        )
        merged = [
            _merged(572, "feat: add the quick brown fox", 0.96),
            _merged(580, "feat: add sample gadget", 1.00),
        ]

        calls, changelog, _ = self._run(
            tmp_path, branch_block=branch_block, branch_version="0.35.0", merged=merged
        )

        assert not any(c[:2] == ["git", "commit"] for c in calls)
        assert not any(c[:2] == ["git", "push"] for c in calls)
        assert not any(c[:3] == ["gh", "pr", "edit"] for c in calls)
        assert calls[-1] == ["git", "checkout", "main"]

    def test_builds_on_branch_head_without_force_or_reset(self, tmp_path: Path) -> None:
        # A manual entry added by hand on the branch must survive.
        branch_block = (
            f"## v0.34.1 ({TODAY.isoformat()})\n"
            "- #590: Fix: Jordan Example’s inbox — the quick brown fox "
            "($0.00, external contribution)\n"
            "Total: 1 PRs, $0.00\n"
        )
        merged = [_merged(592, "fix: lazy dog filter", 0.30)]

        calls, changelog, _ = self._run(
            tmp_path, branch_block=branch_block, branch_version="0.34.1", merged=merged
        )

        git_calls = [c for c in calls if c[0] == "git"]
        sync = [
            ["git", "fetch", "origin", BRANCH],
            ["git", "checkout", BRANCH],
            ["git", "merge", "--ff-only", f"origin/{BRANCH}"],
        ]
        assert git_calls[:3] == sync
        for c in git_calls:
            assert "reset" not in c
            assert "rebase" not in c
            assert "-B" not in c
            assert not any(arg.startswith(("--force", "-f")) for arg in c)
        assert ["git", "push", "origin", BRANCH] in calls

        text = changelog.read_text()
        assert "Jordan Example’s inbox — the quick brown fox ($0.00, external contribution)" in text
        assert "- #592: Fix: lazy dog filter ($0.30)" in text
        assert "Total: 2 PRs, $0.30" in text

    def test_stops_when_branch_cannot_fast_forward(self, tmp_path: Path) -> None:
        branch_block = (
            f"## v0.34.1 ({TODAY.isoformat()})\n"
            "- #590: Docs: fix the quick brown fox example ($0.50)\n"
            "Total: 1 PRs, $0.50\n"
        )
        merged = [_merged(592, "feat: add sample gadget", 1.00)]

        calls, _, _ = self._run(
            tmp_path,
            branch_block=branch_block,
            branch_version="0.34.1",
            merged=merged,
            fail_on=["merge"],
        )

        assert not any(c[:2] == ["git", "commit"] for c in calls)
        assert not any(c[:2] == ["git", "push"] for c in calls)
        assert calls[-1] == ["git", "checkout", "main"]

    def test_chore_prs_excluded(self, tmp_path: Path) -> None:
        branch_block = (
            f"## v0.34.1 ({TODAY.isoformat()})\n"
            "- #590: Docs: fix the quick brown fox example ($0.50)\n"
            "Total: 1 PRs, $0.50\n"
        )
        merged = [
            _merged(589, "chore: update changelog and version (v0.34.0)", 0.00),
            _merged(592, "fix: lazy dog filter", 0.30),
        ]

        calls, changelog, _ = self._run(
            tmp_path, branch_block=branch_block, branch_version="0.34.1", merged=merged
        )

        assert "#589" not in changelog.read_text()
        assert ["git", "commit", "-m", "chore: add #592 to v0.34.1 changelog"] in calls

    def test_lookback_starts_at_mains_latest_block(self, tmp_path: Path) -> None:
        calls, _, _ = self._run(
            tmp_path, branch_block="", branch_version="0.34.0", merged=[], open_prs=[]
        )
        merged_query = next(c for c in calls if c[:3] == ["gh", "pr", "list"] and "merged" in c)
        assert f"merged:>={YESTERDAY.isoformat()}" in merged_query

    def test_creates_new_pr_when_none_open(self, tmp_path: Path) -> None:
        merged = [_merged(592, "feat: add sample gadget", 1.00)]

        calls, changelog, pyproject = self._run(
            tmp_path, branch_block="", branch_version="0.34.0", merged=merged, open_prs=[]
        )

        stamp = TODAY.isoformat()
        assert ["git", "checkout", "-b", f"chore/changelog-{stamp}"] in calls
        assert ["git", "push", "-u", "origin", f"chore/changelog-{stamp}"] in calls
        assert any(c[:3] == ["gh", "pr", "create"] for c in calls)
        assert not any(c[:3] == ["gh", "pr", "edit"] for c in calls)
        assert not any(c[:2] == ["git", "fetch"] for c in calls)
        assert f"## v0.35.0 ({stamp})" in changelog.read_text()
        assert 'version = "0.35.0"' in pyproject.read_text()
