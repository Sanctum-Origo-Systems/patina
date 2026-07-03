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
        result = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                self.repo,
                "--state",
                "open",
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


def all_siblings_closed(gh: GhClient, parent_num: int) -> bool:
    """Return True only when no open issue references ``Parent issue: #parent_num``."""
    for issue in gh.list_open_issues():
        if parse_parent_ref(issue.get("body", "") or "") == parent_num:
            return False
    return True


def close_parent_with_comment(gh: GhClient, parent_num: int, sibling_count: int) -> None:
    """Close the parent issue and post an auto-close summary comment."""
    gh.close_issue(parent_num)
    gh.comment_issue(
        parent_num,
        f"Auto-closed: All {sibling_count} sub-issues are now complete.",
    )
