from __future__ import annotations

import importlib
import json
import os
import subprocess

import claude_runner
import implement_issue
from claude_runner import ClaudeResult
from implement_issue import (
    acquire_lock,
    add_needs_design_label,
    build_branch_name,
    build_pr_body,
    cleanup_merged_labels,
    collect_verification_errors,
    create_branch,
    create_pr,
    design_gate,
    design_issue,
    design_required,
    detect_issue_type,
    ensure_clean_main,
    get_issue_by_number,
    has_design_comment,
    has_needs_design_label,
    implement,
    implement_single_issue,
    implement_targeted_issue,
    log_run,
    parent_issue_number,
    parse_and_strip_metric_targets,
    parse_dependency_numbers,
    parse_review_response,
    post_design,
    post_in_progress_comment,
    priority_rank,
    release_lock,
    review_implementation,
    select_top_issue,
    unblock_ready_issues,
)

# --- Smoke test: module docstring ---


def test_module_docstring_mentions_vps_deployment():
    assert implement_issue.__doc__ is not None
    assert "VPS" in implement_issue.__doc__


def _claude_result(
    cost_usd=1.5, input_tokens=1000, output_tokens=200, cache_read_tokens=500, success=True
):
    """Build a ClaudeResult for mocking implement()/run_claude()."""
    return ClaudeResult(
        text="",
        cost_usd=cost_usd,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        success=success,
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


# --- Pure function tests: parse_and_strip_metric_targets ---


def test_parse_metric_targets_no_targets():
    body = "## Summary\nAdd a feature\n\n## Acceptance Criteria\n- works"
    cleaned, targets = parse_and_strip_metric_targets(body)
    assert cleaned == body
    assert targets == []


def test_parse_metric_targets_single_target():
    body = "## Summary\nDo something\n**Metric Target:** latency < 100ms\n## End"
    cleaned, targets = parse_and_strip_metric_targets(body)
    assert "Metric Target" not in cleaned
    assert "## Summary" in cleaned
    assert "## End" in cleaned
    assert targets == ["**Metric Target:** latency < 100ms"]


def test_parse_metric_targets_multiple_targets():
    body = (
        "## Summary\nFix bug\n"
        "**Metric Target:** p99 < 200ms\n"
        "Some text\n"
        "**Metric Target:** error_rate < 0.1%\n"
        "## End"
    )
    cleaned, targets = parse_and_strip_metric_targets(body)
    assert "Metric Target" not in cleaned
    assert "Some text" in cleaned
    assert len(targets) == 2
    assert targets[0] == "**Metric Target:** p99 < 200ms"
    assert targets[1] == "**Metric Target:** error_rate < 0.1%"


def test_parse_metric_targets_empty_body():
    cleaned, targets = parse_and_strip_metric_targets("")
    assert cleaned == ""
    assert targets == []


def test_parse_metric_targets_preserves_surrounding_content():
    body = "before\n**Metric Target:** x\nafter\n"
    cleaned, targets = parse_and_strip_metric_targets(body)
    assert cleaned == "before\nafter\n"
    assert targets == ["**Metric Target:** x"]


def test_parse_metric_targets_indented_line():
    body = "text\n  **Metric Target:** indented\nmore text"
    cleaned, targets = parse_and_strip_metric_targets(body)
    assert "Metric Target" not in cleaned
    assert targets == ["  **Metric Target:** indented"]


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
    body = build_pr_body(
        issue,
        attempts=2,
        duration=120.5,
        cost_usd=3.42,
        input_tokens=45000,
        output_tokens=2300,
    )
    assert "## AI-DLC Run Stats" in body
    assert "Attempts: 2/" in body
    assert "Duration: 120s" in body
    assert "Input tokens: 45,000" in body
    assert "Output tokens: 2,300" in body
    assert "Cost: $3.42" in body


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
    log_run(17, True, 2, 120.0, 5.00, 45000, 2300, 16832)

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["issue"] == 17
    assert entry["success"] is True
    assert entry["attempts"] == 2
    assert entry["duration_seconds"] == 120
    assert entry["cost_usd"] == 5.00
    assert entry["input_tokens"] == 45000
    assert entry["output_tokens"] == 2300
    assert entry["cache_read_tokens"] == 16832
    assert "timestamp" in entry


def test_log_run_token_fields_default_to_zero(tmp_path, monkeypatch):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)
    log_run(1, True, 1, 10.0, 2.50)

    entry = json.loads(log_path.read_text().strip())
    assert entry["input_tokens"] == 0
    assert entry["output_tokens"] == 0
    assert entry["cache_read_tokens"] == 0


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
    assert entry["cost_usd"] == 2.56


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


# --- ensure_clean_main tests ---


def test_ensure_clean_main_calls_three_git_commands_in_order(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    ensure_clean_main()

    assert len(calls) == 3
    assert calls[0] == ["git", "checkout", "--", "."]
    assert calls[1] == ["git", "checkout", "main"]
    assert calls[2] == ["git", "pull", "--ff-only", "origin", "main"]


def test_ensure_clean_main_passes_repo_dir_as_cwd(monkeypatch):
    cwds = []

    def fake_run(cmd, **kwargs):
        cwds.append(kwargs.get("cwd"))
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    ensure_clean_main()

    assert all(cwd == implement_issue.REPO_DIR for cwd in cwds)


def test_ensure_clean_main_called_before_create_branch(monkeypatch, tmp_path):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)

    order = []
    monkeypatch.setattr(
        implement_issue, "ensure_clean_main", lambda: order.append("ensure_clean_main")
    )
    monkeypatch.setattr(
        implement_issue,
        "create_branch",
        lambda issue: order.append("create_branch") or "ai-dlc/42-x",
    )
    monkeypatch.setattr(
        implement_issue, "implement", lambda issue, previous_errors=None: _claude_result()
    )
    monkeypatch.setattr(implement_issue, "verify_implementation", lambda branch: (True, ""))
    monkeypatch.setattr(implement_issue, "review_implementation", lambda issue, branch: (True, ""))
    monkeypatch.setattr(implement_issue, "create_pr", lambda *a, **kw: None)
    monkeypatch.setattr(implement_issue, "label_in_review", lambda n: None)
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    implement_single_issue(
        {"number": 42, "title": "Test order", "body": "## Type\nfeature", "labels": []}
    )

    assert "ensure_clean_main" in order
    assert "create_branch" in order
    assert order.index("ensure_clean_main") < order.index("create_branch")


def test_implement_single_issue_catches_exception_returns_false(monkeypatch):
    monkeypatch.setattr(implement_issue, "ensure_clean_main", lambda: None)
    monkeypatch.setattr(implement_issue, "design_gate", lambda i, require_design=False: True)

    def exploding_run(cmd, **kwargs):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(implement_issue.subprocess, "run", exploding_run)

    result = implement_single_issue(
        {"number": 99, "title": "Exploding issue", "body": "", "labels": []}
    )
    assert result is False


