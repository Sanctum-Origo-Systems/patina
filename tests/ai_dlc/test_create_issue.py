from __future__ import annotations

from unittest.mock import patch

import create_issue
from create_issue import (
    DEFAULT_ACCEPTANCE,
    build_issue,
    build_issue_body,
    main,
    prompt_multiline,
    prompt_optional,
    prompt_required,
)

# --- Pure function tests: build_issue_body ---


def test_build_issue_body_feature_all_sections():
    body = build_issue_body(
        summary="Add verbose flag",
        issue_type="feature",
        files="src/patina/cli.py",
        current_behavior="",
        expected="Prints one line per message",
        extra_criteria="CLI shows output",
        hints="Follow --dry-run pattern",
        deps="Depends on #43",
        context="See issue #40",
    )
    assert "## Summary\nAdd verbose flag" in body
    assert "## Type\nfeature" in body
    assert "## Files to Modify\n- src/patina/cli.py" in body
    assert "## Expected Behavior\nPrints one line per message" in body
    assert "## Acceptance Criteria" in body
    assert "## Implementation Hints\nFollow --dry-run pattern" in body
    assert "## Dependencies\nDepends on #43" in body
    assert "## Context\nSee issue #40" in body
    assert "## Story Points" in body


def test_build_issue_body_bug_includes_current_behavior():
    body = build_issue_body(
        summary="Fix crash",
        issue_type="bug",
        files="",
        current_behavior="It crashes on ingest",
        expected="No crash",
        extra_criteria="",
        hints="",
        deps="",
        context="",
    )
    assert "## Current Behavior\nIt crashes on ingest" in body


def test_build_issue_body_feature_omits_current_behavior():
    body = build_issue_body(
        summary="Add flag",
        issue_type="feature",
        files="",
        current_behavior="",
        expected="Flag works",
        extra_criteria="",
        hints="",
        deps="",
        context="",
    )
    assert "## Current Behavior" not in body


def test_build_issue_body_blank_files_shows_unknown():
    body = build_issue_body(
        summary="X",
        issue_type="feature",
        files="",
        current_behavior="",
        expected="Y",
        extra_criteria="",
        hints="",
        deps="",
        context="",
    )
    assert "## Files to Modify\nUnknown" in body


def test_build_issue_body_always_includes_default_acceptance():
    body = build_issue_body(
        summary="X",
        issue_type="feature",
        files="",
        current_behavior="",
        expected="Y",
        extra_criteria="",
        hints="",
        deps="",
        context="",
    )
    for criterion in DEFAULT_ACCEPTANCE:
        assert f"- [ ] {criterion}" in body


def test_build_issue_body_extra_criteria_appended():
    body = build_issue_body(
        summary="X",
        issue_type="feature",
        files="",
        current_behavior="",
        expected="Y",
        extra_criteria="API returns 200\nLatency < 100ms",
        hints="",
        deps="",
        context="",
    )
    assert "- [ ] API returns 200" in body
    assert "- [ ] Latency < 100ms" in body
    for criterion in DEFAULT_ACCEPTANCE:
        assert f"- [ ] {criterion}" in body


def test_build_issue_body_optional_sections_omitted_when_empty():
    body = build_issue_body(
        summary="X",
        issue_type="feature",
        files="",
        current_behavior="",
        expected="Y",
        extra_criteria="",
        hints="",
        deps="",
        context="",
    )
    assert "## Implementation Hints" not in body
    assert "## Dependencies" not in body
    assert "## Context" not in body


def test_build_issue_body_story_points_always_blank():
    body = build_issue_body(
        summary="X",
        issue_type="feature",
        files="",
        current_behavior="",
        expected="Y",
        extra_criteria="",
        hints="",
        deps="",
        context="",
    )
    assert "## Story Points\n<!-- Triage bot will estimate -->" in body


# --- I/O tests: prompt functions ---


def test_prompt_required_rejects_empty_then_accepts(monkeypatch):
    inputs = iter(["", "  ", "actual value"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    result = prompt_required("Summary")
    assert result == "actual value"


def test_prompt_optional_returns_empty_on_enter(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    result = prompt_optional("Hints", "optional")
    assert result == ""


def test_prompt_optional_returns_value(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "some hint")
    result = prompt_optional("Hints")
    assert result == "some hint"


def test_prompt_multiline_collects_until_blank(monkeypatch):
    inputs = iter(["line one", "line two", ""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    result = prompt_multiline("Files")
    assert result == "line one\nline two"


def test_prompt_multiline_empty_immediately(monkeypatch):
    inputs = iter([""])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    result = prompt_multiline("Files")
    assert result == ""


# --- I/O tests: build_issue ---


def test_build_issue_feature_happy_path(monkeypatch):
    inputs = iter(
        [
            "Add verbose flag",
            "feature",
            "src/patina/cli.py",
            "",
            "Prints one line per message",
            "",
            "",
            "",
            "",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    title, body = build_issue()
    assert title == "Add verbose flag"
    assert "## Type\nfeature" in body


def test_build_issue_type_from_arg_skips_prompt(monkeypatch):
    inputs = iter(
        [
            "Refactor extraction",
            "",
            "Cleaner code",
            "",
            "",
            "",
            "",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    title, body = build_issue(issue_type="refactor")
    assert title == "Refactor extraction"
    assert "## Type\nrefactor" in body


def test_build_issue_bug_prompts_current_behavior(monkeypatch):
    inputs = iter(
        [
            "Fix crash on ingest",
            "bug",
            "",
            "It crashes with IndexError",
            "",
            "No crash",
            "",
            "",
            "",
            "",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    title, body = build_issue()
    assert "## Current Behavior\nIt crashes with IndexError" in body


def test_build_issue_rejects_invalid_type_then_accepts(monkeypatch):
    inputs = iter(
        [
            "Something",
            "invalid",
            "also_bad",
            "feature",
            "",
            "It works",
            "",
            "",
            "",
            "",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    _, body = build_issue()
    assert "## Type\nfeature" in body


# --- Subprocess tests: main ---


def test_main_dry_run_prints_markdown(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["create_issue.py", "--dry-run", "--type", "feature"])
    inputs = iter(
        [
            "Add a flag",
            "",
            "Flag works",
            "",
            "",
            "",
            "",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))
    main()
    captured = capsys.readouterr()
    assert "--- Issue Markdown ---" in captured.out
    assert "**Title:** Add a flag" in captured.out
    assert "## Type\nfeature" in captured.out


def test_main_submits_via_gh(monkeypatch):
    monkeypatch.setattr("sys.argv", ["create_issue.py", "--type", "feature"])
    inputs = iter(
        [
            "Add a flag",
            "",
            "Flag works",
            "",
            "",
            "",
            "",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    class FakeResult:
        returncode = 0

    with patch.object(create_issue.subprocess, "run", return_value=FakeResult()) as mock_run:
        main()
    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "gh"
    assert "issue" in call_args
    assert "create" in call_args


def test_main_gh_failure_exits_1(monkeypatch):
    monkeypatch.setattr("sys.argv", ["create_issue.py", "--type", "feature"])
    inputs = iter(
        [
            "Add a flag",
            "",
            "Flag works",
            "",
            "",
            "",
            "",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda prompt="": next(inputs))

    class FakeResult:
        returncode = 1

    import pytest

    with patch.object(create_issue.subprocess, "run", return_value=FakeResult()):
        with pytest.raises(SystemExit, match="1"):
            main()
