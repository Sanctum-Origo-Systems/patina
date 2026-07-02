from __future__ import annotations

import importlib
import json
import os

import implement_issue
from implement_issue import (
    acquire_lock,
    build_branch_name,
    build_pr_body,
    collect_verification_errors,
    create_branch,
    detect_issue_type,
    implement,
    implement_single_issue,
    log_run,
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


def test_build_pr_body_includes_stats():
    issue = {"number": 42, "title": "Add flag"}
    body = build_pr_body(issue, attempts=2, claude_calls=3, duration=120.5)
    assert "## AI-DLC Run Stats" in body
    assert "Attempts: 2/" in body
    assert "Claude calls: 3" in body
    assert "Duration: 120s" in body
    assert "Estimated cost: ~$" in body


def test_build_pr_body_no_stats_when_zero_calls():
    issue = {"number": 42, "title": "Add flag"}
    body = build_pr_body(issue)
    assert "AI-DLC Run Stats" not in body


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


# --- log_run tests ---


def test_log_run_writes_json_entry(tmp_path, monkeypatch):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)
    log_run(17, True, 2, 120.0, 5.00)

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["issue"] == 17
    assert entry["success"] is True
    assert entry["attempts"] == 2
    assert entry["duration_seconds"] == 120
    assert entry["estimated_cost"] == 5.00
    assert "timestamp" in entry


def test_log_run_appends_multiple_entries(tmp_path, monkeypatch):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)
    log_run(10, True, 1, 60.0, 2.50)
    log_run(11, False, 3, 300.0, 7.50)

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["issue"] == 10
    assert json.loads(lines[1])["issue"] == 11


def test_log_run_rounds_duration(tmp_path, monkeypatch):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)
    log_run(1, True, 1, 99.7, 2.50)

    entry = json.loads(log_path.read_text().strip())
    assert entry["duration_seconds"] == 100


def test_log_run_rounds_cost(tmp_path, monkeypatch):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)
    log_run(1, True, 1, 10.0, 2.555)

    entry = json.loads(log_path.read_text().strip())
    assert entry["estimated_cost"] == 2.56


# --- Subprocess tests: create_branch ---


def test_create_branch_calls_in_order(monkeypatch):
    calls = []
    issue = {"number": 18, "title": "Pull latest main before creating branch"}

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    branch = create_branch(issue)

    assert calls[0] == ["git", "checkout", "main"]
    assert calls[1] == ["git", "pull", "origin", "main"]
    assert calls[2][0:3] == ["git", "checkout", "-b"]
    assert branch in calls[2]


def test_create_branch_returns_correct_name(monkeypatch):
    issue = {"number": 5, "title": "Add new feature"}
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        lambda *a, **kw: type("R", (), {"returncode": 0})(),
    )
    assert create_branch(issue) == "ai-dlc/5-add-new-feature"


def test_create_branch_pulls_before_creating(monkeypatch):
    """pull must happen before checkout -b, not after."""
    order = []
    issue = {"number": 7, "title": "Fix bug"}

    def fake_run(cmd, **kwargs):
        if cmd == ["git", "pull", "origin", "main"]:
            order.append("pull")
        elif len(cmd) >= 3 and cmd[:2] == ["git", "checkout"] and cmd[2] == "-b":
            order.append("create")
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    create_branch(issue)

    assert order == ["pull", "create"]


# --- implement_single_issue tests ---

_FAKE_ISSUE = {"number": 42, "title": "Add feature", "body": "## Type\nfeature", "labels": []}


def _make_fake_run(responses=None):
    """Return a fake subprocess.run that cycles through responses."""
    responses = responses or []
    call_idx = [0]

    def fake_run(cmd, **kwargs):
        idx = min(call_idx[0], len(responses) - 1)
        call_idx[0] += 1
        return responses[idx]

    return fake_run


def _ok():
    return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()


def _fail():
    return type("R", (), {"returncode": 1, "stdout": "error", "stderr": ""})()