def test_implement_single_issue_exception_does_not_propagate(monkeypatch):
    monkeypatch.setattr(implement_issue, "ensure_clean_main", lambda: None)
    monkeypatch.setattr(implement_issue, "design_gate", lambda i, require_design=False: True)
    monkeypatch.setattr(
        implement_issue, "create_branch", lambda issue: (_ for _ in ()).throw(ValueError("boom"))
    )
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    result = implement_single_issue({"number": 77, "title": "Boom", "body": "", "labels": []})
    assert result is False


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
    monkeypatch.setattr(
        implement_issue, "implement", lambda issue, previous_errors=None: _claude_result()
    )
    monkeypatch.setattr(implement_issue, "create_branch", lambda issue: "ai-dlc/42-add-feature")
    monkeypatch.setattr(implement_issue, "create_pr", lambda *a, **kw: None)
    monkeypatch.setattr(implement_issue, "label_in_review", lambda n: None)
    monkeypatch.setattr(implement_issue, "review_implementation", lambda issue, branch: (True, ""))

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
    monkeypatch.setattr(
        implement_issue, "implement", lambda issue, previous_errors=None: _claude_result()
    )
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
    monkeypatch.setattr(
        implement_issue, "implement", lambda issue, previous_errors=None: _claude_result()
    )
    monkeypatch.setattr(implement_issue, "create_branch", lambda issue: "ai-dlc/42-add-feature")
    monkeypatch.setattr(implement_issue, "cleanup_branch", lambda branch: None)

    implement_single_issue(_FAKE_ISSUE)

    needs_human_calls = [c for c in gh_calls if "needs-human" in c]
    assert needs_human_calls, "Expected a gh call adding needs-human label"


def test_implement_single_issue_logs_summed_token_totals(monkeypatch, tmp_path):
    """run_history entry sums real token/cost data across all attempts."""
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)

    results = iter(
        [
            _claude_result(cost_usd=1.0, input_tokens=100, output_tokens=10, cache_read_tokens=5),
            _claude_result(cost_usd=2.5, input_tokens=250, output_tokens=30, cache_read_tokens=15),
        ]
    )
    monkeypatch.setattr(
        implement_issue, "implement", lambda issue, previous_errors=None: next(results)
    )
    monkeypatch.setattr(implement_issue, "create_branch", lambda issue: "ai-dlc/42-test")
    monkeypatch.setattr(implement_issue, "cleanup_branch", lambda branch: None)
    monkeypatch.setattr(implement_issue, "post_attempt_failure", lambda n, a, e: None)
    monkeypatch.setattr(implement_issue, "create_pr", lambda *a, **kw: None)
    monkeypatch.setattr(implement_issue, "label_in_review", lambda n: None)
    monkeypatch.setattr(implement_issue, "review_implementation", lambda issue, branch: (True, ""))

    verify_calls = [0]

    def fake_verify(branch):
        verify_calls[0] += 1
        if verify_calls[0] < 2:
            return False, "attempt 1 failed"
        return True, ""

    monkeypatch.setattr(implement_issue, "verify_implementation", fake_verify)
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    assert implement_single_issue(_FAKE_ISSUE) is True
    entry = json.loads(log_path.read_text().strip())
    assert entry["cost_usd"] == 3.5
    assert entry["input_tokens"] == 350
    assert entry["output_tokens"] == 40
    assert entry["cache_read_tokens"] == 20


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
    monkeypatch.setattr(implement_issue, "cleanup_merged_labels", lambda: None)
    monkeypatch.setattr(implement_issue, "unblock_ready_issues", lambda: None)

    def fake_implement_single(issue, require_design=False):
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
    monkeypatch.setattr(implement_issue, "cleanup_merged_labels", lambda: None)
    monkeypatch.setattr(implement_issue, "unblock_ready_issues", lambda: None)

    def fake_implement_single(issue, require_design=False):
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
    monkeypatch.setattr(implement_issue, "cleanup_merged_labels", lambda: None)
    monkeypatch.setattr(implement_issue, "unblock_ready_issues", lambda: None)

    def fake_implement_single(issue, require_design=False):
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
    monkeypatch.setattr(implement_issue, "cleanup_merged_labels", lambda: None)
    monkeypatch.setattr(implement_issue, "unblock_ready_issues", lambda: None)

    def fake_implement_single(issue, require_design=False):
        call_count[0] += 1
        return False  # always fails

    monkeypatch.setattr(implement_issue, "implement_single_issue", fake_implement_single)

    import sys

    monkeypatch.setattr(sys, "argv", ["implement_issue.py", "--max-issues", "3"])
    implement_issue.main()
    out = capsys.readouterr().out
    assert "Implemented 0 issue(s) this run." in out
    assert call_count[0] == 1  # stops after first failure


def test_main_no_blocked_label_on_unmet_deps(monkeypatch, tmp_path, capsys):
    """main() never applies the 'blocked' label — deps are filtered in select_top_issue()."""
    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)

    gh_calls = []

    def fake_subprocess_run(cmd, **kwargs):
        if cmd and cmd[0] == "gh":
            gh_calls.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(implement_issue, "get_top_ready_issue", lambda: None)
    monkeypatch.setattr(implement_issue, "cleanup_merged_labels", lambda: None)
    monkeypatch.setattr(implement_issue, "unblock_ready_issues", lambda: None)

    import sys

    monkeypatch.setattr(sys, "argv", ["implement_issue.py"])

    implement_issue.main()
    out = capsys.readouterr().out
    blocked_label_calls = [c for c in gh_calls if "blocked" in c]
    assert not blocked_label_calls, "main() should never apply the 'blocked' label"
    assert "No more ready issues." in out


def test_main_no_ready_issues_prints_message(monkeypatch, tmp_path, capsys):
    import sys

    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    monkeypatch.setattr(implement_issue, "get_top_ready_issue", lambda: None)
    monkeypatch.setattr(implement_issue, "cleanup_merged_labels", lambda: None)
    monkeypatch.setattr(implement_issue, "unblock_ready_issues", lambda: None)
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
    monkeypatch.setattr(claude_runner.subprocess, "run", fake_run)

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
    monkeypatch.setattr(claude_runner.subprocess, "run", fake_run)

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
    monkeypatch.setattr(claude_runner.subprocess, "run", fake_run)

    implement({"number": 1, "title": "Test", "body": ""})

    assert captured["timeout"] == 1800


def test_implement_model_default_from_env(monkeypatch):
    monkeypatch.delenv("PATINA_AIDLC_IMPL_MODEL", raising=False)
    importlib.reload(implement_issue)
    assert implement_issue.IMPLEMENT_MODEL == "claude-opus-4-6[1m]"


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
    monkeypatch.setattr(claude_runner.subprocess, "run", fake_run)

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
    monkeypatch.setattr(claude_runner.subprocess, "run", fake_run)

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
    monkeypatch.setattr(claude_runner.subprocess, "run", fake_run)

    issue = {"number": 1, "title": "Test", "body": ""}
    implement_issue.implement(issue, previous_errors="e" * 5000)

    prompt_arg = captured["cmd"][-1]
    assert "e" * 2000 in prompt_arg
    assert "e" * 2001 not in prompt_arg


# --- design_issue tests ---


def _json_result(text):
    """A claude_runner subprocess result carrying JSON with a result field."""
    return type(
        "R",
        (),
        {"returncode": 0, "stdout": json.dumps({"result": text}), "stderr": ""},
    )()


