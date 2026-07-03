#!/usr/bin/env python3
"""Cron 1: Triage untriaged GitHub issues via Claude."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from claude_runner import ClaudeResult, run_claude
from create_issue import build_issue_body

REPO = "Sanctum-Origo-Systems/patina"
REPO_DIR = Path(__file__).resolve().parent.parent
LOG_FILE = REPO_DIR / "ai-dlc" / "run_history.jsonl"
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

SUB_ISSUE_PROMPT = """\
Generate structured issue fields for this sub-issue of a decomposed parent.

Parent issue: #{parent_number}
Parent summary: {parent_summary}

Sub-issue: {step_title}
Files: {step_files}
Reason for ordering: {step_reason}

Respond with JSON only:
{{
  "expected_behavior": "specific, testable description",
  "acceptance_criteria": ["criterion 1", "criterion 2"]
}}

Rules:
- Expected behavior must describe observable outputs, not repeat the title.
- Acceptance criteria must be verifiable by running a test or command.
- Do not include generic criteria like "tests pass" or "lint clean".
- Reference function names and modules, not line numbers.
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


def parse_sub_issue_response(stdout: str) -> dict | None:
    """Extract sub-issue fields JSON from Claude's output.

    Returns a dict with 'expected_behavior' and 'acceptance_criteria', or None
    if the response is not valid JSON or is missing the expected fields.
    """
    text = stdout.strip()
    if "```" in text:
        text = text.split("```")[1].replace("json", "").strip()
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        return None
    if not isinstance(data, dict) or "expected_behavior" not in data:
        return None
    return data


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


def build_sub_issue_summary_comment(parent_number: int, sub_issues: list[int]) -> str:
    """Build the parent comment listing the created sub-issue numbers."""
    lines = "\n".join(f"- #{n}" for n in sub_issues)
    return (
        f"**Auto-triage — Sub-issues created:**\n\n"
        f"Decomposed #{parent_number} into {len(sub_issues)} sub-issue(s):\n{lines}"
    )