def _make_verify_ok():
    """Subprocess responses that make verify_implementation pass."""
    ahead = type("R", (), {"returncode": 0, "stdout": "1\n", "stderr": ""})()
    tests = type("R", (), {"returncode": 0, "stdout": "passed", "stderr": ""})()
    evals = type("R", (), {"returncode": 0, "stdout": "passed", "stderr": ""})()
    lint = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    fmt = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    diff = type("R", (), {"returncode": 0, "stdout": "tests/test_x.py\n", "stderr": ""})()
    return [ahead, tests, evals, lint, fmt, diff]


def test_implement_single_issue_returns_true_on_success(monkeypatch, tmp_path):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        # verify_implementation calls: ahead, pytest, eval, ruff check, ruff format, git diff
        if cmd[:3] == ["git", "rev-list", "--count"]:
            return type("R", (), {"returncode": 0, "stdout": "1\n", "stderr": ""})()
        if cmd[:3] == ["uv", "run", "pytest"] and "eval" not in str(cmd):
            return type("R", (), {"returncode": 0, "stdout": "passed", "stderr": ""})()
        if "eval" in str(cmd):
            return type("R", (), {"returncode": 0, "stdout": "passed", "stderr": ""})()
        if "ruff" in cmd:
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        if cmd[:3] == ["git", "diff", "--name-only"]:
            return type("R", (), {"returncode": 0, "stdout": "tests/test_x.py\n", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    monkeypatch.setattr(implement_issue, "implement", lambda issue, previous_errors=None: None)
    monkeypatch.setattr(implement_issue, "create_branch", lambda issue: "ai-dlc/42-add-feature")
    monkeypatch.setattr(implement_issue, "create_pr", lambda *a, **kw: None)
    monkeypatch.setattr(implement_issue, "label_in_review", lambda n: None)

    result = implement_single_issue(_FAKE_ISSUE)
    assert result is True
    assert log_path.exists()
    entry = json.loads(log_path.read_text().strip())
    assert entry["success"] is True
    assert entry["issue"] == 42


def test_implement_single_issue_returns_false_after_all_retries(monkeypatch, tmp_path):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["git", "rev-list", "--count"]:
            return type("R", (), {"returncode": 0, "stdout": "0\n", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    monkeypatch.setattr(implement_issue, "implement", lambda issue, previous_errors=None: None)
    monkeypatch.setattr(implement_issue, "create_branch", lambda issue: "ai-dlc/42-add-feature")
    monkeypatch.setattr(implement_issue, "cleanup_branch", lambda branch: None)

    result = implement_single_issue(_FAKE_ISSUE)
    assert result is False
    entry = json.loads(log_path.read_text().strip())
    assert entry["success"] is False
    assert entry["issue"] == 42


def test_implement_single_issue_labels_needs_human_on_failure(monkeypatch, tmp_path):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)
    gh_calls = []

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "gh":
            gh_calls.append(cmd)
        if cmd[:3] == ["git", "rev-list", "--count"]:
            return type("R", (), {"returncode": 0, "stdout": "0\n", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    monkeypatch.setattr(implement_issue, "implement", lambda issue, previous_errors=None: None)
    monkeypatch.setattr(implement_issue, "create_branch", lambda issue: "ai-dlc/42-add-feature")
    monkeypatch.setattr(implement_issue, "cleanup_branch", lambda branch: None)

    implement_single_issue(_FAKE_ISSUE)

    needs_human_calls = [c for c in gh_calls if "needs-human" in c]
    assert needs_human_calls, "Expected a gh call adding needs-human label"


# --- main() loop tests ---


def test_main_default_implements_one_issue(monkeypatch, tmp_path, capsys):
    import sys

    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    monkeypatch.setattr(sys, "argv", ["implement_issue.py"])

    issues = [{"number": 1, "title": "Issue one", "body": "", "labels": []}]
    call_count = [0]

    def fake_get_top():
        if call_count[0] < len(issues):
            return issues[call_count[0]]
        return None

    monkeypatch.setattr(implement_issue, "get_top_ready_issue", fake_get_top)
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda issue: True)

    def fake_implement_single(issue):
        call_count[0] += 1
        return True

    monkeypatch.setattr(implement_issue, "implement_single_issue", fake_implement_single)

    implement_issue.main()
    out = capsys.readouterr().out
    assert "Implemented 1 issue(s) this run." in out
    assert call_count[0] == 1


def test_main_max_issues_processes_multiple(monkeypatch, tmp_path, capsys):
    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)

    issues = [{"number": i, "title": f"Issue {i}", "body": "", "labels": []} for i in range(1, 5)]
    call_count = [0]

    def fake_get_top():
        if call_count[0] < len(issues):
            return issues[call_count[0]]
        return None

    monkeypatch.setattr(implement_issue, "get_top_ready_issue", fake_get_top)
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda issue: True)

    def fake_implement_single(issue):
        call_count[0] += 1
        return True

    monkeypatch.setattr(implement_issue, "implement_single_issue", fake_implement_single)

    import sys

    monkeypatch.setattr(sys, "argv", ["implement_issue.py", "--max-issues", "3"])
    implement_issue.main()
    out = capsys.readouterr().out
    assert "Implemented 3 issue(s) this run." in out
    assert call_count[0] == 3


def test_main_stops_when_no_more_issues(monkeypatch, tmp_path, capsys):
    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)

    issues = [{"number": 1, "title": "Only one", "body": "", "labels": []}]
    call_count = [0]

    def fake_get_top():
        if call_count[0] < len(issues):
            return issues[call_count[0]]
        return None

    monkeypatch.setattr(implement_issue, "get_top_ready_issue", fake_get_top)
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda issue: True)

    def fake_implement_single(issue):
        call_count[0] += 1
        return True

    monkeypatch.setattr(implement_issue, "implement_single_issue", fake_implement_single)

    import sys

    monkeypatch.setattr(sys, "argv", ["implement_issue.py", "--max-issues", "5"])
    implement_issue.main()
    out = capsys.readouterr().out
    assert "No more ready issues." in out
    assert "Implemented 1 issue(s) this run." in out
    assert call_count[0] == 1


