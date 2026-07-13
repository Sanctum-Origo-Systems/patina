from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"


def test_claude_md_exists():
    assert CLAUDE_MD.exists()


def test_anonymization_rule_present():
    content = CLAUDE_MD.read_text()
    assert "No real message content or user data in GitHub issues" in content


def test_anonymization_rule_adjacent_to_names_rule():
    lines = CLAUDE_MD.read_text().splitlines()
    names_idx = None
    anon_idx = None
    for i, line in enumerate(lines):
        if "No real person or company names" in line:
            names_idx = i
        if "No real message content or user data" in line:
            anon_idx = i
    assert names_idx is not None, "names rule not found"
    assert anon_idx is not None, "anonymization rule not found"
    assert anon_idx == names_idx + 1, "anonymization rule should follow names rule"
