from __future__ import annotations

import importlib
import json

import claude_runner
import triage_issues
from claude_runner import ClaudeResult
from triage_issues import (
    build_decomposition_comment,
    log_run,
    parse_file_discovery_response,
    parse_triage_response,
    triage_issue,
    validate_discovered_files,
)


def _cr(cost_usd=0.02, input_tokens=2000, output_tokens=60, cache_read_tokens=16000, success=True):
    """Build a ClaudeResult for mocking run_claude()."""
    return ClaudeResult(
        text="",
        cost_usd=cost_usd,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        success=success,
    )


# --- Pure function tests: parse_triage_response ---


def test_parse_triage_response_plain_json():
    raw = '{"verdict":"ready","points":1,"priority":"p1","reason":"ok","files_missing":false}'
    result = parse_triage_response(raw)
    assert result["verdict"] == "ready"
    assert result["points"] == 1


def test_parse_triage_response_markdown_fenced():
    raw = (
        "Here is my analysis:\n```json\n"
        '{"verdict":"ready","points":2,"priority":"p2","reason":"good"}\n```'
    )
    result = parse_triage_response(raw)
    assert result["verdict"] == "ready"
    assert result["points"] == 2


def test_parse_triage_response_invalid_returns_rejected():
    result = parse_triage_response("I can't evaluate this issue properly.")
    assert result["verdict"] == "rejected"
    assert "Failed to parse" in result["reason"]


def test_parse_triage_response_empty_string():
    result = parse_triage_response("")
    assert result["verdict"] == "rejected"


# --- Pure function tests: parse_file_discovery_response ---


def test_parse_file_discovery_plain_json():
    raw = '{"files_to_modify": [{"path": "src/patina/store.py", "reason": "schema"}]}'
    files = parse_file_discovery_response(raw)
    assert len(files) == 1
    assert files[0]["path"] == "src/patina/store.py"


def test_parse_file_discovery_markdown_fenced():
    raw = '```json\n{"files_to_modify": [{"path": "src/x.py", "reason": "x"}]}\n```'
    files = parse_file_discovery_response(raw)
    assert len(files) == 1


def test_parse_file_discovery_invalid_returns_empty():
    assert parse_file_discovery_response("no json here") == []


# --- Pure function tests: validate_discovered_files ---


def test_validate_filters_missing_files(tmp_path):
    (tmp_path / "src" / "patina").mkdir(parents=True)
    (tmp_path / "src" / "patina" / "store.py").touch()
    files = [
        {"path": "src/patina/store.py", "reason": "exists"},
        {"path": "src/patina/nonexistent.py", "reason": "gone"},
    ]
    result = validate_discovered_files(files, tmp_path)
    assert len(result) == 1
    assert result[0]["path"] == "src/patina/store.py"


def test_validate_allows_new_test_files(tmp_path):
    files = [{"path": "tests/test_new.py", "reason": "new test"}]
    result = validate_discovered_files(files, tmp_path)
    assert len(result) == 1


# --- Pure function tests: build_decomposition_comment ---


def test_build_decomposition_comment_format():
    result = {
        "points": 5,
        "decomposition": [
            {
                "order": 1,
                "title": "Add tables",
                "points": 1,
                "depends_on": [],
                "files": ["store.py"],
                "why_first": "Schema must exist first",
            },
            {
                "order": 2,
                "title": "Add tools",
                "points": 2,
                "depends_on": [1],
                "files": ["tools.py"],
                "why_after": "Tools use tables from step 1",
            },
        ],
    }
    comment = build_decomposition_comment(result)
    assert "Estimated at 5 points" in comment
    assert "| Order | Sub-issue | Pts | Depends on | Files |" in comment
    assert "| 1 | Add tables | 1 |" in comment
    assert "Step 1" in comment
    assert "**Why this order:**" in comment
    assert "Schema must exist first" in comment
    assert "Tools use tables from step 1" in comment


def test_build_decomposition_comment_single_step():
    result = {
        "points": 3,
        "decomposition": [
            {
                "order": 1,
                "title": "Do the thing",
                "points": 3,
                "depends_on": [],
                "files": ["a.py", "b.py"],
                "why_first": "Only step",
            },
        ],
    }
    comment = build_decomposition_comment(result)
    assert "| 1 | Do the thing | 3 | — |" in comment
    assert "`a.py`, `b.py`" in comment


# --- Orchestrator tests: triage_issue ---


def _make_issue(number=42, title="Add flag", body="## Summary\nAdd a flag"):
    return {"number": number, "title": title, "body": body}


