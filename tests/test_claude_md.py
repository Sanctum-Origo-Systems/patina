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


TRIGGER_SHAPE_MARKER = "anonymized reproduction of the live trigger shape"
MIRRORS = [REPO_ROOT / "AGENTS.md", REPO_ROOT / ".cursorrules"]
PR_TEMPLATE = REPO_ROOT / ".github" / "pull_request_template.md"


def _conventions_lines(path):
    lines = path.read_text().splitlines()
    start = lines.index("## Conventions")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return lines[start + 1 : end]


def _trigger_shape_rule(path):
    matches = [line for line in _conventions_lines(path) if TRIGGER_SHAPE_MARKER in line]
    assert len(matches) == 1, f"trigger-shape rule missing from {path.name} Conventions"
    return matches[0]


def test_trigger_shape_rule_in_claude_md_conventions():
    rule = _trigger_shape_rule(CLAUDE_MD)
    assert "production-derived defect issue" in rule
    assert "structure and field layout" in rule
    assert "punctuation and non-ASCII characters" in rule
    assert "fictitious content" in rule
    assert "a generic fixture alone does not satisfy the rule" in rule


def test_trigger_shape_rule_mirrored_identically():
    rule = _trigger_shape_rule(CLAUDE_MD)
    for path in MIRRORS:
        assert _trigger_shape_rule(path) == rule, f"{path.name} rule differs from CLAUDE.md"


def test_pr_template_has_trigger_shape_checklist_item():
    assert PR_TEMPLATE.exists()
    item = (
        "- [ ] If this fixes a production-derived defect, "
        "the anonymized live trigger shape is in the tests."
    )
    assert item in PR_TEMPLATE.read_text()
