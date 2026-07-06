from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from version import get_version

REPO_DIR = Path(__file__).resolve().parent.parent.parent
AIDLC_DIR = REPO_DIR / "ai-dlc"


def test_get_version_returns_string():
    version = get_version()
    assert isinstance(version, str)
    assert len(version) > 0


def test_get_version_matches_pyproject():
    import tomllib

    with open(REPO_DIR / "pyproject.toml", "rb") as f:
        data = tomllib.load(f)
    assert get_version() == data["project"]["version"]


def test_create_issue_version_flag(capsys):
    import create_issue

    with patch.object(sys, "argv", ["create_issue.py", "--version"]):
        try:
            create_issue.main()
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("patina ")
    assert get_version() in captured.out


def test_triage_issues_version_flag(capsys):
    import triage_issues

    with patch.object(sys, "argv", ["triage_issues.py", "--version"]):
        try:
            triage_issues.main()
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("patina ")
    assert get_version() in captured.out


def test_implement_issue_version_flag(capsys):
    import implement_issue

    with patch.object(sys, "argv", ["implement_issue.py", "--version"]):
        try:
            implement_issue.main()
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("patina ")
    assert get_version() in captured.out
