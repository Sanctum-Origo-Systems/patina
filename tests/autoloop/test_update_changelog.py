"""Tests for autoloop/update_changelog.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from autoloop.update_changelog import (
    append_entries,
    close_completed_parents,
    existing_entries,
    extract_cost,
    extract_issue_number,
    trim_changelog,
)

# --- extract_cost ---


def test_extract_cost_parses_dollar_amount():
    assert extract_cost("- Cost: $1.23") == 1.23


def test_extract_cost_returns_zero_when_missing():
    assert extract_cost("no cost here") == 0.0


def test_extract_cost_handles_empty():
    assert extract_cost("") == 0.0


# --- extract_issue_number ---


def test_extract_issue_number_finds_closes_ref():
    assert extract_issue_number("Closes #42") == 42


def test_extract_issue_number_returns_none_when_missing():
    assert extract_issue_number("no issue ref") is None


def test_extract_issue_number_handles_empty():
    assert extract_issue_number("") is None


# --- existing_entries ---


def test_existing_entries_empty_when_no_file(tmp_path):
    assert existing_entries(tmp_path) == set()


def test_existing_entries_reads_pr_numbers(tmp_path):
    d = tmp_path / "eval" / "cognitive"
    d.mkdir(parents=True)
    (d / "CHANGELOG.md").write_text(
        "# Cognitive Changelog\n\n## 2026-07-01\n- Fix bug (PR #10)\n- Add feature (PR #25)\n"
    )
    assert existing_entries(tmp_path) == {10, 25}


def test_existing_entries_ignores_non_pr_numbers(tmp_path):
    d = tmp_path / "eval" / "cognitive"
    d.mkdir(parents=True)
    (d / "CHANGELOG.md").write_text("Some text without PR references\n")
    assert existing_entries(tmp_path) == set()


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
    count = append_entries(_sample_prs(), tmp_path)
    assert count == 2
    changelog = tmp_path / "eval" / "cognitive" / "CHANGELOG.md"
    assert changelog.exists()
    text = changelog.read_text()
    assert "PR #42" in text
    assert "PR #43" in text


def test_append_entries_skips_known_prs(tmp_path):
    d = tmp_path / "eval" / "cognitive"
    d.mkdir(parents=True)
    (d / "CHANGELOG.md").write_text(
        "# Cognitive Changelog\n\n## 2026-07-01\n- Fix login bug (PR #42)\n"
    )
    count = append_entries(_sample_prs(), tmp_path)
    assert count == 1
    text = (d / "CHANGELOG.md").read_text()
    assert "PR #43" in text


def test_append_entries_returns_zero_when_all_known(tmp_path):
    d = tmp_path / "eval" / "cognitive"
    d.mkdir(parents=True)
    (d / "CHANGELOG.md").write_text(
        "# Cognitive Changelog\n\n## 2026-07-01\n"
        "- Fix login bug (PR #42)\n- Add dashboard (PR #43)\n"
    )
    assert append_entries(_sample_prs(), tmp_path) == 0


def test_append_entries_extracts_cost_and_issue(tmp_path):
    append_entries(_sample_prs(), tmp_path)
    text = (tmp_path / "eval" / "cognitive" / "CHANGELOG.md").read_text()
    assert "($1.23)" in text
    assert "#10" in text


def test_append_entries_creates_parent_dirs(tmp_path):
    append_entries(_sample_prs(), tmp_path)
    assert (tmp_path / "eval" / "cognitive" / "CHANGELOG.md").exists()


# --- trim_changelog ---


def test_trim_changelog_moves_old_entries_to_archive(tmp_path):
    d = tmp_path / "eval" / "cognitive"
    d.mkdir(parents=True)
    old_date = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")
    recent_date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    (d / "CHANGELOG.md").write_text(
        f"# Cognitive Changelog\n\n## {recent_date}\n- New item (PR #2)\n"
        f"\n## {old_date}\n- Old item (PR #1)\n"
    )
    trim_changelog(tmp_path)

    cl_text = (d / "CHANGELOG.md").read_text()
    assert "PR #2" in cl_text
    assert "PR #1" not in cl_text

    archive = d / "changelog-archive.md"
    assert archive.exists()
    assert "PR #1" in archive.read_text()


def test_trim_changelog_noop_when_no_file(tmp_path):
    trim_changelog(tmp_path)


def test_trim_changelog_preserves_recent_entries(tmp_path):
    d = tmp_path / "eval" / "cognitive"
    d.mkdir(parents=True)
    recent_date = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    (d / "CHANGELOG.md").write_text(
        f"# Cognitive Changelog\n\n## {recent_date}\n- Recent item (PR #5)\n"
    )
    trim_changelog(tmp_path)
    assert not (d / "changelog-archive.md").exists()
    assert "PR #5" in (d / "CHANGELOG.md").read_text()


def test_trim_changelog_appends_to_existing_archive(tmp_path):
    d = tmp_path / "eval" / "cognitive"
    d.mkdir(parents=True)
    old_date = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%d")
    (d / "CHANGELOG.md").write_text(f"# Cognitive Changelog\n\n## {old_date}\n- Old item (PR #3)\n")
    (d / "changelog-archive.md").write_text("- Ancient item (PR #1)\n")
    trim_changelog(tmp_path)

    ar_text = (d / "changelog-archive.md").read_text()
    assert "PR #3" in ar_text
    assert "PR #1" in ar_text


# --- close_completed_parents ---


def _make_run_result(returncode=0, stdout="[]"):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    return result


def _cfg(repo="acme-corp/widget"):
    return SimpleNamespace(repo=repo)


def test_close_completed_parents_closes_when_all_subs_closed():
    """Parent is closed when all discovered sub-issues have state CLOSED."""
    import json

    parents_json = json.dumps([{"number": 10}])
    subs_json = json.dumps(
        [
            {"number": 11, "body": "Parent issue: #10", "state": "CLOSED"},
            {"number": 12, "body": "Parent issue: #10", "state": "CLOSED"},
        ]
    )

    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        cmd_str = " ".join(cmd)
        if "issue" in cmd_str and "list" in cmd_str and "--label" in cmd_str:
            return _make_run_result(stdout=parents_json)
        if "issue" in cmd_str and "list" in cmd_str and "--search" in cmd_str:
            return _make_run_result(stdout=subs_json)
        return _make_run_result()

    with patch("autoloop.update_changelog.subprocess.run", side_effect=fake_run):
        close_completed_parents(_cfg())

    close_calls = [c for c in calls if "close" in c]
    assert len(close_calls) == 1
    assert "10" in close_calls[0]
    assert "Auto-closed: All 2 sub-issues complete." in close_calls[0]

    edit_calls = [c for c in calls if "edit" in c]
    assert len(edit_calls) == 1
    assert "--remove-label" in edit_calls[0]
    assert "needs-decomposition" in edit_calls[0]


def test_close_completed_parents_skips_when_sub_open():
    """Parent is NOT closed when any sub-issue is still open."""
    import json

    parents_json = json.dumps([{"number": 10}])
    subs_json = json.dumps(
        [
            {"number": 11, "body": "Parent issue: #10", "state": "CLOSED"},
            {"number": 12, "body": "Parent issue: #10", "state": "OPEN"},
        ]
    )

    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        cmd_str = " ".join(cmd)
        if "issue" in cmd_str and "list" in cmd_str and "--label" in cmd_str:
            return _make_run_result(stdout=parents_json)
        if "issue" in cmd_str and "list" in cmd_str and "--search" in cmd_str:
            return _make_run_result(stdout=subs_json)
        return _make_run_result()

    with patch("autoloop.update_changelog.subprocess.run", side_effect=fake_run):
        close_completed_parents(_cfg())

    close_calls = [c for c in calls if "close" in c]
    assert len(close_calls) == 0


def test_close_completed_parents_skips_when_no_subs_found():
    """Parent is NOT closed when no sub-issues reference it."""
    import json

    parents_json = json.dumps([{"number": 10}])
    subs_json = json.dumps([])

    def fake_run(cmd, **_kwargs):
        cmd_str = " ".join(cmd)
        if "issue" in cmd_str and "list" in cmd_str and "--label" in cmd_str:
            return _make_run_result(stdout=parents_json)
        if "issue" in cmd_str and "list" in cmd_str and "--search" in cmd_str:
            return _make_run_result(stdout=subs_json)
        return _make_run_result()

    calls = []

    def tracking_run(cmd, **kwargs):
        calls.append(list(cmd))
        return fake_run(cmd, **kwargs)

    with patch("autoloop.update_changelog.subprocess.run", side_effect=tracking_run):
        close_completed_parents(_cfg())

    close_calls = [c for c in calls if "close" in c]
    assert len(close_calls) == 0


def test_close_completed_parents_skips_unrelated_issues_in_search():
    """Issues returned by search but without matching body text are ignored."""
    import json

    parents_json = json.dumps([{"number": 10}])
    subs_json = json.dumps(
        [
            {"number": 11, "body": "Parent issue: #10", "state": "CLOSED"},
            {"number": 99, "body": "Unrelated issue body", "state": "OPEN"},
        ]
    )

    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        cmd_str = " ".join(cmd)
        if "issue" in cmd_str and "list" in cmd_str and "--label" in cmd_str:
            return _make_run_result(stdout=parents_json)
        if "issue" in cmd_str and "list" in cmd_str and "--search" in cmd_str:
            return _make_run_result(stdout=subs_json)
        return _make_run_result()

    with patch("autoloop.update_changelog.subprocess.run", side_effect=fake_run):
        close_completed_parents(_cfg())

    close_calls = [c for c in calls if "close" in c]
    assert len(close_calls) == 1
    assert "Auto-closed: All 1 sub-issues complete." in close_calls[0]


def test_close_completed_parents_returns_early_on_list_failure():
    """gh issue list failure causes early return, no crash."""
    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        return _make_run_result(returncode=1)

    with patch("autoloop.update_changelog.subprocess.run", side_effect=fake_run):
        close_completed_parents(_cfg())

    assert len(calls) == 1


def test_close_completed_parents_skips_parent_on_search_failure():
    """gh search failure for one parent skips it without crashing."""
    import json

    parents_json = json.dumps([{"number": 10}, {"number": 20}])
    subs_20_json = json.dumps([{"number": 21, "body": "Parent issue: #20", "state": "CLOSED"}])

    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        cmd_str = " ".join(cmd)
        if "issue" in cmd_str and "list" in cmd_str and "--label" in cmd_str:
            return _make_run_result(stdout=parents_json)
        if "issue" in cmd_str and "list" in cmd_str and "--search" in cmd_str:
            if "#10" in cmd_str:
                return _make_run_result(returncode=1)
            return _make_run_result(stdout=subs_20_json)
        return _make_run_result()

    with patch("autoloop.update_changelog.subprocess.run", side_effect=fake_run):
        close_completed_parents(_cfg())

    close_calls = [c for c in calls if "close" in c]
    assert len(close_calls) == 1
    assert "20" in close_calls[0]


def test_close_completed_parents_handles_multiple_parents():
    """Each parent is evaluated independently."""
    import json

    parents_json = json.dumps([{"number": 10}, {"number": 20}])
    subs_10_json = json.dumps([{"number": 11, "body": "Parent issue: #10", "state": "CLOSED"}])
    subs_20_json = json.dumps([{"number": 21, "body": "Parent issue: #20", "state": "OPEN"}])

    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        cmd_str = " ".join(cmd)
        if "issue" in cmd_str and "list" in cmd_str and "--label" in cmd_str:
            return _make_run_result(stdout=parents_json)
        if "issue" in cmd_str and "list" in cmd_str and "--search" in cmd_str:
            if "#10" in cmd_str:
                return _make_run_result(stdout=subs_10_json)
            return _make_run_result(stdout=subs_20_json)
        return _make_run_result()

    with patch("autoloop.update_changelog.subprocess.run", side_effect=fake_run):
        close_completed_parents(_cfg())

    close_calls = [c for c in calls if "close" in c]
    assert len(close_calls) == 1
    assert "10" in close_calls[0]

    edit_calls = [c for c in calls if "edit" in c]
    assert len(edit_calls) == 1
    assert "10" in edit_calls[0]


def test_close_completed_parents_uses_cfg_repo():
    """All gh calls include --repo with the configured repo."""
    import json

    parents_json = json.dumps([{"number": 5}])
    subs_json = json.dumps([{"number": 6, "body": "Parent issue: #5", "state": "CLOSED"}])

    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        cmd_str = " ".join(cmd)
        if "issue" in cmd_str and "list" in cmd_str and "--label" in cmd_str:
            return _make_run_result(stdout=parents_json)
        if "issue" in cmd_str and "list" in cmd_str and "--search" in cmd_str:
            return _make_run_result(stdout=subs_json)
        return _make_run_result()

    with patch("autoloop.update_changelog.subprocess.run", side_effect=fake_run):
        close_completed_parents(_cfg(repo="owner/other"))

    for c in calls:
        if "gh" in c:
            repo_indices = [i for i, arg in enumerate(c) if arg == "--repo"]
            assert len(repo_indices) == 1
            assert c[repo_indices[0] + 1] == "owner/other"


def test_close_completed_parents_handles_null_body():
    """Sub-issues with null body are filtered out, not crash."""
    import json

    parents_json = json.dumps([{"number": 10}])
    subs_json = json.dumps(
        [
            {"number": 11, "body": None, "state": "CLOSED"},
            {"number": 12, "body": "Parent issue: #10", "state": "CLOSED"},
        ]
    )

    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        cmd_str = " ".join(cmd)
        if "issue" in cmd_str and "list" in cmd_str and "--label" in cmd_str:
            return _make_run_result(stdout=parents_json)
        if "issue" in cmd_str and "list" in cmd_str and "--search" in cmd_str:
            return _make_run_result(stdout=subs_json)
        return _make_run_result()

    with patch("autoloop.update_changelog.subprocess.run", side_effect=fake_run):
        close_completed_parents(_cfg())

    close_calls = [c for c in calls if "close" in c]
    assert len(close_calls) == 1
    assert "Auto-closed: All 1 sub-issues complete." in close_calls[0]
