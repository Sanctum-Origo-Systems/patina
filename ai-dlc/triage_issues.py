#!/usr/bin/env python3
"""Cron 1: Triage untriaged GitHub issues via Claude."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = "Sanctum-Origo-Systems/patina"
REPO_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = REPO_DIR / "ai-dlc" / "run_history.jsonl"
TRIAGE_COST_PER_CALL = 0.03
TRIAGE_MODEL = os.environ.get("PATINA_AIDLC_TRIAGE_MODEL", "sonnet")

TRIAGE_LABELS = {
    "ready",
    "rejected",
    "needs-decomposition",
    "in-progress",
    "in-review",
    "needs-human",
}

TRIAGE_PROMPT = """\
Evaluate this GitHub issue for implementation readiness.

TEMPLATE REQUIREMENTS — reject if missing:
- Summary (one clear sentence)
- Type (bug/feature/refactor)
- Expected Behavior (specific and testable)
- Acceptance Criteria (at least one checkbox item)

"Files to Modify" is optional — do NOT reject for missing files.

REJECTION GUIDANCE:
- When rejecting, explain what is missing or vague at the module or function level.
- Do NOT suggest specific line numbers, variable names, or exact assertion text.
- Good: "Expected Behavior should describe observable output, not internal state"
- Bad: "add assertion 'PROFILE.md content appears at index 3 of system_prompt'"
- The goal is to tell the submitter WHAT to fix, not HOW to implement it.

SIZE ESTIMATION:
- 1 point: single file change, <50 lines
- 2 points: 1-3 files, new function + tests, <150 lines
- 3+ points: 4+ files, schema changes, new module, >150 lines

VERDICT:
- "ready" if template complete AND estimated ≤2 points
- "needs-decomposition" if template complete BUT >2 points
- "rejected" if template incomplete or vague

Respond with JSON only:
{
  "verdict": "ready" | "needs-decomposition" | "rejected",
  "points": 1 | 2 | 3 | 5 | 8,
  "priority": "p0" | "p1" | "p2",
  "reason": "one line",
  "files_missing": true | false,
  "decomposition": [...]
}

Include "decomposition" only if verdict is "needs-decomposition".
Each sub-issue: {order, title, points, depends_on, files, why_first/why_after}.
"""

FILE_DISCOVERY_PROMPT = """\
Given this issue and the project structure, identify files to modify and test.

Project structure:
{tree}

CLAUDE.md:
{claude_md}

Issue #{number}: {title}
{body}

Respond with JSON only:
{{
  "files_to_modify": [
    {{"path": "src/patina/example.py", "reason": "why this file"}},
    {{"path": "tests/test_example.py", "reason": "test coverage"}}
  ]
}}
"""


# --- Pure functions (testable without mocking) ---


def parse_triage_response(stdout: str) -> dict:
    """Extract JSON verdict from Claude's triage output."""
    text = stdout.strip()
    if "```" in text:
        text = text.split("```")[1].replace("json", "").strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, IndexError):
        return {"verdict": "rejected", "reason": "Failed to parse triage response"}


def parse_file_discovery_response(stdout: str) -> list[dict]:
    """Extract file list JSON from Claude's file discovery output."""
    text = stdout.strip()
    if "```" in text:
        text = text.split("```")[1].replace("json", "").strip()
    try:
        return json.loads(text).get("files_to_modify", [])
    except (json.JSONDecodeError, IndexError):
        return []


def validate_discovered_files(files: list[dict], repo_dir: Path) -> list[dict]:
    """Filter to files that exist or are new test files."""
    return [f for f in files if (repo_dir / f["path"]).exists() or f["path"].startswith("tests/")]


def build_decomposition_comment(result: dict) -> str:
    """Build markdown table from decomposition array."""
    rows = []
    for step in result.get("decomposition", []):
        deps = ", ".join(f"Step {d}" for d in step.get("depends_on", [])) or "—"
        files = ", ".join(f"`{f}`" for f in step.get("files", []))
        rows.append(f"| {step['order']} | {step['title']} | {step['points']} | {deps} | {files} |")
    table = (
        f"**Auto-triage:** Estimated at {result['points']} points"
        f" — needs decomposition.\n\n"
        f"| Order | Sub-issue | Pts | Depends on | Files |\n"
        f"|-------|-----------|-----|------------|-------|\n" + "\n".join(rows)
    )
    why_lines = []
    for step in result.get("decomposition", []):
        reason = step.get("why_first") or step.get("why_after", "")
        if reason:
            why_lines.append(f"- Step {step['order']}: {reason}")
    if why_lines:
        table += "\n\n**Why this order:**\n" + "\n".join(why_lines)
    table += (
        "\n\nCreate sub-issues using the issue template. Use `Depends on: #N`\n"
        "(real issue numbers) in the Dependencies field. The implementation bot\n"
        "skips issues whose dependencies aren't merged yet."
    )
    return table


def log_run(issue_number: int, success: bool, attempts: int, duration: float, cost: float):
    """Append a JSON entry to the run history log."""
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "issue": issue_number,
        "success": success,
        "attempts": attempts,
        "duration_seconds": round(duration),
        "estimated_cost": round(cost, 2),
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


