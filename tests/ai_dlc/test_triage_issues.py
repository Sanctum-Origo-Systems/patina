from __future__ import annotations

import triage_issues
from triage_issues import (
    build_decomposition_comment,
    parse_file_discovery_response,
    parse_triage_response,
    triage_issue,
    validate_discovered_files,
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
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: verdict)
    monkeypatch.setattr(
        triage_issues,
        "approve_issue",
        lambda n, p, r: calls.append(("approve", n, p)),
    )
    monkeypatch.setattr(triage_issues, "discover_files", lambda i: [])
    monkeypatch.setattr(triage_issues, "enrich_issue_with_files", lambda n, f: None)

    triage_issue(_make_issue())
    assert ("approve", 42, "p1") in calls


def test_triage_issue_rejected(monkeypatch):
    verdict = {"verdict": "rejected", "reason": "incomplete"}
    calls = []
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: verdict)
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
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: verdict)
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
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: verdict)
    monkeypatch.setattr(triage_issues, "discover_files", lambda i: discovered)
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
    monkeypatch.setattr(triage_issues, "evaluate_issue", lambda i: verdict)
    monkeypatch.setattr(triage_issues, "discover_files", lambda i: [])
    monkeypatch.setattr(
        triage_issues,
        "enrich_issue_with_files",
        lambda n, f: enriched.append((n, f)),
    )
    monkeypatch.setattr(triage_issues, "approve_issue", lambda n, p, r: None)

    triage_issue(_make_issue())
    assert len(enriched) == 0
