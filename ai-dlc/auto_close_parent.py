#!/usr/bin/env python3
"""Auto-close a parent issue once all of its sub-issues are complete.

Sub-issues carry a ``Parent issue: #N`` reference in their body. When the last
open sub-issue of a parent is closed, the parent can be closed automatically
with a summary comment. This module exposes the GitHub API helpers that the
cleanup workflow invokes.
"""

from __future__ import annotations

import json
import re
import subprocess

REPO = "Sanctum-Origo-Systems/patina"


class GhClient:
    """Thin wrapper over the ``gh`` CLI for issue lookup, close, and comment."""

    def __init__(self, repo: str = REPO) -> None:
        self.repo = repo

    def list_open_issues(self) -> list[dict]:
        """Return all open issues as dicts with ``number`` and ``body``."""
        return self._list_issues("open")

    def list_all_issues(self) -> list[dict]:
        """Return all issues (open and closed) as dicts with ``number`` and ``body``."""
        return self._list_issues("all")

    def _list_issues(self, state: str) -> list[dict]:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                self.repo,
                "--state",
                state,
                "--json",
                "number,body",
                "--limit",
                "100",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []
        return json.loads(result.stdout)

    def get_issue_body(self, number: int) -> str:
        """Return the body of the given issue, or an empty string on failure."""
        result = subprocess.run(
            [
                "gh",
                "issue",
                "view",
                str(number),
                "--repo",
                self.repo,
                "--json",
                "body",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ""
        return json.loads(result.stdout).get("body", "") or ""

    def get_pr_body(self, number: int) -> str:
        """Return the body of the given pull request, or an empty string on failure."""
        result = subprocess.run(
            [
                "gh",
                "pr",
                "view",
                str(number),
                "--repo",
                self.repo,
                "--json",
                "body",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return ""
        return json.loads(result.stdout).get("body", "") or ""

    def close_issue(self, number: int) -> None:
        """Set the given issue's state to closed."""
        subprocess.run(
            ["gh", "issue", "close", str(number), "--repo", self.repo],
            capture_output=True,
            text=True,
        )

    def comment_issue(self, number: int, body: str) -> None:
        """Post a comment on the given issue."""
        subprocess.run(
            ["gh", "issue", "comment", str(number), "--repo", self.repo, "--body", body],
            capture_output=True,
            text=True,
        )


def parse_parent_ref(body: str) -> int | None:
    """Extract the parent issue number from a ``Parent issue: #N`` reference.

    Returns the integer number, or None if the body has no such reference.
    """
    if not body:
        return None
    match = re.search(r"Parent issue: #(\d+)", body)
    return int(match.group(1)) if match else None


def parse_closes_ref(body: str) -> int | None:
    """Extract the issue number from a ``Closes #N`` reference in a PR body.

    Returns the integer number, or None if the body has no such reference.
    """
    if not body:
        return None
    match = re.search(r"Closes #(\d+)", body)
    return int(match.group(1)) if match else None


def all_siblings_closed(gh: GhClient, parent_num: int) -> bool:
    """Return True only when no open issue references ``Parent issue: #parent_num``."""
    for issue in gh.list_open_issues():
        if parse_parent_ref(issue.get("body", "") or "") == parent_num:
            return False
    return True


def count_subissues(gh: GhClient, parent_num: int) -> int:
    """Return the total number of issues referencing ``Parent issue: #parent_num``."""
    return sum(
        1
        for issue in gh.list_all_issues()
        if parse_parent_ref(issue.get("body", "") or "") == parent_num
    )


def close_parent_with_comment(gh: GhClient, parent_num: int, sibling_count: int) -> None:
    """Close the parent issue and post an auto-close summary comment."""
    gh.close_issue(parent_num)
    gh.comment_issue(
        parent_num,
        f"Auto-closed: All {sibling_count} sub-issues are now complete.",
    )


def check_and_close_parent(pr_number: int, gh: GhClient | None = None) -> int | None:
    """Close a parent issue when a merged PR completes its last open sub-issue.

    Reads the merged PR body for ``Closes #N``, looks up issue N's body for a
    ``Parent issue: #P`` reference, and — only when no sibling sub-issue of P
    remains open — closes P with an auto-close summary comment.

    Returns the closed parent number, or None when nothing was modified (no
    ``Closes`` ref, no parent ref, or a sibling is still open).
    """
    gh = gh or GhClient()

    closed_issue = parse_closes_ref(gh.get_pr_body(pr_number))
    if closed_issue is None:
        return None

    parent_num = parse_parent_ref(gh.get_issue_body(closed_issue))
    if parent_num is None:
        return None

    if not all_siblings_closed(gh, parent_num):
        return None

    close_parent_with_comment(gh, parent_num, count_subissues(gh, parent_num))
    return parent_num


if __name__ == "__main__":
    import sys

    check_and_close_parent(int(sys.argv[1]))
