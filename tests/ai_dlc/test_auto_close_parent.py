from __future__ import annotations

import re
from unittest.mock import MagicMock

from auto_close_parent import (
    all_siblings_closed,
    check_and_close_parent,
    close_parent_with_comment,
    count_subissues,
    parse_closes_ref,
    parse_parent_ref,
)

# --- parse_parent_ref ---


def test_parse_parent_ref_valid():
    assert parse_parent_ref("Some text\nParent issue: #42\nmore text") == 42


def test_parse_parent_ref_missing_pattern():
    assert parse_parent_ref("This body has no parent reference at all.") is None


def test_parse_parent_ref_empty_body():
    assert parse_parent_ref("") is None


def test_parse_parent_ref_malformed():
    # No number after the hash — not a valid reference.
    assert parse_parent_ref("Parent issue: #") is None
    # Missing the hash entirely.
    assert parse_parent_ref("Parent issue: 42") is None


# --- all_siblings_closed ---


def _gh_with_open_issues(issues: list[dict]) -> MagicMock:
    gh = MagicMock()
    gh.list_open_issues.return_value = issues
    return gh


def test_all_siblings_closed_zero_open_siblings():
    # No open issues reference the parent → all siblings closed.
    gh = _gh_with_open_issues([{"number": 7, "body": "Unrelated open issue"}])
    assert all_siblings_closed(gh, 55) is True


def test_all_siblings_closed_one_open_sibling():
    gh = _gh_with_open_issues([{"number": 56, "body": "Parent issue: #55"}])
    assert all_siblings_closed(gh, 55) is False


def test_all_siblings_closed_multiple_open_siblings():
    gh = _gh_with_open_issues(
        [
            {"number": 56, "body": "Parent issue: #55"},
            {"number": 57, "body": "Parent issue: #55"},
            {"number": 99, "body": "Parent issue: #12"},
        ]
    )
    assert all_siblings_closed(gh, 55) is False


def test_all_siblings_closed_ignores_other_parents():
    # Only open siblings belong to a different parent.
    gh = _gh_with_open_issues([{"number": 99, "body": "Parent issue: #12"}])
    assert all_siblings_closed(gh, 55) is True


def test_all_siblings_closed_empty_repo():
    gh = _gh_with_open_issues([])
    assert all_siblings_closed(gh, 55) is True


# --- close_parent_with_comment ---


def test_close_parent_with_comment_invokes_both_calls():
    gh = MagicMock()
    close_parent_with_comment(gh, 55, 3)

    gh.close_issue.assert_called_once_with(55)
    gh.comment_issue.assert_called_once()

    (num, body), _ = gh.comment_issue.call_args
    assert num == 55
    assert re.search(r"Auto-closed: All \d+ sub-issues are now complete\.", body)
    assert "3" in body


# --- parse_closes_ref ---


def test_parse_closes_ref_valid():
    assert parse_closes_ref("This PR does stuff.\nCloses #57") == 57


def test_parse_closes_ref_missing_pattern():
    assert parse_closes_ref("No linked issue in this body.") is None


def test_parse_closes_ref_empty_body():
    assert parse_closes_ref("") is None


def test_parse_closes_ref_malformed():
    assert parse_closes_ref("Closes #") is None
    assert parse_closes_ref("Closes 57") is None


# --- count_subissues ---


def test_count_subissues_counts_matching_parents():
    gh = MagicMock()
    gh.list_all_issues.return_value = [
        {"number": 56, "body": "Parent issue: #55"},
        {"number": 57, "body": "Parent issue: #55"},
        {"number": 99, "body": "Parent issue: #12"},
        {"number": 7, "body": "Unrelated"},
    ]
    assert count_subissues(gh, 55) == 2


def test_count_subissues_none_match():
    gh = MagicMock()
    gh.list_all_issues.return_value = [{"number": 7, "body": "Unrelated"}]
    assert count_subissues(gh, 55) == 0


# --- check_and_close_parent ---


def _orchestration_gh(
    pr_body: str, issue_body: str, open_issues: list[dict], all_issues: list[dict]
) -> MagicMock:
    gh = MagicMock()
    gh.get_pr_body.return_value = pr_body
    gh.get_issue_body.return_value = issue_body
    gh.list_open_issues.return_value = open_issues
    gh.list_all_issues.return_value = all_issues
    return gh


def test_check_and_close_parent_closes_when_last_sibling():
    all_issues = [
        {"number": 56, "body": "Parent issue: #55"},
        {"number": 57, "body": "Parent issue: #55"},
    ]
    gh = _orchestration_gh(
        pr_body="Closes #57",
        issue_body="Parent issue: #55",
        open_issues=[],
        all_issues=all_issues,
    )

    assert check_and_close_parent(42, gh) == 55
    gh.close_issue.assert_called_once_with(55)
    (num, body), _ = gh.comment_issue.call_args
    assert num == 55
    assert "All 2 sub-issues are now complete." in body


def test_check_and_close_parent_skips_when_sibling_open():
    gh = _orchestration_gh(
        pr_body="Closes #57",
        issue_body="Parent issue: #55",
        open_issues=[{"number": 56, "body": "Parent issue: #55"}],
        all_issues=[],
    )

    assert check_and_close_parent(42, gh) is None
    gh.close_issue.assert_not_called()
    gh.comment_issue.assert_not_called()


def test_check_and_close_parent_skips_when_no_parent_ref():
    gh = _orchestration_gh(
        pr_body="Closes #57",
        issue_body="A sub-issue with no parent reference.",
        open_issues=[],
        all_issues=[],
    )

    assert check_and_close_parent(42, gh) is None
    gh.close_issue.assert_not_called()
    gh.comment_issue.assert_not_called()


def test_check_and_close_parent_skips_when_no_closes_ref():
    gh = _orchestration_gh(
        pr_body="This PR has no Closes reference.",
        issue_body="",
        open_issues=[],
        all_issues=[],
    )

    assert check_and_close_parent(42, gh) is None
    gh.get_issue_body.assert_not_called()
    gh.close_issue.assert_not_called()
    gh.comment_issue.assert_not_called()