def test_main_breaks_on_failure(monkeypatch, tmp_path, capsys):
    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)

    issues = [{"number": i, "title": f"Issue {i}", "body": "", "labels": []} for i in range(1, 4)]
    call_count = [0]

    def fake_get_top():
        if call_count[0] < len(issues):
            return issues[call_count[0]]
        return None

    monkeypatch.setattr(implement_issue, "get_top_ready_issue", fake_get_top)
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda issue: True)

    def fake_implement_single(issue):
        call_count[0] += 1
        return False  # always fails

    monkeypatch.setattr(implement_issue, "implement_single_issue", fake_implement_single)

    import sys

    monkeypatch.setattr(sys, "argv", ["implement_issue.py", "--max-issues", "3"])
    implement_issue.main()
    out = capsys.readouterr().out
    assert "Implemented 0 issue(s) this run." in out
    assert call_count[0] == 1  # stops after first failure


def test_main_labels_blocked_on_unmet_deps(monkeypatch, tmp_path, capsys):
    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)

    blocked_issue = {"number": 99, "title": "Blocked issue", "body": "", "labels": []}
    ready_issue = {"number": 100, "title": "Ready issue", "body": "", "labels": []}
    get_count = [0]

    def fake_get_top():
        issues = [blocked_issue, ready_issue]
        if get_count[0] < len(issues):
            return issues[get_count[0]]
        return None

    gh_calls = []

    def fake_subprocess_run(cmd, **kwargs):
        if cmd and cmd[0] == "gh":
            gh_calls.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(implement_issue, "get_top_ready_issue", fake_get_top)

    def fake_deps_met(issue):
        return issue["number"] != 99

    monkeypatch.setattr(implement_issue, "dependencies_met", fake_deps_met)

    implement_count = [0]

    def fake_implement_single(issue):
        get_count[0] += 1
        implement_count[0] += 1
        return True

    monkeypatch.setattr(implement_issue, "implement_single_issue", fake_implement_single)

    import sys

    monkeypatch.setattr(sys, "argv", ["implement_issue.py", "--max-issues", "1"])

    # Advance past the blocked issue when get_top is called
    def controlled_get_top():
        idx = get_count[0]
        issues = [blocked_issue, ready_issue]
        if idx < len(issues):
            return issues[idx]
        return None

    monkeypatch.setattr(implement_issue, "get_top_ready_issue", controlled_get_top)

    def fake_deps_met2(issue):
        if issue["number"] == 99:
            get_count[0] += 1  # advance past blocked
            return False
        return True

    monkeypatch.setattr(implement_issue, "dependencies_met", fake_deps_met2)

    implement_issue.main()
    out = capsys.readouterr().out
    blocked_label_calls = [c for c in gh_calls if "blocked" in c]
    assert blocked_label_calls, "Expected gh call adding blocked label"
    assert "Implemented 1 issue(s) this run." in out