# --- Subprocess functions ---


def list_untriaged_issues() -> list[dict]:
    """Fetch open issues that have no triage labels yet."""
    result = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            REPO,
            "--state",
            "open",
            "--json",
            "number,title,body,labels",
            "--limit",
            "50",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    issues = json.loads(result.stdout)
    return [
        i for i in issues if not any(lbl["name"] in TRIAGE_LABELS for lbl in i.get("labels", []))
    ]


def evaluate_issue(issue: dict) -> dict:
    """Run Claude to evaluate an issue against the triage prompt."""
    prompt = (
        TRIAGE_PROMPT
        + f"\n\nIssue #{issue['number']}: {issue['title']}\n\n"
        + (issue.get("body") or "")
    )
    try:
        result = subprocess.run(
            ["claude", "-p", "--model", TRIAGE_MODEL, prompt],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        return {"verdict": "rejected", "reason": "Triage timed out — issue body may be too large"}
    return parse_triage_response(result.stdout)


def discover_files(issue: dict) -> list[dict]:
    """Ask Claude to identify relevant files for an issue."""
    tree = subprocess.run(
        ["find", "src/", "tests/", "-name", "*.py", "-not", "-path", "*__pycache__*"],
        capture_output=True,
        text=True,
        cwd=REPO_DIR,
    ).stdout

    claude_md = (REPO_DIR / "CLAUDE.md").read_text()
    prompt = FILE_DISCOVERY_PROMPT.format(
        tree=tree[:3000],
        claude_md=claude_md,
        number=issue["number"],
        title=issue["title"],
        body=issue["body"] or "",
    )

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", TRIAGE_MODEL, prompt],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        return []

    files = parse_file_discovery_response(result.stdout)
    return validate_discovered_files(files, REPO_DIR)


def enrich_issue_with_files(number: int, files: list[dict]):
    """Comment with discovered files so the implementation agent sees them."""
    file_lines = "\n".join(f"- `{f['path']}` — {f['reason']}" for f in files)
    comment = f"**Auto-triage — File Discovery:**\n\nIdentified files to modify:\n{file_lines}"
    subprocess.run(
        ["gh", "issue", "comment", str(number), "--repo", REPO, "--body", comment],
    )


def reject_issue(number: int, reason: str):
    """Label issue as rejected and comment with the reason."""
    subprocess.run(
        ["gh", "issue", "edit", str(number), "--repo", REPO, "--add-label", "rejected"],
    )
    subprocess.run(
        [
            "gh",
            "issue",
            "comment",
            str(number),
            "--repo",
            REPO,
            "--body",
            f"**Auto-triage — Rejected:** {reason}",
        ],
    )


def approve_issue(number: int, priority: str, reason: str):
    """Label issue as ready with priority and comment."""
    subprocess.run(
        ["gh", "issue", "edit", str(number), "--repo", REPO, "--add-label", f"ready,{priority}"],
    )
    subprocess.run(
        [
            "gh",
            "issue",
            "comment",
            str(number),
            "--repo",
            REPO,
            "--body",
            f"**Auto-triage — Ready ({priority}):** {reason}",
        ],
    )


def decompose_issue(number: int, result: dict):
    """Label issue as needs-decomposition and post breakdown comment."""
    subprocess.run(
        ["gh", "issue", "edit", str(number), "--repo", REPO, "--add-label", "needs-decomposition"],
    )
    comment = build_decomposition_comment(result)
    subprocess.run(
        ["gh", "issue", "comment", str(number), "--repo", REPO, "--body", comment],
    )


# --- Orchestration ---


def triage_issue(issue: dict) -> int:
    """Evaluate a single issue and apply the appropriate label. Returns claude call count."""
    claude_calls = 1  # evaluate_issue always makes one claude call
    result = evaluate_issue(issue)

    if result["verdict"] == "rejected":
        reject_issue(issue["number"], result["reason"])
        return claude_calls

    if result.get("files_missing", False):
        files = discover_files(issue)
        claude_calls += 1  # discover_files makes one claude call
        if files:
            enrich_issue_with_files(issue["number"], files)

    if result["verdict"] == "ready":
        approve_issue(issue["number"], result["priority"], result["reason"])
    elif result["verdict"] == "needs-decomposition":
        decompose_issue(issue["number"], result)

    return claude_calls


def main():
    start_time = time.time()
    claude_calls = 0

    issues = list_untriaged_issues()
    if not issues:
        print("No untriaged issues found.")
        return
    for issue in issues:
        print(f"Triaging #{issue['number']}: {issue['title']}")
        claude_calls += triage_issue(issue)

    if claude_calls > 0:
        elapsed = time.time() - start_time
        cost = claude_calls * TRIAGE_COST_PER_CALL
        print("\n--- AI-DLC Run Stats ---")
        print(f"  Duration: {elapsed:.0f}s")
        print(f"  Claude calls: {claude_calls}")
        print(f"  Estimated cost: ~${cost:.2f}")
        log_run(0, True, len(issues), elapsed, cost)


if __name__ == "__main__":
    main()