def test_design_issue_prompt_contains_issue_and_claude_md(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _json_result("design proposal")

    monkeypatch.setattr(claude_runner.subprocess, "run", fake_run)

    issue = {"number": 43, "title": "Add design_issue function", "body": "Design body details"}
    design_issue(issue)

    prompt = captured["cmd"][-1]
    assert captured["cmd"][:2] == ["claude", "-p"]
    assert "Add design_issue function" in prompt
    assert "Design body details" in prompt
    # CLAUDE.md content is embedded as project conventions.
    assert "Cognitive assistant" in prompt


def test_design_issue_uses_implement_model(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _json_result("design proposal")

    monkeypatch.setattr(implement_issue, "IMPLEMENT_MODEL", "opus")
    monkeypatch.setattr(claude_runner.subprocess, "run", fake_run)

    design_issue({"number": 1, "title": "Test", "body": ""})

    cmd = captured["cmd"]
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "opus"


def test_design_issue_returns_text_on_success(monkeypatch):
    monkeypatch.setattr(
        claude_runner.subprocess, "run", lambda *a, **kw: _json_result("proposed design")
    )
    result = design_issue({"number": 1, "title": "Test", "body": "b"})
    assert result == "proposed design"


def test_design_issue_returns_empty_on_timeout(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))

    monkeypatch.setattr(claude_runner.subprocess, "run", fake_run)
    assert design_issue({"number": 1, "title": "Test", "body": "b"}) == ""


def test_design_issue_returns_empty_on_nonzero_exit(monkeypatch):
    def fake_run(cmd, **kwargs):
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()

    monkeypatch.setattr(claude_runner.subprocess, "run", fake_run)
    assert design_issue({"number": 1, "title": "Test", "body": "b"}) == ""


def test_design_issue_handles_missing_body(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _json_result("design proposal")

    monkeypatch.setattr(claude_runner.subprocess, "run", fake_run)
    # A None body must not raise and must still produce a prompt.
    design_issue({"number": 5, "title": "No body issue", "body": None})
    assert "No body issue" in captured["cmd"][-1]


# --- Retry loop error passing tests ---


def test_implement_single_issue_passes_errors_to_next_attempt(monkeypatch, tmp_path):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)

    received_errors = []

    def fake_implement(issue, previous_errors=None):
        received_errors.append(previous_errors)
        return _claude_result()

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
    monkeypatch.setattr(implement_issue, "review_implementation", lambda issue, branch: (True, ""))

    implement_issue.implement_single_issue(_FAKE_ISSUE)

    assert received_errors[0] is None
    assert received_errors[1] == "test error on attempt 1"


def test_implement_single_issue_calls_post_attempt_failure_on_error(monkeypatch, tmp_path):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)

    post_calls = []

    def fake_post(number, attempt, errors):
        post_calls.append((number, attempt, errors))

    monkeypatch.setattr(
        implement_issue, "implement", lambda issue, previous_errors=None: _claude_result()
    )
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


# --- cleanup_merged_labels tests ---


