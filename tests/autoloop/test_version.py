from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

REPO_DIR = Path(__file__).resolve().parent.parent.parent


def _read_version() -> str:
    with open(REPO_DIR / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def test_triage_issues_version_flag(capsys):
    from autoloop.triage_issues import main

    with patch.object(sys, "argv", ["triage_issues.py", "--version"]):
        try:
            main()
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("patina ")
    assert _read_version() in captured.out


def test_implement_issue_version_flag(capsys):
    import autoloop.implement_issue as mod

    with patch.object(sys, "argv", ["implement_issue.py", "--version"]):
        try:
            mod.main()
        except SystemExit as e:
            assert e.code == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("patina ")
    assert _read_version() in captured.out
