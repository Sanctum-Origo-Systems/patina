from __future__ import annotations

import importlib
import json

import claude_runner
import triage_issues
from claude_runner import ClaudeResult
from triage_issues import (
    apply_rewrite,
    build_decomposition_comment,
    build_sub_issue_summary_comment,
    create_sub_issues,
    decompose_issue,
    log_run,
    parse_file_discovery_response,
    parse_rewritten_body,
    parse_sub_issue_response,
    parse_triage_response,
    rewrite_issue_body,
    suggest_sub_issue_fields,
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


def _cr_text(text, success=True):
    """Build a successful ClaudeResult carrying a text payload."""
    return ClaudeResult(
        text=text,
        cost_usd=0.01,
        input_tokens=100,
        output_tokens=20,
        cache_read_tokens=0,
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


# --- build_sub_issue_summary_comment tests ---


def test_build_sub_issue_summary_comment_lists_numbers():
    comment = build_sub_issue_summary_comment(42, [101, 102])
    assert "Decomposed #42 into 2 sub-issue(s)" in comment
    assert "- #101" in comment
    assert "- #102" in comment


# --- create_sub_issues tests ---


class _FakeProc:
    def __init__(self, returncode, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def _gh_create_stub(state, fail_titles=()):
    """subprocess.run stub that mints incrementing issue URLs for gh create."""

    def run(cmd, **kwargs):
        title = cmd[cmd.index("--title") + 1]
        body = cmd[cmd.index("--body") + 1]
        if title in fail_titles:
            return _FakeProc(1, "")
        state["n"] += 1
        num = 100 + state["n"]
        state["calls"].append({"title": title, "body": body, "number": num})
        return _FakeProc(0, f"https://github.com/owner/repo/issues/{num}\n")

    return run


def test_create_sub_issues_returns_numbers_in_order(monkeypatch):
    result = {
        "decomposition": [
            {"order": 1, "title": "Step 1", "points": 2, "depends_on": [], "files": ["a.py"]},
            {"order": 2, "title": "Step 2", "points": 1, "depends_on": [1], "files": ["b.py"]},
        ]
    }
    state = {"n": 0, "calls": []}
    monkeypatch.setattr(triage_issues, "suggest_sub_issue_fields", lambda *a, **k: None)
    monkeypatch.setattr(triage_issues.subprocess, "run", _gh_create_stub(state))

    created = create_sub_issues(42, result)
    assert created == [101, 102]


def test_create_sub_issues_body_has_parent_hint_and_deps(monkeypatch):
    result = {
        "decomposition": [
            {"order": 1, "title": "Step 1", "points": 2, "depends_on": [], "files": ["a.py"]},
            {"order": 2, "title": "Step 2", "points": 1, "depends_on": [1], "files": ["b.py"]},
        ]
    }
    state = {"n": 0, "calls": []}
    monkeypatch.setattr(triage_issues, "suggest_sub_issue_fields", lambda *a, **k: None)
    monkeypatch.setattr(triage_issues.subprocess, "run", _gh_create_stub(state))

    create_sub_issues(42, result)

    first_body = state["calls"][0]["body"]
    second_body = state["calls"][1]["body"]
    assert "Sub-issue of #42" in first_body
    assert "Parent issue: #42" in first_body
    # First step has no deps; second depends on the already-created first (#101).
    assert "Depends on:" not in first_body
    assert "Depends on: #101" in second_body


def test_create_sub_issues_skips_unmet_dependency(monkeypatch):
    # depends_on references a step that has not been created yet (or at all).
    result = {
        "decomposition": [
            {"order": 1, "title": "Step 1", "points": 2, "depends_on": [9], "files": []},
        ]
    }
    state = {"n": 0, "calls": []}
    monkeypatch.setattr(triage_issues, "suggest_sub_issue_fields", lambda *a, **k: None)
    monkeypatch.setattr(triage_issues.subprocess, "run", _gh_create_stub(state))

    create_sub_issues(42, result)
    assert "Depends on:" not in state["calls"][0]["body"]


def test_create_sub_issues_omits_failed_creations(monkeypatch):
    result = {
        "decomposition": [
            {"order": 1, "title": "Good", "points": 1, "depends_on": [], "files": []},
            {"order": 2, "title": "Bad", "points": 1, "depends_on": [], "files": []},
        ]
    }
    state = {"n": 0, "calls": []}
    monkeypatch.setattr(triage_issues, "suggest_sub_issue_fields", lambda *a, **k: None)
    monkeypatch.setattr(
        triage_issues.subprocess, "run", _gh_create_stub(state, fail_titles={"Bad"})
    )

    created = create_sub_issues(42, result)
    assert created == [101]


# --- parse_sub_issue_response tests ---


def test_parse_sub_issue_response_plain_json():
    raw = '{"expected_behavior":"emits a report","acceptance_criteria":["foo() returns 3"]}'
    fields = parse_sub_issue_response(raw)
    assert fields["expected_behavior"] == "emits a report"
    assert fields["acceptance_criteria"] == ["foo() returns 3"]


def test_parse_sub_issue_response_markdown_fenced():
    raw = (
        "Here you go:\n```json\n"
        '{"expected_behavior":"writes rows to store","acceptance_criteria":["a","b"]}\n```'
    )
    fields = parse_sub_issue_response(raw)
    assert fields["expected_behavior"] == "writes rows to store"
    assert fields["acceptance_criteria"] == ["a", "b"]


def test_parse_sub_issue_response_invalid_json_returns_none():
    assert parse_sub_issue_response("not json at all") is None


def test_parse_sub_issue_response_missing_field_returns_none():
    assert parse_sub_issue_response('{"acceptance_criteria":["a"]}') is None


# --- suggest_sub_issue_fields tests ---


def _step(title="Add design_issue()", files=("a.py",), why_first="foundational"):
    return {
        "order": 1,
        "title": title,
        "points": 2,
        "depends_on": [],
        "files": list(files),
        "why_first": why_first,
    }


def test_suggest_sub_issue_fields_returns_none_without_claude(monkeypatch):
    monkeypatch.setattr(triage_issues.shutil, "which", lambda name: None)
    assert suggest_sub_issue_fields(42, "parent summary", _step()) is None


def test_suggest_sub_issue_fields_parses_claude_json(monkeypatch):
    monkeypatch.setattr(triage_issues.shutil, "which", lambda name: "/usr/bin/claude")
    payload = '{"expected_behavior":"prints a table","acceptance_criteria":["render() emits rows"]}'
    monkeypatch.setattr(triage_issues, "run_claude", lambda *a, **k: _cr_text(payload))

    fields = suggest_sub_issue_fields(42, "parent summary", _step())
    assert fields["expected_behavior"] == "prints a table"
    assert fields["acceptance_criteria"] == ["render() emits rows"]


def test_suggest_sub_issue_fields_returns_none_on_failed_call(monkeypatch):
    monkeypatch.setattr(triage_issues.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(triage_issues, "run_claude", lambda *a, **k: _cr(success=False))
    assert suggest_sub_issue_fields(42, "parent summary", _step()) is None


def test_suggest_sub_issue_fields_returns_none_on_bad_json(monkeypatch):
    monkeypatch.setattr(triage_issues.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(triage_issues, "run_claude", lambda *a, **k: _cr_text("garbage"))
    assert suggest_sub_issue_fields(42, "parent summary", _step()) is None


def test_suggest_sub_issue_fields_prompt_includes_context(monkeypatch):
    captured = {}
    monkeypatch.setattr(triage_issues.shutil, "which", lambda name: "/usr/bin/claude")

    def fake_run_claude(prompt, model, timeout):
        captured["prompt"] = prompt
        return _cr_text('{"expected_behavior":"x","acceptance_criteria":[]}')

    monkeypatch.setattr(triage_issues, "run_claude", fake_run_claude)
    suggest_sub_issue_fields(42, "Ship the widget", _step(title="Wire the button"))

    assert "#42" in captured["prompt"]
    assert "Ship the widget" in captured["prompt"]
    assert "Wire the button" in captured["prompt"]
    assert "foundational" in captured["prompt"]


# --- create_sub_issues LLM enrichment tests ---


def test_create_sub_issues_uses_llm_fields_in_body(monkeypatch):
    result = {
        "decomposition": [
            {"order": 1, "title": "Step 1", "points": 2, "depends_on": [], "files": ["a.py"]},
        ]
    }
    state = {"n": 0, "calls": []}
    monkeypatch.setattr(
        triage_issues,
        "suggest_sub_issue_fields",
        lambda *a, **k: {
            "expected_behavior": "render() returns a formatted table string",
            "acceptance_criteria": [
                "render([]) returns an empty string",
                "render(rows) has a header",
            ],
        },
    )
    monkeypatch.setattr(triage_issues.subprocess, "run", _gh_create_stub(state))

    create_sub_issues(42, result, "parent summary")

    body = state["calls"][0]["body"]
    assert "render() returns a formatted table string" in body
    assert "Step 1" not in body.split("## Expected Behavior")[1].split("##")[0]
    assert "render([]) returns an empty string" in body
    assert "render(rows) has a header" in body


def test_create_sub_issues_falls_back_to_title_on_none(monkeypatch):
    result = {
        "decomposition": [
            {"order": 1, "title": "Step 1", "points": 2, "depends_on": [], "files": ["a.py"]},
        ]
    }
    state = {"n": 0, "calls": []}
    monkeypatch.setattr(triage_issues, "suggest_sub_issue_fields", lambda *a, **k: None)
    monkeypatch.setattr(triage_issues.subprocess, "run", _gh_create_stub(state))

    create_sub_issues(42, result, "parent summary")

    expected_section = state["calls"][0]["body"].split("## Expected Behavior")[1].split("##")[0]
    assert "Step 1" in expected_section


# --- decompose_issue tests ---


def test_decompose_issue_labels_and_posts_summary(monkeypatch):
    result = {
        "points": 5,
        "decomposition": [
            {"order": 1, "title": "Step 1", "points": 2, "depends_on": [], "files": ["a.py"]},
        ],
    }
    calls = []
    monkeypatch.setattr(triage_issues, "create_sub_issues", lambda n, r, s="": [101, 102])
    monkeypatch.setattr(
        triage_issues.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or _FakeProc(0)
    )

    decompose_issue(42, result)

    joined = [" ".join(c) for c in calls]
    assert any("--add-label needs-decomposition" in c for c in joined)
    summary_calls = [c for c in calls if "issue" in c and "comment" in c]
    bodies = [c[c.index("--body") + 1] for c in summary_calls]
    assert any("#101" in b and "#102" in b for b in bodies)


def test_decompose_issue_skips_summary_when_no_sub_issues(monkeypatch):
    result = {"points": 5, "decomposition": []}
    calls = []
    monkeypatch.setattr(triage_issues, "create_sub_issues", lambda n, r, s="": [])
    monkeypatch.setattr(
        triage_issues.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or _FakeProc(0)
    )

    decompose_issue(42, result)

    bodies = [c[c.index("--body") + 1] for c in calls if "--body" in c]
    assert not any("Sub-issues created" in b for b in bodies)


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

    # auto_fix=False models the re-triage pass: a rejection is final.
    triage_issue(_make_issue(), auto_fix=False)
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
        lambda n, r, s="": calls.append(("decompose", n)),
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

    results = triage_issue(_make_issue(), auto_fix=False)
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


# --- parse_rewritten_body tests ---


def test_parse_rewritten_body_plain_markdown():
    raw = "## Summary\nAdd a flag\n\n## Expected Behavior\nEmits a report"
    assert parse_rewritten_body(raw) == raw


def test_parse_rewritten_body_strips_wrapping_fence():
    raw = "```markdown\n## Summary\nAdd a flag\n\n## Expected Behavior\nx\n```"
    result = parse_rewritten_body(raw)
    assert result == "## Summary\nAdd a flag\n\n## Expected Behavior\nx"


def test_parse_rewritten_body_strips_bare_fence():
    raw = "```\n## Summary\nAdd a flag\n```"
    assert parse_rewritten_body(raw) == "## Summary\nAdd a flag"


def test_parse_rewritten_body_without_header_returns_none():
    assert parse_rewritten_body("I could not rewrite this issue.") is None


def test_parse_rewritten_body_empty_returns_none():
    assert parse_rewritten_body("") is None


# --- rewrite_issue_body tests ---


def test_rewrite_issue_body_parses_claude_output(monkeypatch):
    body = "## Summary\nfixed\n\n## Expected Behavior\nEmits rows"
    monkeypatch.setattr(triage_issues, "run_claude", lambda *a, **k: _cr_text(body))

    new_body, result = rewrite_issue_body(_make_issue(), "vague expected behavior")
    assert new_body == body
    assert isinstance(result, ClaudeResult)


def test_rewrite_issue_body_prompt_includes_reason_and_body(monkeypatch):
    captured = {}

    def fake_run_claude(prompt, model, timeout):
        captured["prompt"] = prompt
        return _cr_text("## Summary\nx\n\n## Expected Behavior\ny")

    monkeypatch.setattr(triage_issues, "run_claude", fake_run_claude)
    issue = _make_issue(body="## Summary\noriginal body here")
    rewrite_issue_body(issue, "Acceptance Criteria missing checkbox")

    assert "Acceptance Criteria missing checkbox" in captured["prompt"]
    assert "original body here" in captured["prompt"]


def test_rewrite_issue_body_returns_none_on_failed_call(monkeypatch):
    monkeypatch.setattr(triage_issues, "run_claude", lambda *a, **k: _cr(success=False))
    new_body, result = rewrite_issue_body(_make_issue(), "reason")
    assert new_body is None
    assert result.success is False


def test_rewrite_issue_body_returns_none_on_unusable_output(monkeypatch):
    monkeypatch.setattr(triage_issues, "run_claude", lambda *a, **k: _cr_text("sorry, cannot"))
    new_body, _ = rewrite_issue_body(_make_issue(), "reason")
    assert new_body is None


# --- triage_issue auto-fix tests ---


def _sequenced_evaluate(verdicts):
    """Return an evaluate_issue stub that yields verdicts in order plus a counter."""
    state = {"n": 0}

    def evaluate(issue):
        verdict = verdicts[min(state["n"], len(verdicts) - 1)]
        state["n"] += 1
        return verdict, _cr()

    return evaluate, state


def test_triage_issue_auto_fix_rewrites_and_reapproves(monkeypatch):
    verdicts = [
        {"verdict": "rejected", "reason": "vague expected behavior"},
        {"verdict": "ready", "priority": "p2", "reason": "ok", "files_missing": False},
    ]
    evaluate, state = _sequenced_evaluate(verdicts)
    new_body = "## Summary\nfixed\n\n## Expected Behavior\nEmits rows"
    applied = []
    approved = []
    rejected = []
    monkeypatch.setattr(triage_issues, "evaluate_issue", evaluate)
    monkeypatch.setattr(triage_issues, "rewrite_issue_body", lambda i, r: (new_body, _cr()))
    monkeypatch.setattr(triage_issues, "apply_rewrite", lambda n, b: applied.append((n, b)))
    monkeypatch.setattr(triage_issues, "approve_issue", lambda n, p, r: approved.append((n, p)))
    monkeypatch.setattr(triage_issues, "reject_issue", lambda n, r: rejected.append(n))

    results = triage_issue(_make_issue())

    # Re-triage happens exactly once (two evaluate calls total).
    assert state["n"] == 2
    # Issue body updated with the rewritten body before re-triage.
    assert applied == [(42, new_body)]
    # Re-triage saw the rewritten body and approved.
    assert approved == [(42, "p2")]
    assert rejected == []
    # eval + rewrite + re-eval.
    assert len(results) == 3


def test_triage_issue_auto_fix_second_rejection_is_final(monkeypatch):
    verdicts = [
        {"verdict": "rejected", "reason": "first reason"},
        {"verdict": "rejected", "reason": "second reason"},
    ]
    evaluate, state = _sequenced_evaluate(verdicts)
    rewrite_calls = []
    rejected = []
    monkeypatch.setattr(triage_issues, "evaluate_issue", evaluate)
    monkeypatch.setattr(
        triage_issues,
        "rewrite_issue_body",
        lambda i, r: rewrite_calls.append(r) or ("## Summary\nx\n\n## Expected Behavior\ny", _cr()),
    )
    monkeypatch.setattr(triage_issues, "apply_rewrite", lambda n, b: None)
    monkeypatch.setattr(triage_issues, "reject_issue", lambda n, r: rejected.append((n, r)))

    results = triage_issue(_make_issue())

    # Exactly one re-triage and exactly one auto-fix attempt.
    assert state["n"] == 2
    assert rewrite_calls == ["first reason"]
    # The second rejection is final and keeps the rejected label.
    assert rejected == [(42, "second reason")]
    assert len(results) == 3


def test_triage_issue_auto_fix_falls_back_to_reject_when_rewrite_fails(monkeypatch):
    verdict = {"verdict": "rejected", "reason": "incomplete"}
    applied = []
    rejected = []
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: (verdict, _cr()))
    monkeypatch.setattr(triage_issues, "rewrite_issue_body", lambda i, r: (None, _cr()))
    monkeypatch.setattr(triage_issues, "apply_rewrite", lambda n, b: applied.append(n))
    monkeypatch.setattr(triage_issues, "reject_issue", lambda n, r: rejected.append((n, r)))

    results = triage_issue(_make_issue())

    # No update when the rewrite is unusable; the issue is rejected normally.
    assert applied == []
    assert rejected == [(42, "incomplete")]
    # eval + failed rewrite (still counted for cost tracking).
    assert len(results) == 2


def test_triage_issue_no_auto_fix_when_disabled(monkeypatch):
    verdict = {"verdict": "rejected", "reason": "incomplete"}
    rewrite_calls = []
    rejected = []
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: (verdict, _cr()))
    monkeypatch.setattr(
        triage_issues, "rewrite_issue_body", lambda i, r: rewrite_calls.append(r) or (None, _cr())
    )
    monkeypatch.setattr(triage_issues, "reject_issue", lambda n, r: rejected.append((n, r)))

    triage_issue(_make_issue(), auto_fix=False)

    # With auto_fix disabled, no rewrite is attempted.
    assert rewrite_calls == []
    assert rejected == [(42, "incomplete")]


# --- apply_rewrite tests ---


def test_apply_rewrite_edits_body_and_removes_label(monkeypatch):
    calls = []
    monkeypatch.setattr(
        triage_issues.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or _FakeProc(0)
    )

    apply_rewrite(42, "## Summary\nnew body")

    joined = [" ".join(c) for c in calls]
    # Body updated with the rewritten content.
    edit_calls = [c for c in calls if "edit" in c and "--body" in c]
    assert edit_calls[0][edit_calls[0].index("--body") + 1] == "## Summary\nnew body"
    # 'rejected' label removed before re-triage.
    assert any("--remove-label rejected" in c for c in joined)
    # An auto-fix comment is posted.
    comment_calls = [c for c in calls if "comment" in c]
    assert any("Auto-fix" in c[c.index("--body") + 1] for c in comment_calls)


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