def test_cleanup_merged_labels_removes_label_from_each_issue(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["gh", "issue", "list"]:
            return type(
                "R",
                (),
                {"returncode": 0, "stdout": '[{"number": 10}, {"number": 14}]', "stderr": ""},
            )()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    cleanup_merged_labels()

    edit_calls = [c for c in calls if c[:3] == ["gh", "issue", "edit"]]
    assert len(edit_calls) == 2
    assert edit_calls[0][3] == "10"
    assert edit_calls[1][3] == "14"
    for c in edit_calls:
        assert "--remove-label" in c
        assert c[c.index("--remove-label") + 1] == "in-review"


def test_cleanup_merged_labels_queries_closed_in_review_issues(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["gh", "issue", "list"]:
            captured["list_cmd"] = cmd
            return type("R", (), {"returncode": 0, "stdout": "[]", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    cleanup_merged_labels()

    cmd = captured["list_cmd"]
    assert "--label" in cmd and cmd[cmd.index("--label") + 1] == "in-review"
    assert "--state" in cmd and cmd[cmd.index("--state") + 1] == "closed"


def test_cleanup_merged_labels_no_issues_no_edits(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["gh", "issue", "list"]:
            return type("R", (), {"returncode": 0, "stdout": "[]", "stderr": ""})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    cleanup_merged_labels()

    edit_calls = [c for c in calls if c[:3] == ["gh", "issue", "edit"]]
    assert edit_calls == []


def test_cleanup_merged_labels_returns_early_on_list_failure(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["gh", "issue", "list"]:
            return type("R", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    cleanup_merged_labels()

    edit_calls = [c for c in calls if c[:3] == ["gh", "issue", "edit"]]
    assert edit_calls == []


def test_main_runs_cleanup_merged_labels(monkeypatch, tmp_path):
    import sys

    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    monkeypatch.setattr(sys, "argv", ["implement_issue.py"])
    monkeypatch.setattr(implement_issue, "get_top_ready_issue", lambda: None)

    ran = []
    monkeypatch.setattr(implement_issue, "cleanup_merged_labels", lambda: ran.append(True))
    monkeypatch.setattr(implement_issue, "unblock_ready_issues", lambda: None)

    implement_issue.main()
    assert ran == [True]


# --- unblock_ready_issues tests ---


def _blocked(number, title="Blocked", body=""):
    return {
        "number": number,
        "title": title,
        "body": body,
        "labels": [{"name": "blocked"}],
    }


def _gh_list_result(issues):
    payload = json.dumps(issues)
    return type(
        "R",
        (),
        {"returncode": 0, "stdout": payload, "stderr": ""},
    )()


def test_unblock_ready_issues_unblocks_when_deps_met(monkeypatch):
    blocked_issues = [_blocked(10, "Blocked issue", "Depends on: #5")]
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["gh", "issue", "list"]:
            return _gh_list_result(blocked_issues)
        return _ok()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: True)

    unblock_ready_issues()

    edit_calls = [c for c in calls if c[:3] == ["gh", "issue", "edit"]]
    assert len(edit_calls) == 1
    cmd = edit_calls[0]
    assert cmd[3] == "10"
    assert "--remove-label" in cmd
    assert cmd[cmd.index("--remove-label") + 1] == "blocked"
    assert "--add-label" in cmd
    assert cmd[cmd.index("--add-label") + 1] == "ready"


def test_unblock_ready_issues_skips_when_deps_not_met(monkeypatch):
    blocked_issues = [_blocked(10, "Still blocked", "Depends on: #5")]
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["gh", "issue", "list"]:
            return _gh_list_result(blocked_issues)
        return _ok()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: False)

    unblock_ready_issues()

    edit_calls = [c for c in calls if c[:3] == ["gh", "issue", "edit"]]
    assert edit_calls == []


def test_unblock_ready_issues_handles_mixed_deps(monkeypatch):
    blocked_issues = [
        _blocked(10, "Ready to unblock", "Depends on: #5"),
        _blocked(11, "Still blocked", "Depends on: #6"),
        _blocked(12, "Also ready", "Depends on: #7"),
    ]
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["gh", "issue", "list"]:
            return _gh_list_result(blocked_issues)
        return _ok()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    monkeypatch.setattr(
        implement_issue,
        "dependencies_met",
        lambda i: i["number"] != 11,
    )

    unblock_ready_issues()

    edit_calls = [c for c in calls if c[:3] == ["gh", "issue", "edit"]]
    assert len(edit_calls) == 2
    edited_numbers = {c[3] for c in edit_calls}
    assert edited_numbers == {"10", "12"}


def test_unblock_ready_issues_exits_silently_on_gh_failure(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["gh", "issue", "list"]:
            return _fail()
        return _ok()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)

    unblock_ready_issues()

    edit_calls = [c for c in calls if c[:3] == ["gh", "issue", "edit"]]
    assert edit_calls == []


def test_unblock_ready_issues_no_blocked_issues(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["gh", "issue", "list"]:
            return _gh_list_result([])
        return _ok()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)

    unblock_ready_issues()

    edit_calls = [c for c in calls if c[:3] == ["gh", "issue", "edit"]]
    assert edit_calls == []


def test_unblock_ready_issues_queries_blocked_open_issues(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["gh", "issue", "list"]:
            captured["list_cmd"] = cmd
            return _gh_list_result([])
        return _ok()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)

    unblock_ready_issues()

    cmd = captured["list_cmd"]
    assert "--label" in cmd
    assert cmd[cmd.index("--label") + 1] == "blocked"
    assert "--state" in cmd
    assert cmd[cmd.index("--state") + 1] == "open"


def test_unblock_ready_issues_prints_unblocked(monkeypatch, capsys):
    blocked_issues = [_blocked(10, "Unblock me")]

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["gh", "issue", "list"]:
            return _gh_list_result(blocked_issues)
        return _ok()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: True)

    unblock_ready_issues()

    out = capsys.readouterr().out
    assert "Unblocked #10" in out
    assert "Unblock me" in out


def test_main_calls_unblock_ready_issues(monkeypatch, tmp_path):
    import sys

    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    monkeypatch.setattr(sys, "argv", ["implement_issue.py"])
    monkeypatch.setattr(implement_issue, "get_top_ready_issue", lambda: None)
    monkeypatch.setattr(implement_issue, "cleanup_merged_labels", lambda: None)

    ran = []
    monkeypatch.setattr(implement_issue, "unblock_ready_issues", lambda: ran.append(True))

    implement_issue.main()
    assert ran == [True]


def test_main_calls_unblock_before_implementation_loop(monkeypatch, tmp_path):
    import sys

    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    monkeypatch.setattr(sys, "argv", ["implement_issue.py"])
    monkeypatch.setattr(implement_issue, "cleanup_merged_labels", lambda: None)

    order = []
    monkeypatch.setattr(implement_issue, "unblock_ready_issues", lambda: order.append("unblock"))

    def fake_get_top():
        order.append("get_top")
        return None

    monkeypatch.setattr(implement_issue, "get_top_ready_issue", fake_get_top)

    implement_issue.main()
    assert "unblock" in order
    assert "get_top" in order
    assert order.index("unblock") < order.index("get_top")


# --- get_issue_by_number tests ---


def test_get_issue_by_number_returns_issue(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type(
            "R",
            (),
            {
                "returncode": 0,
                "stdout": '{"number": 28, "title": "Big issue", "body": "b", "labels": []}',
                "stderr": "",
            },
        )()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    issue = get_issue_by_number(28)

    assert issue["number"] == 28
    assert issue["title"] == "Big issue"
    cmd = captured["cmd"]
    assert cmd[:4] == ["gh", "issue", "view", "28"]
    # Fetches directly without filtering on the ready label.
    assert "--label" not in cmd


def test_get_issue_by_number_returns_none_on_failure(monkeypatch):
    def fake_run(cmd, **kwargs):
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": "not found"})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    assert get_issue_by_number(999) is None


# --- implement_targeted_issue tests ---


def test_implement_targeted_issue_bypasses_ready_and_points(monkeypatch, capsys):
    targeted = {"number": 28, "title": "Five point issue", "body": "", "labels": []}
    monkeypatch.setattr(implement_issue, "get_issue_by_number", lambda n: targeted)
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda issue: True)

    # get_top_ready_issue must NOT be consulted for a targeted run.
    def boom():
        raise AssertionError("get_top_ready_issue should not be called")

    monkeypatch.setattr(implement_issue, "get_top_ready_issue", boom)

    implemented = []
    monkeypatch.setattr(
        implement_issue,
        "implement_single_issue",
        lambda issue, require_design=False: implemented.append(issue["number"]) or True,
    )

    assert implement_targeted_issue(28) is True
    assert implemented == [28]
    assert "Implemented 1 issue(s) this run." in capsys.readouterr().out


def test_implement_targeted_issue_aborts_on_unmet_deps(monkeypatch, capsys):
    targeted = {"number": 28, "title": "Blocked", "body": "Depends on: #5", "labels": []}
    monkeypatch.setattr(implement_issue, "get_issue_by_number", lambda n: targeted)
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda issue: False)

    called = []
    monkeypatch.setattr(
        implement_issue, "implement_single_issue", lambda issue: called.append(True)
    )

    assert implement_targeted_issue(28) is False
    assert called == []
    assert "dependencies not met" in capsys.readouterr().out


def test_implement_targeted_issue_aborts_when_fetch_fails(monkeypatch, capsys):
    monkeypatch.setattr(implement_issue, "get_issue_by_number", lambda n: None)

    called = []
    monkeypatch.setattr(
        implement_issue, "implement_single_issue", lambda issue: called.append(True)
    )

    assert implement_targeted_issue(28) is False
    assert called == []
    assert "could not fetch issue" in capsys.readouterr().out


# --- main() --issue flag tests ---


def test_main_issue_flag_targets_specific_issue(monkeypatch, tmp_path):
    import sys

    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    monkeypatch.setattr(sys, "argv", ["implement_issue.py", "--issue", "28"])
    monkeypatch.setattr(implement_issue, "cleanup_merged_labels", lambda: None)
    monkeypatch.setattr(implement_issue, "unblock_ready_issues", lambda: None)

    # Auto-pick path must not be used when --issue is given.
    def boom():
        raise AssertionError("get_top_ready_issue should not be called with --issue")

    monkeypatch.setattr(implement_issue, "get_top_ready_issue", boom)

    targeted = []
    monkeypatch.setattr(
        implement_issue,
        "implement_targeted_issue",
        lambda number, require_design=False: targeted.append(number) or True,
    )

    implement_issue.main()
    assert targeted == [28]


def test_main_issue_flag_with_max_issues_runs_without_error(monkeypatch, tmp_path):
    import sys

    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    monkeypatch.setattr(sys, "argv", ["implement_issue.py", "--issue", "28", "--max-issues", "1"])
    monkeypatch.setattr(implement_issue, "cleanup_merged_labels", lambda: None)
    monkeypatch.setattr(implement_issue, "unblock_ready_issues", lambda: None)
    monkeypatch.setattr(implement_issue, "get_top_ready_issue", lambda: None)

    targeted = []
    monkeypatch.setattr(
        implement_issue,
        "implement_targeted_issue",
        lambda number, require_design=False: targeted.append(number) or True,
    )

    implement_issue.main()
    assert targeted == [28]


def test_main_without_issue_flag_uses_auto_pick(monkeypatch, tmp_path):
    import sys

    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    monkeypatch.setattr(sys, "argv", ["implement_issue.py"])
    monkeypatch.setattr(implement_issue, "cleanup_merged_labels", lambda: None)
    monkeypatch.setattr(implement_issue, "unblock_ready_issues", lambda: None)

    auto_pick_called = []

    def fake_get_top():
        auto_pick_called.append(True)
        return None

    monkeypatch.setattr(implement_issue, "get_top_ready_issue", fake_get_top)

    # Targeted path must not be used without --issue.
    def boom(number):
        raise AssertionError("implement_targeted_issue should not be called without --issue")

    monkeypatch.setattr(implement_issue, "implement_targeted_issue", boom)

    implement_issue.main()
    assert auto_pick_called == [True]


# --- parent_issue_number tests ---


def test_parent_issue_number_found():
    issue = {"body": "Some text\nParent issue: #28\nmore"}
    assert parent_issue_number(issue) == 28


def test_parent_issue_number_none_when_standalone():
    issue = {"body": "A standalone issue with no parent reference"}
    assert parent_issue_number(issue) is None


def test_parent_issue_number_none_when_body_missing():
    assert parent_issue_number({}) is None
    assert parent_issue_number({"body": None}) is None


# --- priority_rank tests ---


def test_priority_rank_orders_labels():
    p0 = {"labels": [{"name": "p0"}]}
    p1 = {"labels": [{"name": "p1"}]}
    p2 = {"labels": [{"name": "p2"}]}
    assert priority_rank(p0) < priority_rank(p1) < priority_rank(p2)


def test_priority_rank_unlabeled_is_lowest():
    unlabeled = {"labels": [{"name": "ready"}]}
    assert priority_rank(unlabeled) == 99


# --- select_top_issue tests ---


def _sub(number, parent, priority=None):
    labels = [{"name": priority}] if priority else []
    return {
        "number": number,
        "title": f"Step for #{parent}",
        "body": f"Parent issue: #{parent}",
        "labels": labels,
    }


def _standalone(number, priority=None):
    labels = [{"name": priority}] if priority else []
    return {
        "number": number,
        "title": f"Standalone #{number}",
        "body": "No parent here",
        "labels": labels,
    }


def test_select_top_issue_empty_returns_none():
    assert select_top_issue([]) is None


def test_select_top_issue_prefers_group_with_most_sub_issues(monkeypatch):
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: True)
    # Parent 28 has two ready sub-issues, parent 30 has one.
    issues = [
        _sub(101, parent=30),
        _sub(102, parent=28),
        _sub(103, parent=28),
    ]
    chosen = select_top_issue(issues)
    assert parent_issue_number(chosen) == 28


def test_select_top_issue_returns_lowest_step_within_group(monkeypatch):
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: True)
    issues = [
        _sub(103, parent=28),
        _sub(101, parent=28),
        _sub(102, parent=28),
    ]
    chosen = select_top_issue(issues)
    assert chosen["number"] == 101


def test_select_top_issue_ties_break_to_lowest_parent(monkeypatch):
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: True)
    # Both groups have one ready sub-issue; lowest parent number wins.
    issues = [
        _sub(200, parent=30),
        _sub(201, parent=28),
    ]
    chosen = select_top_issue(issues)
    assert parent_issue_number(chosen) == 28