def test_triage_issue_ready_approves(monkeypatch):
    verdict = {"verdict": "ready", "priority": "p1", "reason": "ok", "files_missing": False}
    calls = []
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: (verdict, _cr()))
    monkeypatch.setattr(
        triage_issues,
        "approve_issue",
        lambda n, p, r: calls.append(("approve", n, p)),
    )
    monkeypatch.setattr(triage_issues, "discover_files", lambda i: ([], _cr()))
    monkeypatch.setattr(triage_issues, "enrich_issue_with_files", lambda n, f: None)

    triage_issue(_make_issue())
    assert ("approve", 42, "p1") in calls


def test_triage_issue_rejected(monkeypatch):
    verdict = {"verdict": "rejected", "reason": "incomplete"}
    calls = []
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: (verdict, _cr()))
    monkeypatch.setattr(triage_issues, "reject_issue", lambda n, r: calls.append(("reject", n, r)))

    triage_issue(_make_issue())
    assert ("reject", 42, "incomplete") in calls


def test_triage_issue_needs_decomposition(monkeypatch):
    verdict = {
        "verdict": "needs-decomposition",
        "points": 5,
        "reason": "big",
        "files_missing": False,
        "decomposition": [
            {
                "order": 1,
                "title": "Step 1",
                "points": 2,
                "depends_on": [],
                "files": ["a.py"],
            }
        ],
    }
    calls = []
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: (verdict, _cr()))
    monkeypatch.setattr(
        triage_issues,
        "decompose_issue",
        lambda n, r: calls.append(("decompose", n)),
    )

    triage_issue(_make_issue())
    assert ("decompose", 42) in calls


def test_triage_issue_discovers_files_when_missing(monkeypatch):
    verdict = {"verdict": "ready", "priority": "p2", "reason": "ok", "files_missing": True}
    discovered = [{"path": "src/patina/store.py", "reason": "schema"}]
    enriched = []
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: (verdict, _cr()))
    monkeypatch.setattr(triage_issues, "discover_files", lambda i: (discovered, _cr()))
    monkeypatch.setattr(
        triage_issues,
        "enrich_issue_with_files",
        lambda n, f: enriched.append((n, f)),
    )
    monkeypatch.setattr(triage_issues, "approve_issue", lambda n, p, r: None)

    triage_issue(_make_issue())
    assert len(enriched) == 1
    assert enriched[0] == (42, discovered)


def test_triage_issue_skips_enrich_when_no_files_found(monkeypatch):
    verdict = {"verdict": "ready", "priority": "p2", "reason": "ok", "files_missing": True}
    enriched = []
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: (verdict, _cr()))
    monkeypatch.setattr(triage_issues, "discover_files", lambda i: ([], _cr()))
    monkeypatch.setattr(
        triage_issues,
        "enrich_issue_with_files",
        lambda n, f: enriched.append((n, f)),
    )
    monkeypatch.setattr(triage_issues, "approve_issue", lambda n, p, r: None)

    triage_issue(_make_issue())
    assert len(enriched) == 0


# --- triage_issue result-accumulation tests ---


def test_triage_issue_returns_1_result_for_rejected(monkeypatch):
    verdict = {"verdict": "rejected", "reason": "incomplete"}
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: (verdict, _cr()))
    monkeypatch.setattr(triage_issues, "reject_issue", lambda n, r: None)

    results = triage_issue(_make_issue())
    assert len(results) == 1
    assert all(isinstance(r, ClaudeResult) for r in results)


def test_triage_issue_returns_1_result_for_ready_no_file_discovery(monkeypatch):
    verdict = {"verdict": "ready", "priority": "p1", "reason": "ok", "files_missing": False}
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: (verdict, _cr()))
    monkeypatch.setattr(triage_issues, "approve_issue", lambda n, p, r: None)

    assert len(triage_issue(_make_issue())) == 1


def test_triage_issue_returns_2_results_when_files_missing(monkeypatch):
    verdict = {"verdict": "ready", "priority": "p1", "reason": "ok", "files_missing": True}
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: (verdict, _cr()))
    monkeypatch.setattr(
        triage_issues,
        "discover_files",
        lambda i: ([{"path": "tests/test_x.py", "reason": "x"}], _cr()),
    )
    monkeypatch.setattr(triage_issues, "enrich_issue_with_files", lambda n, f: None)
    monkeypatch.setattr(triage_issues, "approve_issue", lambda n, p, r: None)

    assert len(triage_issue(_make_issue())) == 2