def test_main_no_ready_issues_prints_message(monkeypatch, tmp_path, capsys):
    import sys

    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    monkeypatch.setattr(implement_issue, "get_top_ready_issue", lambda: None)
    monkeypatch.setattr(sys, "argv", ["implement_issue.py"])

    implement_issue.main()
    out = capsys.readouterr().out
    assert "No more ready issues." in out
    assert "Implemented 0 issue(s) this run." in out


# --- post_attempt_failure tests ---


def test_post_attempt_failure_calls_gh_comment(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    implement_issue.post_attempt_failure(42, 2, "Tests failed")

    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[:4] == ["gh", "issue", "comment", "42"]
    assert "--repo" in cmd
    assert "--body" in cmd


def test_post_attempt_failure_comment_includes_attempt_number(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    implement_issue.post_attempt_failure(7, 3, "lint error")

    body_idx = captured["cmd"].index("--body") + 1
    body = captured["cmd"][body_idx]
    assert "AI-DLC Attempt 3 failed:" in body
    assert "lint error" in body


def test_post_attempt_failure_truncates_long_errors(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    long_errors = "x" * 5000
    implement_issue.post_attempt_failure(1, 1, long_errors)

    body_idx = captured["cmd"].index("--body") + 1
    body = captured["cmd"][body_idx]
    assert "x" * 2000 in body
    assert "x" * 2001 not in body


# --- implement() env var tests ---


def test_implement_uses_default_model_and_timeout(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue, "IMPLEMENT_MODEL", "opus")
    monkeypatch.setattr(implement_issue, "IMPLEMENT_TIMEOUT", 900)
    monkeypatch.setattr(implement_issue, "build_implementation_prompt", lambda issue: "prompt")
    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)

    implement({"number": 1, "title": "Test", "body": ""})

    assert "--model" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == "opus"
    assert captured["timeout"] == 900


def test_implement_uses_env_model(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue, "IMPLEMENT_MODEL", "haiku")
    monkeypatch.setattr(implement_issue, "IMPLEMENT_TIMEOUT", 900)
    monkeypatch.setattr(implement_issue, "build_implementation_prompt", lambda issue: "prompt")
    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)

    implement({"number": 1, "title": "Test", "body": ""})

    assert captured["cmd"][captured["cmd"].index("--model") + 1] == "haiku"


def test_implement_uses_env_timeout(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue, "IMPLEMENT_MODEL", "opus")
    monkeypatch.setattr(implement_issue, "IMPLEMENT_TIMEOUT", 1800)
    monkeypatch.setattr(implement_issue, "build_implementation_prompt", lambda issue: "prompt")
    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)

    implement({"number": 1, "title": "Test", "body": ""})

    assert captured["timeout"] == 1800


def test_implement_model_default_from_env(monkeypatch):
    monkeypatch.delenv("PATINA_AIDLC_IMPL_MODEL", raising=False)
    importlib.reload(implement_issue)
    assert implement_issue.IMPLEMENT_MODEL == "opus"


def test_implement_timeout_default_from_env(monkeypatch):
    monkeypatch.delenv("PATINA_AIDLC_TIMEOUT", raising=False)
    importlib.reload(implement_issue)
    assert implement_issue.IMPLEMENT_TIMEOUT == 900


def test_implement_model_override_from_env(monkeypatch):
    monkeypatch.setenv("PATINA_AIDLC_IMPL_MODEL", "sonnet")
    importlib.reload(implement_issue)
    assert implement_issue.IMPLEMENT_MODEL == "sonnet"