def test_select_top_issue_falls_back_to_priority_when_all_standalone(monkeypatch):
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: True)
    issues = [
        _standalone(10, priority="p2"),
        _standalone(11, priority="p0"),
        _standalone(12, priority="p1"),
    ]
    chosen = select_top_issue(issues)
    assert chosen["number"] == 11


def test_select_top_issue_prefers_parented_over_standalone_same_priority(monkeypatch):
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: True)
    # Standalone and sub-issue share priority; group preference wins.
    issues = [
        _standalone(10, priority="p1"),
        _sub(20, parent=28, priority="p1"),
    ]
    chosen = select_top_issue(issues)
    assert chosen["number"] == 20


def test_select_top_issue_higher_priority_standalone_beats_sub_issue(monkeypatch):
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: True)
    # p0 standalone must not be blocked by a lower-priority sub-issue group.
    issues = [
        _standalone(10, priority="p0"),
        _sub(20, parent=28, priority="p1"),
    ]
    chosen = select_top_issue(issues)
    assert chosen["number"] == 10


def test_select_top_issue_higher_priority_sub_issue_beats_standalone(monkeypatch):
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: True)
    # p0 sub-issue outranks a p1 standalone.
    issues = [
        _standalone(10, priority="p1"),
        _sub(20, parent=28, priority="p0"),
    ]
    chosen = select_top_issue(issues)
    assert chosen["number"] == 20


def test_select_top_issue_only_sub_issues_returns_largest_group(monkeypatch):
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: True)
    # No standalone issues: largest group still wins, earliest step within it.
    issues = [
        _sub(101, parent=30, priority="p1"),
        _sub(102, parent=28, priority="p2"),
        _sub(103, parent=28, priority="p2"),
    ]
    chosen = select_top_issue(issues)
    assert chosen["number"] == 102


def test_select_top_issue_only_standalone_returns_highest_priority(monkeypatch):
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: True)
    issues = [
        _standalone(10, priority="p2"),
        _standalone(11, priority="p0"),
        _standalone(12, priority="p1"),
    ]
    chosen = select_top_issue(issues)
    assert chosen["number"] == 11


def test_select_top_issue_single_standalone(monkeypatch):
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: True)
    issues = [_standalone(10)]
    assert select_top_issue(issues)["number"] == 10


def test_select_top_issue_filters_unmet_dependencies(monkeypatch):
    """Issues with unmet dependencies are excluded from selection."""
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: i["number"] != 10)
    issues = [
        _standalone(10, priority="p0"),
        _standalone(11, priority="p1"),
    ]
    chosen = select_top_issue(issues)
    assert chosen["number"] == 11


def test_select_top_issue_returns_none_when_all_deps_unmet(monkeypatch):
    """When every candidate has unmet dependencies, returns None."""
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: False)
    issues = [_standalone(10), _standalone(11)]
    assert select_top_issue(issues) is None


def test_select_top_issue_filters_deps_before_grouping(monkeypatch):
    """Dependency filtering happens before sub-issue grouping logic."""
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: i["number"] != 102)
    # Parent 28 has two sub-issues, but one has unmet deps.
    # Parent 30 has one sub-issue with deps met.
    # After filtering: parent 28 has 1, parent 30 has 1 — tie breaks to lowest parent.
    issues = [
        _sub(101, parent=30),
        _sub(102, parent=28),
        _sub(103, parent=28),
    ]
    chosen = select_top_issue(issues)
    assert parent_issue_number(chosen) == 28
    assert chosen["number"] == 103


# --- get_top_ready_issue tests ---


def test_get_top_ready_issue_returns_none_on_gh_failure(monkeypatch):
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        lambda *a, **kw: type("R", (), {"returncode": 1, "stdout": ""})(),
    )
    assert implement_issue.get_top_ready_issue() is None


def test_get_top_ready_issue_groups_sub_issues(monkeypatch):
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda i: True)
    payload = json.dumps(
        [
            _sub(102, parent=28),
            _sub(101, parent=28),
            _sub(200, parent=30),
        ]
    )
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": payload})(),
    )
    chosen = implement_issue.get_top_ready_issue()
    assert chosen["number"] == 101


def test_get_top_ready_issue_empty_list(monkeypatch):
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "[]"})(),
    )
    assert implement_issue.get_top_ready_issue() is None


# --- design_required tests ---


def test_design_required_true_with_flag():
    issue = {"number": 1, "labels": []}
    assert design_required(issue, require_design=True) is True


def test_design_required_true_with_label():
    issue = {"number": 1, "labels": [{"name": "design-required"}]}
    assert design_required(issue) is True


def test_design_required_false_without_flag_or_label():
    issue = {"number": 1, "labels": [{"name": "ready"}]}
    assert design_required(issue) is False
    assert design_required(issue, require_design=False) is False


def test_design_required_missing_labels_key():
    assert design_required({"number": 1}) is False


# --- has_needs_design_label tests ---


def test_has_needs_design_label_true():
    issue = {"labels": [{"name": "needs-design"}, {"name": "ready"}]}
    assert has_needs_design_label(issue) is True


