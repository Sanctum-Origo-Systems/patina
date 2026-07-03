from __future__ import annotations

import re
from unittest.mock import MagicMock

from auto_close_parent import (
    all_siblings_closed,
    close_parent_with_comment,
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