def test_implement_timeout_override_from_env(monkeypatch):
    monkeypatch.setenv("PATINA_AIDLC_TIMEOUT", "1800")
    importlib.reload(implement_issue)
    assert implement_issue.IMPLEMENT_TIMEOUT == 1800


# --- implement() with previous_errors tests ---


def test_implement_appends_previous_errors_to_prompt(monkeypatch):
    captured = {}

    def fake_build_prompt(issue):
        return "BASE_PROMPT"

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue, "build_implementation_prompt", fake_build_prompt)
    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)

    issue = {"number": 1, "title": "Test", "body": ""}
    implement_issue.implement(issue, previous_errors="test failure output")

    prompt_arg = captured["cmd"][-1]
    assert "Previous Attempt Failed" in prompt_arg
    assert "test failure output" in prompt_arg
    assert "Fix these specific issues" in prompt_arg


def test_implement_no_previous_errors_omits_section(monkeypatch):
    captured = {}

    def fake_build_prompt(issue):
        return "BASE_PROMPT"

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue, "build_implementation_prompt", fake_build_prompt)
    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)

    issue = {"number": 1, "title": "Test", "body": ""}
    implement_issue.implement(issue)

    prompt_arg = captured["cmd"][-1]
    assert "Previous Attempt Failed" not in prompt_arg
    assert prompt_arg == "BASE_PROMPT"


def test_implement_truncates_previous_errors(monkeypatch):
    captured = {}

    def fake_build_prompt(issue):
        return "BASE"

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue, "build_implementation_prompt", fake_build_prompt)
    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)

    issue = {"number": 1, "title": "Test", "body": ""}
    implement_issue.implement(issue, previous_errors="e" * 5000)

    prompt_arg = captured["cmd"][-1]
    assert "e" * 2000 in prompt_arg
    assert "e" * 2001 not in prompt_arg


# --- Retry loop error passing tests ---


def test_implement_single_issue_passes_errors_to_next_attempt(monkeypatch, tmp_path):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)

    received_errors = []

    def fake_implement(issue, previous_errors=None):
        received_errors.append(previous_errors)

    monkeypatch.setattr(implement_issue, "implement", fake_implement)
    monkeypatch.setattr(implement_issue, "create_branch", lambda issue: "ai-dlc/42-test")
    monkeypatch.setattr(implement_issue, "cleanup_branch", lambda branch: None)
    monkeypatch.setattr(implement_issue, "post_attempt_failure", lambda n, a, e: None)

    call_count = [0]

    def fake_verify(branch):
        call_count[0] += 1
        if call_count[0] < 2:
            return False, "test error on attempt 1"
        return True, ""

    monkeypatch.setattr(implement_issue, "verify_implementation", fake_verify)

    def fake_run(cmd, **kwargs):
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    monkeypatch.setattr(implement_issue, "create_pr", lambda *a, **kw: None)
    monkeypatch.setattr(implement_issue, "label_in_review", lambda n: None)

    implement_issue.implement_single_issue(_FAKE_ISSUE)

    assert received_errors[0] is None
    assert received_errors[1] == "test error on attempt 1"


def test_implement_single_issue_calls_post_attempt_failure_on_error(monkeypatch, tmp_path):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)

    post_calls = []

    def fake_post(number, attempt, errors):
        post_calls.append((number, attempt, errors))

    monkeypatch.setattr(implement_issue, "implement", lambda issue, previous_errors=None: None)
    monkeypatch.setattr(implement_issue, "create_branch", lambda issue: "ai-dlc/42-test")
    monkeypatch.setattr(implement_issue, "cleanup_branch", lambda branch: None)
    monkeypatch.setattr(implement_issue, "post_attempt_failure", fake_post)

    def fake_verify(branch):
        return False, "verification failed"

    monkeypatch.setattr(implement_issue, "verify_implementation", fake_verify)

    def fake_run(cmd, **kwargs):
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)

    implement_issue.implement_single_issue(_FAKE_ISSUE)

    assert len(post_calls) == implement_issue.MAX_RETRIES
    assert post_calls[0] == (42, 1, "verification failed")
    assert post_calls[1] == (42, 2, "verification failed")
    assert post_calls[2] == (42, 3, "verification failed")