def log_run(
    issue_number: int,
    success: bool,
    attempts: int,
    duration: float,
    cost_usd: float,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
):
    """Append a JSON entry to the run history log."""
    entry = {
        "timestamp": datetime.now(UTC).isoformat(),
        "issue": issue_number,
        "success": success,
        "attempts": attempts,
        "duration_seconds": round(duration),
        "cost_usd": round(cost_usd, 2),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
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


def evaluate_issue(issue: dict) -> tuple[dict, ClaudeResult]:
    """Run Claude to evaluate an issue against the triage prompt."""
    prompt = (
        TRIAGE_PROMPT
        + f"\n\nIssue #{issue['number']}: {issue['title']}\n\n"
        + (issue.get("body") or "")
    )
    result = run_claude(prompt, TRIAGE_MODEL, 90)
    if not result.success:
        verdict = {
            "verdict": "rejected",
            "reason": "Triage timed out — issue body may be too large",
        }
        return verdict, result
    return parse_triage_response(result.text), result


def discover_files(issue: dict) -> tuple[list[dict], ClaudeResult]:
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

    result = run_claude(prompt, TRIAGE_MODEL, 90)
    if not result.success:
        return [], result

    files = parse_file_discovery_response(result.text)
    return validate_discovered_files(files, REPO_DIR), result


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


def suggest_sub_issue_fields(parent_number: int, parent_summary: str, step: dict) -> dict | None:
    """Ask Claude for a specific Expected Behavior + Acceptance Criteria.

    Returns a dict with 'expected_behavior' and 'acceptance_criteria' keys, or
    None if claude is unavailable, the call fails, or the response is not valid
    JSON. Callers fall back to the step title on None.
    """
    if not shutil.which("claude"):
        return None

    why = step.get("why_first") or step.get("why_after", "")
    prompt = SUB_ISSUE_PROMPT.format(
        parent_number=parent_number,
        parent_summary=parent_summary,
        step_title=step["title"],
        step_files=", ".join(step.get("files", [])),
        step_reason=why,
    )
    result = run_claude(prompt, TRIAGE_MODEL, 90)
    if not result.success:
        return None
    return parse_sub_issue_response(result.text)


def create_sub_issues(parent_number: int, result: dict, parent_summary: str = "") -> list[int]:
    """Create sub-issues from a decomposition and return their numbers.

    Sub-issues are created in decomposition order. Each body references the
    parent issue and lists 'Depends on: #N' for any earlier steps in the same
    decomposition that have already been created.

    For each step, an LLM call generates a specific Expected Behavior and
    feature-specific Acceptance Criteria so the sub-issue survives triage. If
    that call fails or returns invalid JSON, the step title is used as the
    Expected Behavior with no extra criteria (the prior behavior).
    """
    step_to_issue: dict[int, int] = {}
    created: list[int] = []
    for step in result.get("decomposition", []):
        dep_refs = [
            f"#{step_to_issue[d]}" for d in step.get("depends_on", []) if d in step_to_issue
        ]
        deps = "Depends on: " + ", ".join(dep_refs) if dep_refs else ""

        fields = suggest_sub_issue_fields(parent_number, parent_summary, step)
        if fields:
            expected = fields.get("expected_behavior") or step["title"]
            extra_criteria = "\n".join(fields.get("acceptance_criteria", []))
        else:
            expected = step["title"]
            extra_criteria = ""

        why = step.get("why_first") or step.get("why_after", "")
        body = build_issue_body(
            summary=step["title"],
            issue_type="feature",
            files="\n".join(step.get("files", [])),
            current_behavior="",
            expected=expected,
            extra_criteria=extra_criteria,
            hints=f"Sub-issue of #{parent_number}. {why}".strip(),
            deps=deps,
            context=f"Parent issue: #{parent_number}",
        )

        proc = subprocess.run(
            ["gh", "issue", "create", "--repo", REPO, "--title", step["title"], "--body", body],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            issue_url = proc.stdout.strip()
            issue_num = int(issue_url.rstrip("/").split("/")[-1])
            step_to_issue[step["order"]] = issue_num
            created.append(issue_num)

    return created


def decompose_issue(number: int, result: dict, parent_summary: str = ""):
    """Label the parent needs-decomposition, create sub-issues, post summary."""
    subprocess.run(
        ["gh", "issue", "edit", str(number), "--repo", REPO, "--add-label", "needs-decomposition"],
    )
    comment = build_decomposition_comment(result)
    subprocess.run(
        ["gh", "issue", "comment", str(number), "--repo", REPO, "--body", comment],
    )
    sub_issues = create_sub_issues(number, result, parent_summary)
    if sub_issues:
        subprocess.run(
            [
                "gh",
                "issue",
                "comment",
                str(number),
                "--repo",
                REPO,
                "--body",
                build_sub_issue_summary_comment(number, sub_issues),
            ],
        )


# --- Orchestration ---


def triage_issue(issue: dict) -> list[ClaudeResult]:
    """Evaluate a single issue and apply the appropriate label.

    Returns the ClaudeResult of every claude call made for this issue.
    """
    results: list[ClaudeResult] = []
    verdict, eval_result = evaluate_issue(issue)
    results.append(eval_result)

    if verdict["verdict"] == "rejected":
        reject_issue(issue["number"], verdict["reason"])
        return results

    if verdict.get("files_missing", False):
        files, disc_result = discover_files(issue)
        results.append(disc_result)
        if files:
            enrich_issue_with_files(issue["number"], files)

    if verdict["verdict"] == "ready":
        approve_issue(issue["number"], verdict["priority"], verdict["reason"])
    elif verdict["verdict"] == "needs-decomposition":
        decompose_issue(issue["number"], verdict, issue.get("body") or "")

    return results


def main():
    start_time = time.time()
    results: list[ClaudeResult] = []

    issues = list_untriaged_issues()
    if not issues:
        print("No untriaged issues found.")
        return
    for issue in issues:
        print(f"Triaging #{issue['number']}: {issue['title']}")
        results.extend(triage_issue(issue))

    if results:
        elapsed = time.time() - start_time
        total_cost = sum(r.cost_usd for r in results)
        total_input = sum(r.input_tokens for r in results)
        total_output = sum(r.output_tokens for r in results)
        total_cache_read = sum(r.cache_read_tokens for r in results)
        print("\n--- AI-DLC Run Stats ---")
        print(f"  Duration: {elapsed:.0f}s")
        print(f"  Claude calls: {len(results)}")
        print(f"  Input tokens: {total_input:,}")
        print(f"  Output tokens: {total_output:,}")
        print(f"  Cost: ${total_cost:.2f}")
        log_run(
            0,
            True,
            len(issues),
            elapsed,
            total_cost,
            total_input,
            total_output,
            total_cache_read,
        )


if __name__ == "__main__":
    main()
