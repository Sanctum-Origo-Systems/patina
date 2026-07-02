from __future__ import annotations

import importlib
import json
import subprocess
from unittest.mock import patch

import create_issue
from create_issue import (
    DEFAULT_ACCEPTANCE,
    build_issue,
    build_issue_body,
    extract_files_from_spec,
    extract_problem_from_spec,
    get_rejection_reason,
    main,
    parse_issue_sections,
    parse_spec_enhancements,
    prompt_multiline,
    prompt_optional,
    prompt_required,
    suggest_fields,
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


# --- Pure function tests: parse_issue_sections ---


def test_parse_issue_sections_basic():
    body = "## Summary\nFix crash\n\n## Type\nbug\n\n## Expected Behavior\nNo crash"
    sections = parse_issue_sections(body)
    assert sections["Summary"] == "Fix crash"
    assert sections["Type"] == "bug"
    assert sections["Expected Behavior"] == "No crash"


def test_parse_issue_sections_multiline_content():
    body = "## Summary\nFix crash\n\n## Acceptance Criteria\n- [ ] Tests pass\n- [ ] Lint clean"
    sections = parse_issue_sections(body)
    assert "- [ ] Tests pass" in sections["Acceptance Criteria"]
    assert "- [ ] Lint clean" in sections["Acceptance Criteria"]


def test_parse_issue_sections_empty_body():
    assert parse_issue_sections("") == {}


# --- Pure function tests: get_rejection_reason ---


def test_get_rejection_reason_found():
    issue_data = {
        "comments": [
            {"body": "**Auto-triage — Rejected:** Expected Behavior is vague"},
        ],
    }
    assert get_rejection_reason(issue_data) == "Expected Behavior is vague"


def test_get_rejection_reason_not_found():
    issue_data = {"comments": [{"body": "Some other comment"}]}
    assert get_rejection_reason(issue_data) is None


def test_get_rejection_reason_no_comments():
    assert get_rejection_reason({"comments": []}) is None
    assert get_rejection_reason({}) is None


# --- Pure function tests: parse_spec_enhancements ---

SAMPLE_SPEC = """\
# My Spec

## Context

Some context here.

---

## Enhancement 1: Feed Errors Back

**Problem:** Errors are lost on retry.

**File:** `ai-dlc/implement_issue.py`

**Change:** Pass errors forward.

---

## Enhancement 2: Increase Timeout

**Problem:** Timeout too short.

**File:** `ai-dlc/implement_issue.py` and `ai-dlc/triage_issues.py`

**Change:** Make timeout configurable.

---

## Summary of Changes

| Enhancement | File |
|-------------|------|
"""


def test_parse_spec_enhancements_from_file(tmp_path):
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(SAMPLE_SPEC)
    enhancements = parse_spec_enhancements(str(spec_file))
    assert len(enhancements) == 2
    assert enhancements[0]["title"] == "Feed Errors Back"
    assert enhancements[1]["title"] == "Increase Timeout"
    assert "Errors are lost" in enhancements[0]["body"]
    assert "Timeout too short" in enhancements[1]["body"]


def test_parse_spec_enhancements_stops_at_summary(tmp_path):
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(SAMPLE_SPEC)
    enhancements = parse_spec_enhancements(str(spec_file))
    for enh in enhancements:
        assert "Summary of Changes" not in enh["body"]


def test_parse_spec_enhancements_empty_file(tmp_path):
    spec_file = tmp_path / "spec.md"
    spec_file.write_text("# No enhancements here\n\nJust text.")
    assert parse_spec_enhancements(str(spec_file)) == []


# --- Pure function tests: extract_files_from_spec ---


def test_extract_files_single():
    body = "**File:** `ai-dlc/implement_issue.py`"
    assert extract_files_from_spec(body) == ["ai-dlc/implement_issue.py"]


def test_extract_files_multiple_with_and():
    body = "**File:** `ai-dlc/implement_issue.py` and `ai-dlc/triage_issues.py`"
    assert extract_files_from_spec(body) == [
        "ai-dlc/implement_issue.py",
        "ai-dlc/triage_issues.py",
    ]


def test_extract_files_none():
    assert extract_files_from_spec("No files mentioned") == []


# --- Pure function tests: extract_problem_from_spec ---


def test_extract_problem():
    body = "**Problem:** Errors are lost on retry.\n\n**File:** `x.py`"
    assert extract_problem_from_spec(body) == "Errors are lost on retry."


def test_extract_problem_multiline():
    body = "**Problem:** Errors are lost.\nThis wastes retries.\n\n**Change:** Fix it."
    result = extract_problem_from_spec(body)
    assert "Errors are lost" in result
    assert "wastes retries" in result


def test_extract_problem_none():
    assert extract_problem_from_spec("No problem here") == ""


# --- Subprocess tests: suggest_fields ---


def test_suggest_fields_returns_parsed_json(monkeypatch):
    suggestion_json = json.dumps(
        {
            "files": ["src/patina/agent/runtime.py"],
            "current_behavior": "PROFILE.md not loaded",
            "expected_behavior": "PROFILE.md loaded into system prompt",
            "acceptance_criteria": ["system_prompt includes profile content"],
            "implementation_hints": "Mirror load_soul() pattern in config.py",
        }
    )

    class FakeResult:
        returncode = 0
        stdout = suggestion_json

    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/claude")
    with patch.object(create_issue.subprocess, "run", return_value=FakeResult()):
        result = suggest_fields("Fix profile loading", "bug")
    assert result is not None
    assert result["files"] == ["src/patina/agent/runtime.py"]
    assert "Mirror load_soul" in result["implementation_hints"]


def test_suggest_fields_returns_none_when_no_claude(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    assert suggest_fields("Fix something", "bug") is None


def test_suggest_fields_returns_none_on_bad_json(monkeypatch):
    class FakeResult:
        returncode = 0
        stdout = "not json at all"

    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/claude")
    with patch.object(create_issue.subprocess, "run", return_value=FakeResult()):
        assert suggest_fields("Fix something", "bug") is None


def test_suggest_fields_returns_none_on_timeout(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/claude")

    class FakeFind:
        returncode = 0
        stdout = "src/patina/store.py\n"

    call_count = 0

    def selective_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return FakeFind()
        raise subprocess.TimeoutExpired(cmd="claude", timeout=30)

    with patch.object(create_issue.subprocess, "run", side_effect=selective_run):
        assert suggest_fields("Fix something", "bug") is None


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
    monkeypatch.setattr(create_issue.shutil, "which", lambda cmd: None)
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
    monkeypatch.setattr(create_issue.shutil, "which", lambda cmd: None)
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
    monkeypatch.setattr(create_issue.shutil, "which", lambda cmd: None)
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
    monkeypatch.setattr(create_issue.shutil, "which", lambda cmd: None)
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
    monkeypatch.setattr(create_issue.shutil, "which", lambda cmd: None)
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
    monkeypatch.setattr(create_issue.shutil, "which", lambda cmd: None)
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
    monkeypatch.setattr(create_issue.shutil, "which", lambda cmd: None)
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


# --- TRIAGE_MODEL env var tests ---


def test_suggest_fields_uses_triage_model(monkeypatch):
    captured = {}
    call_count = [0]

    class FakeFind:
        returncode = 0
        stdout = "src/patina/store.py\n"

    class FakeClaude:
        returncode = 0
        stdout = json.dumps(
            {
                "files": ["src/patina/store.py"],
                "current_behavior": "",
                "expected_behavior": "works",
                "acceptance_criteria": [],
                "implementation_hints": "",
            }
        )

    def selective_run(cmd, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return FakeFind()
        captured["cmd"] = cmd
        return FakeClaude()

    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/claude")
    monkeypatch.setattr(create_issue, "TRIAGE_MODEL", "opus")
    with patch.object(create_issue.subprocess, "run", side_effect=selective_run):
        suggest_fields("Fix something", "bug")

    assert "--model" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == "opus"


def test_triage_model_default_from_env_create_issue(monkeypatch):
    monkeypatch.delenv("PATINA_AIDLC_TRIAGE_MODEL", raising=False)
    importlib.reload(create_issue)
    assert create_issue.TRIAGE_MODEL == "sonnet"


def test_triage_model_override_from_env_create_issue(monkeypatch):
    monkeypatch.setenv("PATINA_AIDLC_TRIAGE_MODEL", "haiku")
    importlib.reload(create_issue)
    assert create_issue.TRIAGE_MODEL == "haiku"
