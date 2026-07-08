"""Tests for ai-dlc/update_changelog.py ChangelogCfg and parameterized functions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from update_changelog import (
    ChangelogCfg,
    append_entries,
    commit_and_create_pr,
    existing_entries,
    trim_changelog,
)


def _make_cfg(tmp_path):
    return ChangelogCfg(repo="test-org/test-repo", repo_dir=tmp_path)


def _changelog_dir(tmp_path):
    d = tmp_path / "eval" / "cognitive"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- existing_entries ---


def test_existing_entries_empty_when_no_file(tmp_path):
    cfg = _make_cfg(tmp_path)
    assert existing_entries(cfg) == set()


def test_existing_entries_reads_pr_numbers(tmp_path):
    d = _changelog_dir(tmp_path)
    (d / "CHANGELOG.md").write_text(
        "# Cognitive Changelog\n\n## 2026-07-01\n- Fix bug (PR #10)\n- Add feature (PR #25)\n"
    )
    cfg = _make_cfg(tmp_path)
    assert existing_entries(cfg) == {10, 25}


def test_existing_entries_ignores_non_pr_numbers(tmp_path):
    d = _changelog_dir(tmp_path)
    (d / "CHANGELOG.md").write_text("Some text without PR references\n")
    cfg = _make_cfg(tmp_path)
    assert existing_entries(cfg) == set()


# --- append_entries ---


def _sample_prs():
    return [
        {
            "number": 42,
            "title": "Fix login bug",
            "mergedAt": "2026-07-01T12:00:00Z",
            "body": "Closes #10\n- Cost: $1.23",
        },
        {
            "number": 43,
            "title": "Add dashboard",
            "mergedAt": "2026-07-02T08:00:00Z",
            "body": "",
        },
    ]


def test_append_entries_creates_changelog(tmp_path):
    cfg = _make_cfg(tmp_path)
    count = append_entries(_sample_prs(), cfg)
    assert count == 2
    changelog = tmp_path / "eval" / "cognitive" / "CHANGELOG.md"
    assert changelog.exists()
    text = changelog.read_text()
    assert "PR #42" in text
    assert "PR #43" in text


def test_append_entries_skips_known_prs(tmp_path):
    d = _changelog_dir(tmp_path)
    (d / "CHANGELOG.md").write_text(
        "# Cognitive Changelog\n\n## 2026-07-01\n- Fix login bug (PR #42)\n"
    )
    cfg = _make_cfg(tmp_path)
    count = append_entries(_sample_prs(), cfg)
    assert count == 1
    text = (d / "CHANGELOG.md").read_text()
    assert "PR #43" in text


def test_append_entries_returns_zero_when_all_known(tmp_path):
    d = _changelog_dir(tmp_path)
    (d / "CHANGELOG.md").write_text(
        "# Cognitive Changelog\n\n## 2026-07-01\n"
        "- Fix login bug (PR #42)\n- Add dashboard (PR #43)\n"
    )
    cfg = _make_cfg(tmp_path)
    assert append_entries(_sample_prs(), cfg) == 0


def test_append_entries_extracts_cost_and_issue(tmp_path):
    cfg = _make_cfg(tmp_path)
    append_entries(_sample_prs(), cfg)
    text = (tmp_path / "eval" / "cognitive" / "CHANGELOG.md").read_text()
    assert "($1.23)" in text
    assert "#10" in text


def test_append_entries_creates_parent_dirs(tmp_path):
    cfg = _make_cfg(tmp_path)
    append_entries(_sample_prs(), cfg)
    assert (tmp_path / "eval" / "cognitive" / "CHANGELOG.md").exists()


# --- trim_changelog ---


def test_trim_changelog_moves_old_entries_to_archive(tmp_path):
    d = _changelog_dir(tmp_path)
    old_date = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")
    recent_date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    (d / "CHANGELOG.md").write_text(
        f"# Cognitive Changelog\n\n## {recent_date}\n- New item (PR #2)\n"
        f"\n## {old_date}\n- Old item (PR #1)\n"
    )
    cfg = _make_cfg(tmp_path)
    trim_changelog(cfg)

    cl_text = (d / "CHANGELOG.md").read_text()
    assert "PR #2" in cl_text
    assert "PR #1" not in cl_text

    archive = d / "changelog-archive.md"
    assert archive.exists()
    ar_text = archive.read_text()
    assert "PR #1" in ar_text


def test_trim_changelog_noop_when_no_file(tmp_path):
    cfg = _make_cfg(tmp_path)
    trim_changelog(cfg)


def test_trim_changelog_preserves_recent_entries(tmp_path):
    d = _changelog_dir(tmp_path)
    recent_date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    (d / "CHANGELOG.md").write_text(
        f"# Cognitive Changelog\n\n## {recent_date}\n- Recent item (PR #5)\n"
    )
    cfg = _make_cfg(tmp_path)
    trim_changelog(cfg)
    assert not (d / "changelog-archive.md").exists()
    assert "PR #5" in (d / "CHANGELOG.md").read_text()


def test_trim_changelog_appends_to_existing_archive(tmp_path):
    d = _changelog_dir(tmp_path)
    old_date = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")
    (d / "CHANGELOG.md").write_text(f"# Cognitive Changelog\n\n## {old_date}\n- Old item (PR #3)\n")
    (d / "changelog-archive.md").write_text("- Ancient item (PR #1)\n")
    cfg = _make_cfg(tmp_path)
    trim_changelog(cfg)

    ar_text = (d / "changelog-archive.md").read_text()
    assert "PR #3" in ar_text
    assert "PR #1" in ar_text


# --- commit_and_create_pr / --assignee ---


def _setup_staged_changelog(tmp_path):
    """Create a changelog file with staged changes so commit_and_create_pr proceeds."""
    d = _changelog_dir(tmp_path)
    (d / "CHANGELOG.md").write_text("# Cognitive Changelog\n\n## 2026-07-01\n- Item (PR #1)\n")
    return d


def _mock_subprocess_run(calls):
    """Return a side_effect that records calls and fakes subprocess responses."""

    def side_effect(cmd, **kwargs):
        calls.append(cmd)

        class Result:
            returncode = 0
            stdout = ""

        if cmd[:3] == ["git", "diff", "--cached"]:
            Result.returncode = 1
        if cmd[:3] == ["git", "branch", "--list"]:
            Result.stdout = ""
        return Result()

    return side_effect


def test_commit_and_create_pr_includes_assignee_when_set(tmp_path):
    _setup_staged_changelog(tmp_path)
    cfg = ChangelogCfg(repo="test-org/test-repo", repo_dir=tmp_path, pr_reviewer="alice")
    calls = []
    with patch("update_changelog.subprocess.run", side_effect=_mock_subprocess_run(calls)):
        commit_and_create_pr(cfg)

    gh_pr_calls = [c for c in calls if c[:3] == ["gh", "pr", "create"]]
    assert len(gh_pr_calls) == 1
    gh_cmd = gh_pr_calls[0]
    assert "--assignee" in gh_cmd
    assignee_idx = gh_cmd.index("--assignee")
    assert gh_cmd[assignee_idx + 1] == "alice"


def test_commit_and_create_pr_omits_assignee_when_empty(tmp_path):
    _setup_staged_changelog(tmp_path)
    cfg = ChangelogCfg(repo="test-org/test-repo", repo_dir=tmp_path, pr_reviewer="")
    calls = []
    with patch("update_changelog.subprocess.run", side_effect=_mock_subprocess_run(calls)):
        commit_and_create_pr(cfg)

    gh_pr_calls = [c for c in calls if c[:3] == ["gh", "pr", "create"]]
    assert len(gh_pr_calls) == 1
    assert "--assignee" not in gh_pr_calls[0]
