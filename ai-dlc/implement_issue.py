#!/usr/bin/env python3
"""Cron 2: Implement the top ready GitHub issue via Claude."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = "Sanctum-Origo-Systems/patina"
REPO_DIR = Path(__file__).resolve().parent.parent
LOCKFILE = REPO_DIR / ".ai-dlc.lock"
LOG_FILE = REPO_DIR / "ai-dlc" / "run_history.jsonl"
MAX_RETRIES = 3
IMPL_COST_PER_CALL = 2.50


# --- Pure functions (testable without mocking) ---


def parse_dependency_numbers(body: str) -> list[str]:
    """Extract dependency issue numbers from issue body."""
    return re.findall(r"Depends on:?\s*#(\d+)", body, re.IGNORECASE)


def build_branch_name(issue: dict) -> str:
    """Slugify issue into a branch name."""
    slug = re.sub(r"[^a-z0-9]+", "-", issue["title"].lower()).strip("-")[:50]
    return f"ai-dlc/{issue['number']}-{slug}"


def detect_issue_type(body: str) -> str:
    """Determine conventional commit type from issue body."""
    body_lower = (body or "").lower()
    if "## type\nbug" in body_lower:
        return "fix"
    if "## type\nrefactor" in body_lower:
        return "refactor"
    return "feat"


def build_pr_body(
    issue: dict,
    attempts: int = 0,
    claude_calls: int = 0,
    duration: float = 0,
) -> str:
    """Build the PR description markdown."""
    body = (
        f"Closes #{issue['number']}\n\n"
        f"## Summary\n"
        f"{issue['title']}\n\n"
        f"## Test Plan\n"
        f"- `uv run pytest` — all tests pass\n"
        f"- `uv run pytest eval/deterministic/` — eval tests pass\n"
        f"- `uv run ruff check && uv run ruff format --check` — clean\n\n"
    )
    if claude_calls > 0:
        cost = claude_calls * IMPL_COST_PER_CALL
        body += (
            f"## AI-DLC Run Stats\n"
            f"- Attempts: {attempts}/{MAX_RETRIES}\n"
            f"- Claude calls: {claude_calls}\n"
            f"- Duration: {duration:.0f}s\n"
            f"- Estimated cost: ~${cost:.2f}\n\n"
        )
    body += "Automated implementation by Patina AI-DLC."
    return body


def collect_verification_errors(
    ahead_count: str,
    test_rc: int,
    test_out: str,
    eval_rc: int,
    eval_out: str,
    lint_rc: int,
    fmt_rc: int,
    changed_files: list[str],
) -> list[str]:
    """Build error list from verification subprocess results."""
    errors = []
    if ahead_count.strip() == "0" or not ahead_count.strip():
        errors.append("No commits on branch")
    if test_rc != 0:
        errors.append(f"Tests failed:\n{test_out[-500:]}")
    if eval_rc != 0:
        errors.append(f"Eval tests failed:\n{eval_out[-500:]}")
    if lint_rc != 0 or fmt_rc != 0:
        errors.append("Lint or format check failed")
    test_files = [f for f in changed_files if f.startswith("tests/") and f.endswith(".py")]
    if not test_files:
        errors.append("No test files were added or modified")
    return errors


# --- Lockfile ---


def acquire_lock() -> bool:
    """Acquire lockfile. Returns False if another run is active."""
    if LOCKFILE.exists():
        try:
            pid = int(LOCKFILE.read_text().strip())
            os.kill(pid, 0)
            return False
        except (ProcessLookupError, ValueError):
            pass
    LOCKFILE.write_text(str(os.getpid()))
    return True


def release_lock():
    """Remove the lockfile."""
    LOCKFILE.unlink(missing_ok=True)


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


def get_top_ready_issue() -> dict | None:
    """Pick the highest-priority ready issue."""
    result = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            REPO,
            "--label",
            "ready",
            "--state",
            "open",
            "--json",
            "number,title,body,labels",
            "--limit",
            "10",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    issues = json.loads(result.stdout)
    if not issues:
        return None
    priority_order = {"p0": 0, "p1": 1, "p2": 2}

    def sort_key(issue):
        labels = {lbl["name"] for lbl in issue.get("labels", [])}
        for p, rank in priority_order.items():
            if p in labels:
                return rank
        return 99

    issues.sort(key=sort_key)
    return issues[0]


def dependencies_met(issue: dict) -> bool:
    """Check if all issues in Dependencies field are closed."""
    body = issue.get("body", "") or ""
    deps = parse_dependency_numbers(body)
    for dep_num in deps:
        result = subprocess.run(
            ["gh", "issue", "view", dep_num, "--repo", REPO, "--json", "state"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            state = json.loads(result.stdout).get("state", "")
            if state != "CLOSED":
                return False
    return True


def create_branch(issue: dict) -> str:
    """Create feature branch from latest main."""
    branch = build_branch_name(issue)
    subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR, check=True)
    subprocess.run(["git", "pull", "origin", "main"], cwd=REPO_DIR, check=True)
    subprocess.run(["git", "checkout", "-b", branch], cwd=REPO_DIR, check=True)
    return branch


def build_implementation_prompt(issue: dict) -> str:
    """Build the full prompt for the implementation agent."""
    claude_md = (REPO_DIR / "CLAUDE.md").read_text()

    comments = subprocess.run(
        ["gh", "issue", "view", str(issue["number"]), "--repo", REPO, "--json", "body,comments"],
        capture_output=True,
        text=True,
    )
    full_context = issue["body"] or ""
    if comments.returncode == 0:
        data = json.loads(comments.stdout)
        for c in data.get("comments", []):
            body = c.get("body", "")
            if any(
                tag in body
                for tag in (
                    "Auto-triage",
                    "AI-DLC Attempt",
                    "Implementation Detail",
                )
            ):
                full_context += f"\n\n{body}"

    return (
        f"## Task\n\n"
        f"Implement GitHub issue #{issue['number']}: {issue['title']}\n\n"
        f"## Issue Details\n\n{full_context}\n\n"
        f"## Project Conventions\n\n{claude_md}\n\n"
        f"## Implementation Checklist\n\n"
        f"1. Read the files listed in 'Files to Modify'\n"
        f"2. Implement the changes described in the issue\n"
        f"3. Write comprehensive unit tests for every new/changed function\n"
        f"4. Run `uv run pytest` — all tests must pass\n"
        f"5. Run `uv run pytest eval/deterministic/` — eval tests must pass\n"
        f"6. Run `uv run ruff check && uv run ruff format` — must be clean\n"
        f"7. If README.md needs updating (new tools, commands), update it\n"
        f"8. Stage and commit:\n"
        f"   `git add <specific files>`\n"
        f"   `git commit -m '<type>: <description> (#{issue['number']})'\n"
        f"   Types: fix (bugs), feat (features), refactor\n"
        f"   Keep first line under 70 chars\n\n"
        f"## Rules\n\n"
        f"- Never use real person or company names in test data\n"
        f"- Follow existing code patterns in this repo\n"
        f"- Do not add features beyond what the issue asks for\n"
        f"- Do not skip tests or lint\n"
        f"- Do not run git push\n"
    )


def implement(issue: dict) -> bool:
    """Run Claude to implement the issue."""
    prompt = build_implementation_prompt(issue)
    result = subprocess.run(
        ["claude", "-p", "--model", "sonnet", prompt],
        cwd=REPO_DIR,
        capture_output=True,
        text=True,
        timeout=600,
    )
    return result.returncode == 0


def verify_implementation(branch: str) -> tuple[bool, str]:
    """Verify the agent actually produced valid work."""
    ahead = subprocess.run(
        ["git", "rev-list", "--count", f"main..{branch}"],
        capture_output=True,
        text=True,
        cwd=REPO_DIR,
    )
    tests = subprocess.run(
        ["uv", "run", "pytest", "tests/", "-q"],
        capture_output=True,
        text=True,
        cwd=REPO_DIR,
        timeout=120,
    )
    evals = subprocess.run(
        ["uv", "run", "pytest", "eval/deterministic/", "-q"],
        capture_output=True,
        text=True,
        cwd=REPO_DIR,
        timeout=120,
    )
    lint = subprocess.run(
        ["uv", "run", "ruff", "check"],
        capture_output=True,
        text=True,
        cwd=REPO_DIR,
    )
    fmt = subprocess.run(
        ["uv", "run", "ruff", "format", "--check", "."],
        capture_output=True,
        text=True,
        cwd=REPO_DIR,
    )
    diff = subprocess.run(
        ["git", "diff", "--name-only", "main"],
        capture_output=True,
        text=True,
        cwd=REPO_DIR,
    )
    changed = [f for f in diff.stdout.strip().split("\n") if f]

    errors = collect_verification_errors(
        ahead_count=ahead.stdout if ahead.returncode == 0 else "",
        test_rc=tests.returncode,
        test_out=tests.stdout,
        eval_rc=evals.returncode,
        eval_out=evals.stdout,
        lint_rc=lint.returncode,
        fmt_rc=fmt.returncode,
        changed_files=changed,
    )
    if errors:
        return False, "\n".join(errors)
    return True, ""


def cleanup_branch(branch: str):
    """Delete failed branch locally and remotely."""
    subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR)
    subprocess.run(["git", "branch", "-D", branch], cwd=REPO_DIR)
    subprocess.run(
        ["git", "push", "origin", "--delete", branch],
        cwd=REPO_DIR,
        capture_output=True,
    )


def create_pr(
    issue: dict,
    branch: str,
    attempts: int = 0,
    claude_calls: int = 0,
    duration: float = 0,
):
    """Create PR with conventional format."""
    issue_type = detect_issue_type(issue.get("body", ""))
    title = f"{issue_type}: {issue['title'][:60]} (#{issue['number']})"
    body = build_pr_body(issue, attempts=attempts, claude_calls=claude_calls, duration=duration)
    subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            REPO,
            "--title",
            title,
            "--body",
            body,
            "--head",
            branch,
            "--base",
            "main",
        ],
        cwd=REPO_DIR,
    )


def label_in_review(number: int):
    """Move issue from in-progress to in-review."""
    subprocess.run(
        [
            "gh",
            "issue",
            "edit",
            str(number),
            "--repo",
            REPO,
            "--remove-label",
            "in-progress",
            "--add-label",
            "in-review",
        ],
    )


# --- Orchestration ---


def main():
    start_time = time.time()
    claude_calls = 0
    issue_number = 0
    success = False
    final_attempt = 0

    os.chdir(REPO_DIR)

    if not acquire_lock():
        print("Another implementation is running. Exiting.")
        return

    try:
        issue = get_top_ready_issue()
        if not issue:
            print("No ready issues to implement.")
            return

        if not dependencies_met(issue):
            print(f"#{issue['number']}: dependencies not met, skipping.")
            return

        issue_number = issue["number"]
        print(f"Implementing #{issue['number']}: {issue['title']}")

        subprocess.run(
            [
                "gh",
                "issue",
                "edit",
                str(issue["number"]),
                "--repo",
                REPO,
                "--remove-label",
                "ready",
                "--add-label",
                "in-progress",
            ],
        )

        branch = create_branch(issue)
        print(f"  Branch: {branch}")

        for attempt in range(1, MAX_RETRIES + 1):
            print(f"  Attempt {attempt}/{MAX_RETRIES}...")
            implement(issue)
            claude_calls += 1
            final_attempt = attempt

            valid, errors = verify_implementation(branch)
            if valid:
                success = True
                print("  Verification passed.")
                break
            else:
                print(f"  Verification failed:\n{errors}")

        if not success:
            print("  All retries exhausted. Labeling needs-human.")
            subprocess.run(
                [
                    "gh",
                    "issue",
                    "edit",
                    str(issue["number"]),
                    "--repo",
                    REPO,
                    "--remove-label",
                    "in-progress",
                    "--add-label",
                    "ready",
                    "--add-label",
                    "needs-human",
                ],
            )
            cleanup_branch(branch)
            return

        subprocess.run(["git", "push", "-u", "origin", branch], cwd=REPO_DIR)
        elapsed = time.time() - start_time
        create_pr(
            issue,
            branch,
            attempts=final_attempt,
            claude_calls=claude_calls,
            duration=elapsed,
        )
        label_in_review(issue["number"])
        print(f"  PR created for #{issue['number']}.")

        subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR)

    finally:
        release_lock()
        if claude_calls > 0:
            elapsed = time.time() - start_time
            cost = claude_calls * IMPL_COST_PER_CALL
            print("\n--- AI-DLC Run Stats ---")
            print(f"  Duration: {elapsed:.0f}s")
            print(f"  Claude calls: {claude_calls}")
            print(f"  Estimated cost: ~${cost:.2f}")
            log_run(issue_number, success, final_attempt, elapsed, cost)


if __name__ == "__main__":
    main()