def test_triage_issue_returns_2_results_when_files_missing_but_none_found(monkeypatch):
    verdict = {"verdict": "ready", "priority": "p1", "reason": "ok", "files_missing": True}
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: (verdict, _cr()))
    monkeypatch.setattr(triage_issues, "discover_files", lambda i: ([], _cr()))
    monkeypatch.setattr(triage_issues, "enrich_issue_with_files", lambda n, f: None)
    monkeypatch.setattr(triage_issues, "approve_issue", lambda n, p, r: None)

    assert len(triage_issue(_make_issue())) == 2


def test_triage_issue_accumulates_token_data(monkeypatch):
    verdict = {"verdict": "ready", "priority": "p1", "reason": "ok", "files_missing": True}
    monkeypatch.setattr(
        triage_issues,
        "evaluate_issue",
        lambda i: (verdict, _cr(cost_usd=0.02, input_tokens=2000, output_tokens=60)),
    )
    monkeypatch.setattr(
        triage_issues,
        "discover_files",
        lambda i: ([], _cr(cost_usd=0.03, input_tokens=3000, output_tokens=90)),
    )
    monkeypatch.setattr(triage_issues, "enrich_issue_with_files", lambda n, f: None)
    monkeypatch.setattr(triage_issues, "approve_issue", lambda n, p, r: None)

    results = triage_issue(_make_issue())
    assert sum(r.cost_usd for r in results) == 0.05
    assert sum(r.input_tokens for r in results) == 5000
    assert sum(r.output_tokens for r in results) == 150


# --- log_run tests ---


def test_log_run_triage_writes_json_entry(tmp_path, monkeypatch):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(triage_issues, "LOG_FILE", log_path)
    log_run(0, True, 3, 45.0, 0.09, 5000, 150, 16000)

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["issue"] == 0
    assert entry["success"] is True
    assert entry["attempts"] == 3
    assert entry["duration_seconds"] == 45
    assert entry["cost_usd"] == 0.09
    assert entry["input_tokens"] == 5000
    assert entry["output_tokens"] == 150
    assert entry["cache_read_tokens"] == 16000
    assert "timestamp" in entry


def test_log_run_triage_appends_multiple_entries(tmp_path, monkeypatch):
    log_path = tmp_path / "run_history.jsonl"
    monkeypatch.setattr(triage_issues, "LOG_FILE", log_path)
    log_run(0, True, 2, 30.0, 0.06)
    log_run(0, True, 5, 90.0, 0.15)

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["attempts"] == 2
    assert json.loads(lines[1])["attempts"] == 5


# --- TRIAGE_MODEL env var tests ---


def test_evaluate_issue_uses_triage_model(monkeypatch):
    captured = {}

    stdout = json.dumps({"result": '{"verdict":"ready"}'})

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": stdout})()

    monkeypatch.setattr(triage_issues, "TRIAGE_MODEL", "opus")
    monkeypatch.setattr(claude_runner.subprocess, "run", fake_run)

    verdict, result = triage_issues.evaluate_issue({"number": 1, "title": "T", "body": "B"})

    assert "--model" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == "opus"
    assert "--output-format" in captured["cmd"]
    assert isinstance(result, ClaudeResult)


def test_discover_files_uses_triage_model(monkeypatch, tmp_path):
    captured = {}

    def fake_find(cmd, **kwargs):
        # `find` for the project tree runs via triage_issues.subprocess
        return type("R", (), {"returncode": 0, "stdout": ""})()

    claude_stdout = json.dumps({"result": '{"files_to_modify": []}'})

    def fake_claude(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": claude_stdout})()

    monkeypatch.setattr(triage_issues, "TRIAGE_MODEL", "haiku")
    monkeypatch.setattr(triage_issues.subprocess, "run", fake_find)
    monkeypatch.setattr(claude_runner.subprocess, "run", fake_claude)
    monkeypatch.setattr(triage_issues, "REPO_DIR", tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# CLAUDE")

    files, result = triage_issues.discover_files({"number": 1, "title": "T", "body": "B"})

    assert "--model" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--model") + 1] == "haiku"
    assert isinstance(result, ClaudeResult)


def test_triage_model_default_from_env(monkeypatch):
    monkeypatch.delenv("PATINA_AIDLC_TRIAGE_MODEL", raising=False)
    importlib.reload(triage_issues)
    assert triage_issues.TRIAGE_MODEL == "sonnet"


def test_triage_model_override_from_env(monkeypatch):
    monkeypatch.setenv("PATINA_AIDLC_TRIAGE_MODEL", "opus")
    importlib.reload(triage_issues)
    assert triage_issues.TRIAGE_MODEL == "opus"