def test_has_needs_design_label_false():
    issue = {"labels": [{"name": "ready"}]}
    assert has_needs_design_label(issue) is False


def test_has_needs_design_label_missing_labels_key():
    assert has_needs_design_label({}) is False


# --- has_design_comment tests ---


def test_has_design_comment_true(monkeypatch):
    payload = json.dumps(
        {"comments": [{"body": "unrelated"}, {"body": "**Implementation Design:**\n\nAdd a flag"}]}
    )
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": payload, "stderr": ""})(),
    )
    assert has_design_comment(44) is True


def test_has_design_comment_false_when_absent(monkeypatch):
    payload = json.dumps({"comments": [{"body": "just a normal comment"}]})
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": payload, "stderr": ""})(),
    )
    assert has_design_comment(44) is False


def test_has_design_comment_false_on_gh_failure(monkeypatch):
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        lambda *a, **kw: type("R", (), {"returncode": 1, "stdout": "", "stderr": "boom"})(),
    )
    assert has_design_comment(44) is False


def test_has_design_comment_queries_comments(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": '{"comments": []}', "stderr": ""})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    has_design_comment(44)

    cmd = captured["cmd"]
    assert cmd[:4] == ["gh", "issue", "view", "44"]
    assert "comments" in cmd


# --- post_design tests ---


def test_post_design_posts_marker_and_body(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    post_design(44, "Here is the design")

    cmd = captured["cmd"]
    assert cmd[:4] == ["gh", "issue", "comment", "44"]
    body = cmd[cmd.index("--body") + 1]
    assert "Implementation Design:" in body
    assert "Here is the design" in body


# --- add_needs_design_label tests ---


def test_add_needs_design_label_adds_label(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    add_needs_design_label(44)

    cmd = captured["cmd"]
    assert cmd[:4] == ["gh", "issue", "edit", "44"]
    assert "--add-label" in cmd
    assert cmd[cmd.index("--add-label") + 1] == "needs-design"


# --- design_gate tests ---


def test_design_gate_skips_when_not_required():
    """No flag and no label: gate does nothing and proceeds."""
    issue = {"number": 44, "title": "Add flag", "body": "b", "labels": []}
    assert design_gate(issue, require_design=False) is True


def test_design_gate_generates_design_when_missing(monkeypatch):
    """Flag set, no design comment: generate, post, label, and skip."""
    issue = {"number": 44, "title": "Add flag", "body": "b", "labels": []}
    events = {}

    monkeypatch.setattr(implement_issue, "has_design_comment", lambda n: False)
    monkeypatch.setattr(implement_issue, "design_issue", lambda i: "generated design")
    monkeypatch.setattr(implement_issue, "post_design", lambda n, d: events.update(posted=(n, d)))
    monkeypatch.setattr(
        implement_issue, "add_needs_design_label", lambda n: events.update(labeled=n)
    )

    assert design_gate(issue, require_design=True) is False
    assert events["posted"] == (44, "generated design")
    assert events["labeled"] == 44


def test_design_gate_triggers_on_label_without_flag(monkeypatch):
    """design-required label triggers the gate even without the flag."""
    issue = {"number": 44, "title": "T", "body": "b", "labels": [{"name": "design-required"}]}
    calls = []

    monkeypatch.setattr(implement_issue, "has_design_comment", lambda n: False)
    monkeypatch.setattr(implement_issue, "design_issue", lambda i: "d")
    monkeypatch.setattr(implement_issue, "post_design", lambda n, d: calls.append("post"))
    monkeypatch.setattr(implement_issue, "add_needs_design_label", lambda n: calls.append("label"))

    assert design_gate(issue, require_design=False) is False
    assert calls == ["post", "label"]


def test_design_gate_proceeds_when_design_approved(monkeypatch):
    """Design comment exists and needs-design is gone: human approved, proceed."""
    issue = {"number": 44, "title": "T", "body": "b", "labels": [{"name": "design-required"}]}
    monkeypatch.setattr(implement_issue, "has_design_comment", lambda n: True)

    def boom(i):
        raise AssertionError("design_issue must not be called when a design exists")

    monkeypatch.setattr(implement_issue, "design_issue", boom)
    assert design_gate(issue, require_design=True) is True


def test_design_gate_skips_when_awaiting_approval(monkeypatch):
    """Design comment exists but needs-design still present: skip, do not regenerate."""
    issue = {
        "number": 44,
        "title": "T",
        "body": "b",
        "labels": [{"name": "design-required"}, {"name": "needs-design"}],
    }
    monkeypatch.setattr(implement_issue, "has_design_comment", lambda n: True)

    def boom(i):
        raise AssertionError("design_issue must not be called while awaiting approval")

    monkeypatch.setattr(implement_issue, "design_issue", boom)
    assert design_gate(issue, require_design=True) is False


def test_design_gate_require_design_no_comment_calls_design_and_labels(monkeypatch):
    """--require-design with no design comment: design_issue() runs and needs-design is added."""
    issue = {"number": 44, "title": "Add flag", "body": "b", "labels": []}
    calls = []

    monkeypatch.setattr(implement_issue, "has_design_comment", lambda n: False)
    monkeypatch.setattr(
        implement_issue, "design_issue", lambda i: calls.append("design") or "the design"
    )
    monkeypatch.setattr(implement_issue, "post_design", lambda n, d: calls.append("post"))
    monkeypatch.setattr(implement_issue, "add_needs_design_label", lambda n: calls.append("label"))

    assert design_gate(issue, require_design=True) is False
    assert "design" in calls
    assert "label" in calls


def test_design_gate_empty_design_skips_comment(monkeypatch):
    """design_issue() returning an empty string: no comment is posted."""
    issue = {"number": 44, "title": "T", "body": "b", "labels": []}
    posted = []

    monkeypatch.setattr(implement_issue, "has_design_comment", lambda n: False)
    monkeypatch.setattr(implement_issue, "design_issue", lambda i: "")
    monkeypatch.setattr(implement_issue, "post_design", lambda n, d: posted.append(d))
    monkeypatch.setattr(implement_issue, "add_needs_design_label", lambda n: None)

    assert design_gate(issue, require_design=True) is False
    assert posted == []


# --- implement_single_issue design gate integration ---


def test_implement_single_issue_skips_when_design_gate_blocks(monkeypatch):
    """A blocked design gate returns False without touching the branch/labels."""
    issue = {"number": 44, "title": "T", "body": "b", "labels": []}
    monkeypatch.setattr(implement_issue, "ensure_clean_main", lambda: None)
    monkeypatch.setattr(implement_issue, "design_gate", lambda i, require_design=False: False)

    def boom(issue):
        raise AssertionError("create_branch must not run when the design gate blocks")

    monkeypatch.setattr(implement_issue, "create_branch", boom)

    assert implement_single_issue(issue, require_design=True) is False


def test_implement_single_issue_passes_require_design_to_gate(monkeypatch, tmp_path):
    """The require_design flag reaches the design gate."""
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)
    monkeypatch.setattr(implement_issue, "ensure_clean_main", lambda: None)

    captured = {}

    def fake_gate(issue, require_design=False):
        captured["require_design"] = require_design
        return False

    monkeypatch.setattr(implement_issue, "design_gate", fake_gate)
    implement_single_issue(_FAKE_ISSUE, require_design=True)
    assert captured["require_design"] is True


# --- main() --require-design flag tests ---


def test_main_require_design_flag_threads_to_implement(monkeypatch, tmp_path):
    import sys

    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    monkeypatch.setattr(sys, "argv", ["implement_issue.py", "--require-design"])
    monkeypatch.setattr(implement_issue, "cleanup_merged_labels", lambda: None)
    monkeypatch.setattr(implement_issue, "unblock_ready_issues", lambda: None)

    issue = {"number": 1, "title": "One", "body": "", "labels": []}
    served = [issue, None]
    monkeypatch.setattr(implement_issue, "get_top_ready_issue", lambda: served.pop(0))

    captured = {}

    def fake_single(issue, require_design=False):
        captured["require_design"] = require_design
        return True

    monkeypatch.setattr(implement_issue, "implement_single_issue", fake_single)

    implement_issue.main()
    assert captured["require_design"] is True


def test_main_require_design_flag_threads_to_targeted(monkeypatch, tmp_path):
    import sys

    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    monkeypatch.setattr(sys, "argv", ["implement_issue.py", "--issue", "28", "--require-design"])
    monkeypatch.setattr(implement_issue, "cleanup_merged_labels", lambda: None)
    monkeypatch.setattr(implement_issue, "unblock_ready_issues", lambda: None)

    captured = {}

    def fake_targeted(number, require_design=False):
        captured["number"] = number
        captured["require_design"] = require_design
        return True

    monkeypatch.setattr(implement_issue, "implement_targeted_issue", fake_targeted)

    implement_issue.main()
    assert captured["number"] == 28
    assert captured["require_design"] is True


def test_main_defaults_require_design_false(monkeypatch, tmp_path):
    import sys

    lock_path = tmp_path / ".ai-dlc.lock"
    monkeypatch.setattr(implement_issue, "LOCKFILE", lock_path)
    monkeypatch.setattr(sys, "argv", ["implement_issue.py"])
    monkeypatch.setattr(implement_issue, "cleanup_merged_labels", lambda: None)
    monkeypatch.setattr(implement_issue, "unblock_ready_issues", lambda: None)

    issue = {"number": 1, "title": "One", "body": "", "labels": []}
    served = [issue, None]
    monkeypatch.setattr(implement_issue, "get_top_ready_issue", lambda: served.pop(0))

    captured = {}

    def fake_single(issue, require_design=False):
        captured["require_design"] = require_design
        return True

    monkeypatch.setattr(implement_issue, "implement_single_issue", fake_single)

    implement_issue.main()
    assert captured["require_design"] is False


# --- implement_targeted_issue design gate threading ---


def test_implement_targeted_issue_threads_require_design(monkeypatch, capsys):
    targeted = {"number": 28, "title": "T", "body": "", "labels": []}
    monkeypatch.setattr(implement_issue, "get_issue_by_number", lambda n: targeted)
    monkeypatch.setattr(implement_issue, "dependencies_met", lambda issue: True)

    captured = {}

    def fake_single(issue, require_design=False):
        captured["require_design"] = require_design
        return True

    monkeypatch.setattr(implement_issue, "implement_single_issue", fake_single)

    assert implement_targeted_issue(28, require_design=True) is True
    assert captured["require_design"] is True


# --- create_pr assignee tests ---


def _capture_pr_run(monkeypatch):
    """Patch subprocess.run to capture the gh pr create command."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    return calls


def test_create_pr_assigns_default_reviewer(monkeypatch):
    monkeypatch.setattr(implement_issue, "PR_REVIEWER", "andywidjaja")
    calls = _capture_pr_run(monkeypatch)

    create_pr({"number": 42, "title": "Add feature", "body": "## Type\nfeature"}, "ai-dlc/42-x")

    pr_calls = [c for c in calls if c[:3] == ["gh", "pr", "create"]]
    assert len(pr_calls) == 1
    cmd = pr_calls[0]
    assert "--assignee" in cmd
    assert cmd[cmd.index("--assignee") + 1] == "andywidjaja"


def test_create_pr_assigns_override_reviewer(monkeypatch):
    monkeypatch.setattr(implement_issue, "PR_REVIEWER", "otheruser")
    calls = _capture_pr_run(monkeypatch)

    create_pr({"number": 7, "title": "Fix bug", "body": "## Type\nbug"}, "ai-dlc/7-x")

    pr_calls = [c for c in calls if c[:3] == ["gh", "pr", "create"]]
    cmd = pr_calls[0]
    assert cmd[cmd.index("--assignee") + 1] == "otheruser"


def test_pr_reviewer_defaults_to_andywidjaja(monkeypatch):
    monkeypatch.delenv("PATINA_AIDLC_REVIEWER", raising=False)
    reloaded = importlib.reload(implement_issue)
    try:
        assert reloaded.PR_REVIEWER == "andywidjaja"
    finally:
        importlib.reload(implement_issue)


def test_pr_reviewer_reads_env_override(monkeypatch):
    monkeypatch.setenv("PATINA_AIDLC_REVIEWER", "otheruser")
    reloaded = importlib.reload(implement_issue)
    try:
        assert reloaded.PR_REVIEWER == "otheruser"
    finally:
        monkeypatch.delenv("PATINA_AIDLC_REVIEWER", raising=False)
        importlib.reload(implement_issue)


# --- post_in_progress_comment tests ---


def test_post_in_progress_comment_posts_to_issue(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)

    post_in_progress_comment(42)

    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[:4] == ["gh", "issue", "comment", "42"]
    body = cmd[cmd.index("--body") + 1]
    assert "bot" in body.lower()


def test_implement_single_issue_posts_in_progress_comment(monkeypatch, tmp_path):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)

    posted = []
    monkeypatch.setattr(implement_issue, "post_in_progress_comment", lambda n: posted.append(n))
    monkeypatch.setattr(implement_issue, "create_branch", lambda issue: "ai-dlc/42-x")
    monkeypatch.setattr(implement_issue, "create_pr", lambda *a, **kw: None)
    monkeypatch.setattr(implement_issue, "label_in_review", lambda n: None)
    monkeypatch.setattr(
        implement_issue, "implement", lambda issue, previous_errors=None: _claude_result()
    )
    monkeypatch.setattr(implement_issue, "verify_implementation", lambda branch: (True, ""))
    monkeypatch.setattr(implement_issue, "review_implementation", lambda issue, branch: (True, ""))
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    implement_single_issue(_FAKE_ISSUE)

    assert posted == [42]


# --- parse_review_response tests ---


def test_parse_review_response_approved():
    approved, feedback = parse_review_response(
        '{"approved": true, "issues": [], "summary": "looks good"}'
    )
    assert approved is True
    assert feedback == "looks good"


def test_parse_review_response_rejected_lists_issues():
    approved, feedback = parse_review_response(
        '{"approved": false, "issues": ["missing test", "wrong pattern"], "summary": "no"}'
    )
    assert approved is False
    assert "missing test" in feedback
    assert "wrong pattern" in feedback


def test_parse_review_response_strips_code_fence():
    text = '```json\n{"approved": true, "issues": [], "summary": "ok"}\n```'
    approved, feedback = parse_review_response(text)
    assert approved is True
    assert feedback == "ok"


def test_parse_review_response_non_json_is_failure():
    approved, feedback = parse_review_response("this is not json at all")
    assert approved is False
    assert "not valid JSON" in feedback


def test_parse_review_response_malformed_missing_approved():
    approved, feedback = parse_review_response('{"summary": "no approved field"}')
    assert approved is False
    assert "malformed" in feedback


def test_parse_review_response_rejected_without_issues_uses_summary():
    approved, feedback = parse_review_response(
        '{"approved": false, "issues": [], "summary": "nope"}'
    )
    assert approved is False
    assert feedback == "nope"


# --- review_implementation tests ---


def _review_fake_run(diff_stdout, review_json, captured=None):
    """A single subprocess.run fake that serves both git diff and claude.

    implement_issue and claude_runner share the same subprocess module, so one
    fake must dispatch on the command. Captures the claude command in `captured`.
    """

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "git":
            if captured is not None:
                captured["diff_cmd"] = cmd
            return type("R", (), {"returncode": 0, "stdout": diff_stdout, "stderr": ""})()
        if captured is not None:
            captured["claude_cmd"] = cmd
        return _json_result(review_json)

    return fake_run


def test_review_implementation_prompt_includes_issue_and_diff(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        _review_fake_run(
            "DIFF_CONTENT", '{"approved": true, "issues": [], "summary": "ok"}', captured
        ),
    )

    issue = {"number": 31, "title": "Add review step", "body": "Issue body text"}
    review_implementation(issue, "ai-dlc/31-add-review-step")

    prompt = captured["claude_cmd"][-1]
    assert "Issue #31: Add review step" in prompt
    assert "Issue body text" in prompt
    assert "DIFF_CONTENT" in prompt


def test_review_implementation_truncates_diff_to_8000(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        _review_fake_run(
            "d" * 20000, '{"approved": true, "issues": [], "summary": "ok"}', captured
        ),
    )

    review_implementation({"number": 1, "title": "T", "body": ""}, "branch")

    prompt = captured["claude_cmd"][-1]
    assert "d" * 8000 in prompt
    assert "d" * 8001 not in prompt


def test_review_implementation_runs_git_diff_main_to_branch(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        _review_fake_run("", '{"approved": true, "issues": [], "summary": "ok"}', captured),
    )

    review_implementation({"number": 1, "title": "T", "body": ""}, "ai-dlc/1-x")
    assert captured["diff_cmd"] == ["git", "diff", "main..ai-dlc/1-x"]


def test_review_implementation_approved(monkeypatch):
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        _review_fake_run("diff", '{"approved": true, "issues": [], "summary": "great"}'),
    )
    approved, feedback = review_implementation({"number": 1, "title": "T", "body": ""}, "branch")
    assert approved is True
    assert feedback == "great"


def test_review_implementation_rejected_returns_feedback(monkeypatch):
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        _review_fake_run("diff", '{"approved": false, "issues": ["stub test"], "summary": "bad"}'),
    )
    approved, feedback = review_implementation({"number": 1, "title": "T", "body": ""}, "branch")
    assert approved is False
    assert "stub test" in feedback


def test_review_implementation_treats_claude_failure_as_review_failure(monkeypatch):
    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "git":
            return type("R", (), {"returncode": 0, "stdout": "diff", "stderr": ""})()
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    approved, feedback = review_implementation({"number": 1, "title": "T", "body": ""}, "branch")
    assert approved is False
    assert "failed" in feedback.lower()


def test_review_implementation_handles_missing_body(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        _review_fake_run("diff", '{"approved": true, "issues": [], "summary": "ok"}', captured),
    )
    # A None body must not raise.
    review_implementation({"number": 5, "title": "No body", "body": None}, "branch")
    assert "No body" in captured["claude_cmd"][-1]


# --- Review step integration into the retry loop ---


def test_failed_review_triggers_retry_with_feedback(monkeypatch, tmp_path):
    """A rejected review re-attempts and feeds review issues into the next try."""
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)

    received_errors = []

    def fake_implement(issue, previous_errors=None):
        received_errors.append(previous_errors)
        return _claude_result()

    monkeypatch.setattr(implement_issue, "implement", fake_implement)
    monkeypatch.setattr(implement_issue, "create_branch", lambda issue: "ai-dlc/42-test")
    monkeypatch.setattr(implement_issue, "cleanup_branch", lambda branch: None)
    monkeypatch.setattr(implement_issue, "post_attempt_failure", lambda n, a, e: None)
    monkeypatch.setattr(implement_issue, "create_pr", lambda *a, **kw: None)
    monkeypatch.setattr(implement_issue, "label_in_review", lambda n: None)
    # Verification always passes; the review gates the first attempt.
    monkeypatch.setattr(implement_issue, "verify_implementation", lambda branch: (True, ""))

    review_calls = [0]

    def fake_review(issue, branch):
        review_calls[0] += 1
        if review_calls[0] < 2:
            return False, "Review found issues:\n- tests are stubs"
        return True, "approved"

    monkeypatch.setattr(implement_issue, "review_implementation", fake_review)
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    assert implement_single_issue(_FAKE_ISSUE) is True
    # First attempt had no prior errors; the retry received the review feedback.
    assert received_errors[0] is None
    assert received_errors[1] == "Review found issues:\n- tests are stubs"
    assert review_calls[0] == 2


def test_failed_review_all_attempts_labels_needs_human(monkeypatch, tmp_path):
    """When every review rejects, the issue is flagged needs-human and no PR opens."""
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)
    gh_calls = []

    def fake_run(cmd, **kwargs):
        if cmd and cmd[0] == "gh":
            gh_calls.append(cmd)
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(implement_issue.subprocess, "run", fake_run)
    monkeypatch.setattr(
        implement_issue, "implement", lambda issue, previous_errors=None: _claude_result()
    )
    monkeypatch.setattr(implement_issue, "create_branch", lambda issue: "ai-dlc/42-test")
    monkeypatch.setattr(implement_issue, "cleanup_branch", lambda branch: None)
    monkeypatch.setattr(implement_issue, "post_attempt_failure", lambda n, a, e: None)
    monkeypatch.setattr(implement_issue, "verify_implementation", lambda branch: (True, ""))

    pr_calls = []
    monkeypatch.setattr(implement_issue, "create_pr", lambda *a, **kw: pr_calls.append(True))
    monkeypatch.setattr(
        implement_issue, "review_implementation", lambda issue, branch: (False, "still bad")
    )

    assert implement_single_issue(_FAKE_ISSUE) is False
    assert pr_calls == []
    assert [c for c in gh_calls if "needs-human" in c], "Expected needs-human label"


def test_passed_review_creates_pr(monkeypatch, tmp_path):
    """A passing review lets the flow reach PR creation."""
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(implement_issue, "LOG_FILE", log_path)

    monkeypatch.setattr(
        implement_issue, "implement", lambda issue, previous_errors=None: _claude_result()
    )
    monkeypatch.setattr(implement_issue, "create_branch", lambda issue: "ai-dlc/42-test")
    monkeypatch.setattr(implement_issue, "verify_implementation", lambda branch: (True, ""))
    monkeypatch.setattr(implement_issue, "label_in_review", lambda n: None)

    review_seen = []

    def fake_review(issue, branch):
        review_seen.append(branch)
        return True, "approved"

    monkeypatch.setattr(implement_issue, "review_implementation", fake_review)

    pr_calls = []
    monkeypatch.setattr(implement_issue, "create_pr", lambda *a, **kw: pr_calls.append(True))
    monkeypatch.setattr(
        implement_issue.subprocess,
        "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    assert implement_single_issue(_FAKE_ISSUE) is True
    assert review_seen == ["ai-dlc/42-test"]
    assert pr_calls == [True]
