from __future__ import annotations

import os

import implement_issue
from implement_issue import (
    acquire_lock,
    build_branch_name,
    build_pr_body,
    collect_verification_errors,
    detect_issue_type,
    parse_dependency_numbers,
    release_lock,
)

# --- Pure function tests: parse_dependency_numbers ---


def test_parse_deps_single():
    assert parse_dependency_numbers("Depends on: #43") == ["43"]


def test_parse_deps_multiple():
    body = "Depends on: #43\nDepends on #44\nDepends on: #45"
    assert parse_dependency_numbers(body) == ["43", "44", "45"]


def test_parse_deps_none():
    assert parse_dependency_numbers("No dependencies here") == []


def test_parse_deps_case_insensitive():
    assert parse_dependency_numbers("depends on: #10") == ["10"]
    assert parse_dependency_numbers("DEPENDS ON: #20") == ["20"]


# --- Pure function tests: build_branch_name ---


def test_build_branch_name_basic():
    issue = {"number": 42, "title": "Add verbose flag"}
    assert build_branch_name(issue) == "ai-dlc/42-add-verbose-flag"


def test_build_branch_name_strips_special_chars():
    issue = {"number": 7, "title": "Fix: (crash) on ingest!"}
    name = build_branch_name(issue)
    assert name.startswith("ai-dlc/7-")
    assert "(" not in name
    assert "!" not in name
    assert ":" not in name


def test_build_branch_name_truncates_long_title():
    issue = {"number": 1, "title": "A" * 100}
    name = build_branch_name(issue)
    slug = name.split("/", 1)[1].split("-", 1)[1]
    assert len(slug) <= 50


# --- Pure function tests: detect_issue_type ---


def test_detect_issue_type_bug():
    assert detect_issue_type("## Summary\nFix\n\n## Type\nbug") == "fix"


def test_detect_issue_type_feature():
    assert detect_issue_type("## Summary\nAdd\n\n## Type\nfeature") == "feat"


def test_detect_issue_type_refactor():
    assert detect_issue_type("## Summary\nClean\n\n## Type\nrefactor") == "refactor"


def test_detect_issue_type_default_feat():
    assert detect_issue_type("no type section here") == "feat"


def test_detect_issue_type_empty():
    assert detect_issue_type("") == "feat"


# --- Pure function tests: build_pr_body ---


def test_build_pr_body_includes_closes():
    issue = {"number": 42, "title": "Add flag"}
    body = build_pr_body(issue)
    assert "Closes #42" in body
    assert "## Summary" in body
    assert "Add flag" in body
    assert "Automated implementation by Patina AI-DLC" in body


# --- Pure function tests: collect_verification_errors ---


def test_verification_no_errors():
    errors = collect_verification_errors(
        ahead_count="3",
        test_rc=0,
        test_out="",
        eval_rc=0,
        eval_out="",
        lint_rc=0,
        fmt_rc=0,
        changed_files=["tests/test_new.py", "src/x.py"],
    )
    assert errors == []


def test_verification_no_commits():
    errors = collect_verification_errors(
        ahead_count="0",
        test_rc=0,
        test_out="",
        eval_rc=0,
        eval_out="",
        lint_rc=0,
        fmt_rc=0,
        changed_files=["tests/test_new.py"],
    )
    assert "No commits on branch" in errors


def test_verification_empty_ahead():
    errors = collect_verification_errors(
        ahead_count="",
        test_rc=0,
        test_out="",
        eval_rc=0,
        eval_out="",
        lint_rc=0,
        fmt_rc=0,
        changed_files=["tests/test_new.py"],
    )
    assert "No commits on branch" in errors


def test_verification_tests_failed():
    errors = collect_verification_errors(
        ahead_count="1",
        test_rc=1,
        test_out="FAILED test_x",
        eval_rc=0,
        eval_out="",
        lint_rc=0,
        fmt_rc=0,
        changed_files=["tests/test_x.py"],
    )
    assert any("Tests failed" in e for e in errors)


def test_verification_eval_failed():
    errors = collect_verification_errors(
        ahead_count="1",
        test_rc=0,
        test_out="",
        eval_rc=1,
        eval_out="FAILED eval",
        lint_rc=0,
        fmt_rc=0,
        changed_files=["tests/test_x.py"],
    )
    assert any("Eval tests failed" in e for e in errors)


def test_verification_lint_failed():
    errors = collect_verification_errors(
        ahead_count="1",
        test_rc=0,
        test_out="",
        eval_rc=0,
        eval_out="",
        lint_rc=1,
        fmt_rc=0,
        changed_files=["tests/test_x.py"],
    )
    assert "Lint or format check failed" in errors


def test_verification_fmt_failed():
    errors = collect_verification_errors(
        ahead_count="1",
        test_rc=0,
        test_out="",
        eval_rc=0,
        eval_out="",
        lint_rc=0,
        fmt_rc=1,
        changed_files=["tests/test_x.py"],
    )
    assert "Lint or format check failed" in errors


def test_verification_no_test_files():
    errors = collect_verification_errors(
        ahead_count="1",
        test_rc=0,
        test_out="",
        eval_rc=0,
        eval_out="",
        lint_rc=0,
        fmt_rc=0,
        changed_files=["src/patina/store.py"],
    )
    assert "No test files were added or modified" in errors


def test_verification_multiple_errors():
    errors = collect_verification_errors(
        ahead_count="0",
        test_rc=1,
        test_out="fail",
        eval_rc=1,
        eval_out="fail",
        lint_rc=1,
        fmt_rc=1,
        changed_files=[],
    )
    assert len(errors) == 5


# --- Lockfile tests (filesystem, tmp_path) ---


def test_acquire_lock_succeeds_when_no_lockfile(tmp_path, monkeypatch):
    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    assert acquire_lock() is True
    assert lock_path.exists()
    assert lock_path.read_text().strip() == str(os.getpid())


def test_acquire_lock_fails_when_pid_alive(tmp_path, monkeypatch):
    lock_path = tmp_path / ".ai-dlc.lock"
    lock_path.write_text(str(os.getpid()))
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    assert acquire_lock() is False


def test_acquire_lock_succeeds_when_pid_stale(tmp_path, monkeypatch):
    lock_path = tmp_path / ".ai-dlc.lock"
    lock_path.write_text("999999999")
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    assert acquire_lock() is True
    assert lock_path.read_text().strip() == str(os.getpid())


def test_acquire_lock_succeeds_when_lockfile_has_garbage(tmp_path, monkeypatch):
    lock_path = tmp_path / ".ai-dlc.lock"
    lock_path.write_text("not-a-number")
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    assert acquire_lock() is True


def test_release_lock_removes_file(tmp_path, monkeypatch):
    lock_path = tmp_path / ".ai-dlc.lock"
    lock_path.write_text(str(os.getpid()))
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    release_lock()
    assert not lock_path.exists()


def test_release_lock_no_file_no_error(tmp_path, monkeypatch):
    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    release_lock()


# --- Subprocess tests: dependencies_met ---


def test_dependencies_met_all_closed(monkeypatch):
    issue = {"body": "Depends on: #10\nDepends on: #11"}
    results = [
        type("R", (), {"returncode": 0, "stdout": '{"state": "CLOSED"}'})(),
        type("R", (), {"returncode": 0, "stdout": '{"state": "CLOSED"}'})(),
    ]
    call_count = iter(results)
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        lambda *a, **kw: next(call_count),
    )
    assert implement_issue.dependencies_met(issue) is True


def test_dependencies_met_one_open(monkeypatch):
    issue = {"body": "Depends on: #10\nDepends on: #11"}
    results = [
        type("R", (), {"returncode": 0, "stdout": '{"state": "CLOSED"}'})(),
        type("R", (), {"returncode": 0, "stdout": '{"state": "OPEN"}'})(),
    ]
    call_count = iter(results)
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        lambda *a, **kw: next(call_count),
    )
    assert implement_issue.dependencies_met(issue) is False


def test_dependencies_met_no_deps():
    issue = {"body": "No deps here"}
    assert implement_issue.dependencies_met(issue) is True
