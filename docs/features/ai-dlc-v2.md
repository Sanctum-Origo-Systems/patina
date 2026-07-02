# Patina AI-DLC v2: Automated Issue Triage + Implementation

## Changes from v1

- Issue template for Claude-executable specifications
- Story point estimation at triage — issues >2 points get decomposed
- File discovery at triage when submitter doesn't know which files
- Decomposition with dependency ordering and execution sequence
- Correct Claude CLI invocation (`-p` for triage, agentic with settings for impl)
- `.claude/settings.json` for pre-approved tool permissions
- Lint/format before commit, not after
- Branch cleanup on failure
- Concurrency lockfile
- Commit verification before PR creation
- Test count validation
- Eval test awareness
- Error feedback on retry — failed attempts feed errors into next attempt + post to GitHub
- Configurable model and timeout via environment variables
- Batch mode (`--max-issues N`) for clearing backlogs in one run
- Cost/token tracking with `run_history.jsonl` and stats in PR description
- Pull latest main before branching to prevent stale divergence
- `--from-spec` flag to create issues from a spec markdown file
- `--edit` flag to fix rejected issues interactively
- `--no-suggest` flag to skip Claude-powered field suggestions
- GitHub comment conventions: `Auto-triage`, `AI-DLC Attempt`, `Implementation Detail`

---

## Issue Template

Every issue must follow this template. The triage bot rejects issues missing
Summary, Type, Expected Behavior, or Acceptance Criteria.

```markdown
## Summary
<!-- One sentence: what needs to change and why -->

## Type
<!-- bug | feature | refactor -->

## Files to Modify
<!-- Optional. List files if you know them. Write "Unknown" or leave blank. -->
<!-- The triage bot will auto-discover files and comment with suggestions. -->

## Current Behavior (bugs only)
<!-- What happens now? Include error messages or wrong output. -->

## Expected Behavior
<!-- What should happen after the fix? Be specific and testable. -->

## Acceptance Criteria
<!-- Checklist. Each item must be verifiable by running a test or command. -->
- [ ] New unit tests pass
- [ ] All existing tests pass (`uv run pytest`)
- [ ] `uv run ruff check && uv run ruff format --check` clean

## Implementation Hints
<!-- Optional. Function names, patterns to follow, edge cases. -->
<!-- Reference files and methods, not line numbers — lines shift as other PRs land. -->
<!-- Good: "Follow the pattern in src/patina/mcp/tools_beliefs.py" -->
<!-- Bad: "Change line 87 of runtime.py" -->

## Dependencies
<!-- Optional. Issue numbers that must be merged first. -->
<!-- Example: Depends on #43 (schema change must land first) -->

## Context
<!-- Links to related issues, docs, or conversation excerpts. -->
<!-- Include enough that a fresh context window doesn't need prior history. -->

## Story Points
<!-- 1 = trivial, 2 = small (new function + tests), 3+ = needs decomposition -->
<!-- Leave blank — the triage bot will estimate. -->
```

---

## File Discovery at Triage

When "Files to Modify" is blank or "Unknown", the triage bot runs a second
`claude -p` call to discover relevant files.

```python
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


def discover_files(issue: dict) -> list[dict]:
    """Ask Claude to identify relevant files for an issue."""
    tree = subprocess.run(
        ["find", "src/", "tests/", "-name", "*.py",
         "-not", "-path", "*__pycache__*"],
        capture_output=True, text=True, cwd=REPO_DIR
    ).stdout

    claude_md = (REPO_DIR / "CLAUDE.md").read_text()
    prompt = FILE_DISCOVERY_PROMPT.format(
        tree=tree[:3000], claude_md=claude_md,
        number=issue["number"], title=issue["title"],
        body=issue["body"] or "",
    )

    result = subprocess.run(
        ["claude", "-p", "--model", "sonnet", prompt],
        capture_output=True, text=True, timeout=30
    )

    try:
        text = result.stdout.strip()
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        files = json.loads(text).get("files_to_modify", [])
    except (json.JSONDecodeError, IndexError):
        return []

    # Validate: only return files that actually exist in the repo
    return [
        f for f in files
        if (REPO_DIR / f["path"]).exists()
        or f["path"].startswith("tests/")  # new test files are OK
    ]


def enrich_issue_with_files(number: int, files: list[dict]):
    """Comment with discovered files so the implementation agent sees them."""
    file_lines = "\n".join(
        f"- `{f['path']}` — {f['reason']}" for f in files
    )
    comment = (
        f"**Auto-triage — File Discovery:**\n\n"
        f"Identified files to modify:\n{file_lines}"
    )
    subprocess.run(
        ["gh", "issue", "comment", str(number), "--repo", REPO,
         "--body", comment]
    )
```

---

## Decomposition Rule

**Issues >2 story points must be decomposed before implementation.**

### Decomposition criteria

- Touches >3 files → likely >2 points
- Schema migration + code + tests → split by layer
- Multiple independent behaviors → one issue per behavior

### Dependency ordering

The triage bot identifies dependencies and assigns execution order.
`depends_on` uses **step numbers** (1, 2, 3) in the triage output.
When the human creates sub-issues, they replace step numbers with
**real issue numbers** (`Depends on: #47`).

```json
{
  "verdict": "needs-decomposition",
  "points": 5,
  "priority": "p1",
  "reason": "Touches 5 files across 3 layers",
  "decomposition": [
    {
      "order": 1,
      "title": "Add watched_senders/channels tables to schema",
      "points": 1,
      "depends_on": [],
      "files": ["src/patina/store.py", "tests/test_store.py"],
      "why_first": "Schema must exist before code can query it"
    },
    {
      "order": 2,
      "title": "Add 6 watching MCP tools",
      "points": 2,
      "depends_on": [1],
      "files": ["src/patina/mcp/tools_catch_up.py"],
      "why_after": "Tools INSERT into tables from step 1"
    },
    {
      "order": 3,
      "title": "Hook watched channels into ingest_live()",
      "points": 1,
      "depends_on": [1, 2],
      "files": ["src/patina/ingest.py"],
      "why_after": "Reads tables populated by tools in step 2"
    }
  ]
}
```

The comment posted to GitHub:

```markdown
**Auto-triage:** Estimated at 5 points — needs decomposition.

| Order | Sub-issue | Pts | Depends on | Files |
|-------|-----------|-----|------------|-------|
| 1 | Add watched tables to schema | 1 | — | `store.py` |
| 2 | Add 6 watching MCP tools | 2 | Step 1 | `tools_catch_up.py` |
| 3 | Hook into ingest_live() | 1 | Steps 1, 2 | `ingest.py` |

**Why this order:**
- Step 1 first: schema must exist before code queries it
- Step 2 before 3: ingestion reads tables populated by tools

Create sub-issues using the issue template. Use `Depends on: #N`
(real issue numbers) in the Dependencies field. The implementation bot
skips issues whose dependencies aren't merged yet.
```

### Dependency enforcement

```python
def parse_dependency_numbers(body: str) -> list[str]:
    """Extract dependency issue numbers from issue body."""
    return re.findall(r"Depends on:?\s*#(\d+)", body, re.IGNORECASE)


def dependencies_met(issue: dict) -> bool:
    """Check if all issues in Dependencies field are closed."""
    body = issue.get("body", "") or ""
    deps = parse_dependency_numbers(body)
    for dep_num in deps:
        result = subprocess.run(
            ["gh", "issue", "view", dep_num, "--repo", REPO,
             "--json", "state"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            state = json.loads(result.stdout).get("state", "")
            if state != "CLOSED":
                return False
    return True
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                GitHub Issues (Patina repo)                  │
│  [untriaged] → [ready] → [in-progress] → [in-review]        │
│       ↓                                                     │
│  [needs-decomposition] → human splits → sub-issues          │
│  [needs-human] → agent failed, human takes over             │
└───────┬────────────────────────────────┬────────────────────┘
        │                                │
        ▼                                ▼
┌────────────────────┐    ┌──────────────────────────────────┐
│  Cron 1: Triage    │    │  Cron 2: Implement               │
│  (every 6 hours)   │    │  (daily or on-demand)            │
│                    │    │                                  │
│  1. gh issue list  │    │  1. Acquire lockfile             │
│  2. Validate       │    │  2. Pick top "ready" (≤2 pts)    │
│     template       │    │  3. Check dependencies met       │
│  3. Estimate size  │    │  4. git checkout -b              │
│  4. Discover files │    │  5. claude -p (agentic via       │
│  5. Label or       │    │     settings.json permissions)   │
│     decompose      │    │  6. Verify: commits exist,       │
│                    │    │     tests pass, lint clean       │
└────────────────────┘    │  7. Verify: new tests added      │
                          │  8. gh pr create                 │
                          │  9. Label "in-review"            │
                          │  10. Release lockfile            │
                          └──────────────────────────────────┘
```

---

## Prerequisites

### `.claude/settings.json` — pre-approved permissions

The implementation agent needs tool permissions without interactive prompts.
Create this file in the repo root:

```json
{
  "permissions": {
    "allow": [
      "Bash(uv run pytest*)",
      "Bash(uv run ruff*)",
      "Bash(git add*)",
      "Bash(git commit*)",
      "Bash(git status)",
      "Bash(git diff*)",
      "Bash(git log*)",
      "Bash(find*)",
      "Bash(grep*)",
      "Read",
      "Edit",
      "Write"
    ],
    "deny": [
      "Bash(git push*)",
      "Bash(git reset*)",
      "Bash(rm -rf*)",
      "Bash(gh pr merge*)"
    ]
  }
}
```

This allows the agent to read, edit, test, lint, and commit — but NOT push,
force-reset, delete, or merge. The implementation script handles push and PR
creation outside the agent.

### Environment variables (optional)

| Variable | Default | Purpose |
|----------|---------|---------|
| `PATINA_AIDLC_TRIAGE_MODEL` | `sonnet` | Model for triage evaluation and file discovery |
| `PATINA_AIDLC_IMPL_MODEL` | `opus` | Model for implementation |
| `PATINA_AIDLC_TIMEOUT` | `900` | Implementation timeout in seconds |

```bash
# Override for a single run
PATINA_AIDLC_IMPL_MODEL=sonnet uv run python ai-dlc/implement_issue.py
PATINA_AIDLC_TIMEOUT=1800 uv run python ai-dlc/implement_issue.py
```

### GitHub labels

Create these labels on the repo once:

```bash
for label in ready rejected needs-decomposition p0 p1 p2 \
             in-progress in-review needs-human bug feature refactor; do
    gh label create "$label" --repo Sanctum-Origo-Systems/patina 2>/dev/null
done
```

---

## Cron 1: Triage (`ai-dlc/triage_issues.py`)

### Triage prompt

```
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
```

### Listing untriaged issues

```python
def list_untriaged_issues() -> list[dict]:
    """Fetch open issues that have no triage labels yet."""
    result = subprocess.run(
        ["gh", "issue", "list", "--repo", REPO, "--state", "open",
         "--json", "number,title,body,labels", "--limit", "50"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return []
    issues = json.loads(result.stdout)
    triage_labels = {"ready", "rejected", "needs-decomposition",
                     "in-progress", "in-review", "needs-human"}
    return [
        i for i in issues
        if not any(l["name"] in triage_labels for l in i.get("labels", []))
    ]
```

### Evaluating an issue

```python
def parse_triage_response(stdout: str) -> dict:
    """Extract JSON verdict from Claude's triage output."""
    text = stdout.strip()
    if "```" in text:
        text = text.split("```")[1].replace("json", "").strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, IndexError):
        return {"verdict": "rejected", "reason": "Failed to parse triage response"}


def evaluate_issue(issue: dict) -> dict:
    """Run Claude to evaluate an issue against the triage prompt."""
    prompt = TRIAGE_PROMPT + f"\n\nIssue #{issue['number']}: {issue['title']}\n\n{issue.get('body', '')}"
    result = subprocess.run(
        ["claude", "-p", "--model", "sonnet", prompt],
        capture_output=True, text=True, timeout=30
    )
    return parse_triage_response(result.stdout)
```

### Label application

```python
def reject_issue(number: int, reason: str):
    """Label issue as rejected and comment with the reason."""
    subprocess.run(
        ["gh", "issue", "edit", str(number), "--repo", REPO,
         "--add-label", "rejected"]
    )
    subprocess.run(
        ["gh", "issue", "comment", str(number), "--repo", REPO,
         "--body", f"**Auto-triage — Rejected:** {reason}"]
    )


def approve_issue(number: int, priority: str, reason: str):
    """Label issue as ready with priority and comment."""
    subprocess.run(
        ["gh", "issue", "edit", str(number), "--repo", REPO,
         "--add-label", f"ready,{priority}"]
    )
    subprocess.run(
        ["gh", "issue", "comment", str(number), "--repo", REPO,
         "--body", f"**Auto-triage — Ready ({priority}):** {reason}"]
    )


def build_decomposition_comment(result: dict) -> str:
    """Build markdown table from decomposition array."""
    rows = []
    for step in result.get("decomposition", []):
        deps = ", ".join(f"Step {d}" for d in step.get("depends_on", [])) or "—"
        files = ", ".join(f"`{f}`" for f in step.get("files", []))
        rows.append(
            f"| {step['order']} | {step['title']} "
            f"| {step['points']} | {deps} | {files} |"
        )
    table = (
        f"**Auto-triage:** Estimated at {result['points']} points"
        f" — needs decomposition.\n\n"
        f"| Order | Sub-issue | Pts | Depends on | Files |\n"
        f"|-------|-----------|-----|------------|-------|\n"
        + "\n".join(rows)
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


def decompose_issue(number: int, result: dict):
    """Label issue as needs-decomposition and post breakdown comment."""
    subprocess.run(
        ["gh", "issue", "edit", str(number), "--repo", REPO,
         "--add-label", "needs-decomposition"]
    )
    comment = build_decomposition_comment(result)
    subprocess.run(
        ["gh", "issue", "comment", str(number), "--repo", REPO,
         "--body", comment]
    )
```

### Triage flow

```python
def triage_issue(issue: dict):
    result = evaluate_issue(issue)

    if result["verdict"] == "rejected":
        reject_issue(issue["number"], result["reason"])
        return

    if result.get("files_missing", False):
        files = discover_files(issue)
        if files:
            enrich_issue_with_files(issue["number"], files)

    if result["verdict"] == "ready":
        approve_issue(issue["number"], result["priority"], result["reason"])
    elif result["verdict"] == "needs-decomposition":
        decompose_issue(issue["number"], result)


def main():
    issues = list_untriaged_issues()
    if not issues:
        print("No untriaged issues found.")
        return
    for issue in issues:
        print(f"Triaging #{issue['number']}: {issue['title']}")
        triage_issue(issue)


if __name__ == "__main__":
    main()
```

---

## Cron 2: Implement (`ai-dlc/implement_issue.py`)

### Concurrency lockfile

Only one implementation runs at a time. The lockfile prevents cron overlap
and accidental parallel runs.

```python
LOCKFILE = REPO_DIR / ".ai-dlc.lock"


def acquire_lock() -> bool:
    """Acquire lockfile. Returns False if another run is active."""
    if LOCKFILE.exists():
        # Check if the PID is still alive
        try:
            pid = int(LOCKFILE.read_text().strip())
            os.kill(pid, 0)  # signal 0 = check existence
            return False  # process still running
        except (ProcessLookupError, ValueError):
            pass  # stale lock, safe to take
    LOCKFILE.write_text(str(os.getpid()))
    return True


def release_lock():
    LOCKFILE.unlink(missing_ok=True)
```

### Implementation prompt

```python
def build_implementation_prompt(issue: dict) -> str:
    claude_md = (REPO_DIR / "CLAUDE.md").read_text()

    # Collect issue body + any file discovery comments
    comments = subprocess.run(
        ["gh", "issue", "view", str(issue["number"]), "--repo", REPO,
         "--json", "body,comments"],
        capture_output=True, text=True
    )
    full_context = issue["body"] or ""
    if comments.returncode == 0:
        data = json.loads(comments.stdout)
        for c in data.get("comments", []):
            body = c.get("body", "")
            if "Auto-triage" in body:
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
```

### Running the agent

```python
def implement(issue: dict) -> bool:
    """Run Claude to implement the issue.

    Uses claude -p which, combined with .claude/settings.json permissions,
    gives the agent access to Read, Edit, Write, and whitelisted Bash
    commands (pytest, ruff, git add/commit) without interactive prompts.
    """
    prompt = build_implementation_prompt(issue)
    result = subprocess.run(
        ["claude", "-p", "--model", "sonnet", prompt],
        cwd=REPO_DIR, capture_output=True, text=True, timeout=600
    )
    return result.returncode == 0
```

### Verification before PR

```python
def verify_implementation(branch: str) -> tuple[bool, str]:
    """Verify the agent actually produced valid work."""
    errors = []

    # 1. Check branch has commits ahead of main
    ahead = subprocess.run(
        ["git", "rev-list", "--count", f"main..{branch}"],
        capture_output=True, text=True, cwd=REPO_DIR
    )
    if ahead.returncode != 0 or ahead.stdout.strip() == "0":
        errors.append("No commits on branch")

    # 2. Check tests pass
    tests = subprocess.run(
        ["uv", "run", "pytest", "tests/", "-q"],
        capture_output=True, text=True, cwd=REPO_DIR, timeout=120
    )
    if tests.returncode != 0:
        errors.append(f"Tests failed:\n{tests.stdout[-500:]}")

    # 3. Check eval tests pass
    evals = subprocess.run(
        ["uv", "run", "pytest", "eval/deterministic/", "-q"],
        capture_output=True, text=True, cwd=REPO_DIR, timeout=120
    )
    if evals.returncode != 0:
        errors.append(f"Eval tests failed:\n{evals.stdout[-500:]}")

    # 4. Check lint/format
    lint = subprocess.run(
        ["uv", "run", "ruff", "check"],
        capture_output=True, text=True, cwd=REPO_DIR
    )
    fmt = subprocess.run(
        ["uv", "run", "ruff", "format", "--check", "."],
        capture_output=True, text=True, cwd=REPO_DIR
    )
    if lint.returncode != 0 or fmt.returncode != 0:
        errors.append("Lint or format check failed")

    # 5. Check new tests were added (diff should contain test functions)
    diff = subprocess.run(
        ["git", "diff", "--name-only", "main"],
        capture_output=True, text=True, cwd=REPO_DIR
    )
    test_files_changed = [
        f for f in diff.stdout.strip().split("\n")
        if f.startswith("tests/") and f.endswith(".py")
    ]
    if not test_files_changed:
        errors.append("No test files were added or modified")

    if errors:
        return False, "\n".join(errors)
    return True, ""
```

### Branch cleanup

```python
def cleanup_branch(branch: str):
    """Delete failed branch locally and remotely."""
    subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR)
    subprocess.run(["git", "branch", "-D", branch], cwd=REPO_DIR)
    # Remote branch may not exist if we never pushed
    subprocess.run(
        ["git", "push", "origin", "--delete", branch],
        cwd=REPO_DIR, capture_output=True
    )
```

### Issue selection and branch management

```python
def get_top_ready_issue() -> dict | None:
    """Pick the highest-priority ready issue."""
    result = subprocess.run(
        ["gh", "issue", "list", "--repo", REPO, "--label", "ready",
         "--state", "open", "--json", "number,title,body,labels",
         "--limit", "10"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    issues = json.loads(result.stdout)
    if not issues:
        return None
    priority_order = {"p0": 0, "p1": 1, "p2": 2}
    def sort_key(issue):
        labels = {l["name"] for l in issue.get("labels", [])}
        for p, rank in priority_order.items():
            if p in labels:
                return rank
        return 99
    issues.sort(key=sort_key)
    return issues[0]


def build_branch_name(issue: dict) -> str:
    """Slugify issue into a branch name."""
    slug = re.sub(r"[^a-z0-9]+", "-", issue["title"].lower()).strip("-")[:50]
    return f"ai-dlc/{issue['number']}-{slug}"


def create_branch(issue: dict) -> str:
    """Create and checkout a feature branch for the issue."""
    branch = build_branch_name(issue)
    subprocess.run(
        ["git", "checkout", "-b", branch],
        cwd=REPO_DIR, check=True
    )
    return branch


def label_in_review(number: int):
    """Move issue from in-progress to in-review."""
    subprocess.run(
        ["gh", "issue", "edit", str(number), "--repo", REPO,
         "--remove-label", "in-progress", "--add-label", "in-review"]
    )
```

### Main function

```python
def main():
    os.chdir(REPO_DIR)

    if not acquire_lock():
        print("Another implementation is running. Exiting.")
        return

    try:
        issue = get_top_ready_issue()
        if not issue:
            print("No ready issues to implement.")
            return

        # Check dependencies
        if not dependencies_met(issue):
            print(f"#{issue['number']}: dependencies not met, skipping.")
            return

        print(f"Implementing #{issue['number']}: {issue['title']}")

        # Mark as in-progress
        subprocess.run(
            ["gh", "issue", "edit", str(issue["number"]), "--repo", REPO,
             "--remove-label", "ready", "--add-label", "in-progress"]
        )

        branch = create_branch(issue)
        print(f"  Branch: {branch}")

        # Implementation + retry loop
        success = False
        for attempt in range(1, MAX_RETRIES + 1):
            print(f"  Attempt {attempt}/{MAX_RETRIES}...")
            implement(issue)

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
                ["gh", "issue", "edit", str(issue["number"]),
                 "--repo", REPO,
                 "--remove-label", "in-progress",
                 "--add-label", "ready",
                 "--add-label", "needs-human"]
            )
            cleanup_branch(branch)
            return

        # Push and create PR
        subprocess.run(
            ["git", "push", "-u", "origin", branch], cwd=REPO_DIR
        )
        create_pr(issue, branch)
        label_in_review(issue["number"])
        print(f"  PR created for #{issue['number']}.")

        # Return to main
        subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR)

    finally:
        release_lock()


if __name__ == "__main__":
    main()
```

### PR creation

```python
def detect_issue_type(body: str) -> str:
    """Determine conventional commit type from issue body."""
    body_lower = (body or "").lower()
    if "## type\nbug" in body_lower:
        return "fix"
    if "## type\nrefactor" in body_lower:
        return "refactor"
    return "feat"


def create_pr(issue: dict, branch: str):
    """Create PR with conventional format."""
    issue_type = detect_issue_type(issue.get("body", ""))

    title = f"{issue_type}: {issue['title'][:60]} (#{issue['number']})"
    body = (
        f"Closes #{issue['number']}\n\n"
        f"## Summary\n"
        f"{issue['title']}\n\n"
        f"## Test Plan\n"
        f"- `uv run pytest` — all tests pass\n"
        f"- `uv run pytest eval/deterministic/` — eval tests pass\n"
        f"- `uv run ruff check && uv run ruff format --check` — clean\n\n"
        f"Automated implementation by Patina AI-DLC."
    )
    subprocess.run(
        ["gh", "pr", "create", "--repo", REPO, "--title", title,
         "--body", body, "--head", branch, "--base", "main"],
        cwd=REPO_DIR
    )
```

---

## Labels

| Label | Meaning |
|-------|---------|
| (no label) | Untriaged — new issue |
| `ready` | Passed triage, ≤2 points, template complete |
| `rejected` | Template incomplete — comment explains what's missing |
| `needs-decomposition` | >2 points — human must split into sub-issues |
| `p0` / `p1` / `p2` | Priority (critical / normal / low) |
| `in-progress` | Agent is implementing |
| `in-review` | PR created, waiting for human review |
| `needs-human` | Agent failed after max retries |
| `bug` / `feature` / `refactor` | Issue type |

---

## Commit Message Convention

```
<type>: <short description under 70 chars> (#<issue>)

Types: fix | feat | refactor | docs | test
Examples:
  fix: handle conversation-grouped Outlook inbox format (#42)
  feat: add store_search MCP tool with FTS5 (#38)
  refactor: extract _unwrap_email_list helper (#45)
```

---

## Safety Guardrails

1. **Lockfile** — only one implementation runs at a time
2. **≤2 story points** — large issues require human decomposition
3. **Dependency check** — skips issues whose dependencies aren't merged
4. **Max 3 retries** — labels `needs-human` and backs off; errors feed into next attempt
5. **Verification gate** — commits exist, tests pass, lint clean, new tests added
6. **Never merges own PR** — always requires human review
7. **Never pushes inside agent** — push happens outside, in the script
8. **`.claude/settings.json`** — denies `git push`, `git reset`, `rm -rf`, `gh pr merge`
9. **Branch cleanup** — failed branches deleted locally and remotely
10. **Configurable timeout** — defaults to 900s, override via `PATINA_AIDLC_TIMEOUT`
11. **Template validation** — rejects issues without structured criteria
12. **Pull latest main** — always pulls before branching to prevent stale divergence
13. **Cost tracking** — every run logs to `run_history.jsonl` and prints stats

---

## What Each Fresh Context Window Gets

1. **CLAUDE.md** — injected in the prompt (stack, test commands, conventions)
2. **Issue body** — structured template with criteria and hints
3. **File discovery comments** — triage bot's file suggestions included
4. **`.claude/settings.json`** — pre-approved tool permissions
5. **Agentic mode** — can Read files, Edit code, Bash to run tests
6. **Existing code** — follows patterns it reads from the repo

The template IS the standup handoff — it replaces the context a human
engineer would have from attending standup.

---

## Agent Checklist Per Issue

- [ ] Read files listed in issue (or discover via search)
- [ ] Implement changes
- [ ] Write comprehensive unit tests (every new/changed function)
- [ ] `uv run pytest` passes (all tests, not just new ones)
- [ ] `uv run pytest eval/deterministic/` passes
- [ ] `uv run ruff check && uv run ruff format` clean
- [ ] Update README.md if new tools/commands added
- [ ] No real names in test data — use fictitious names only
- [ ] `git add <specific files>` (no `git add .`)
- [ ] Commit with conventional message: `<type>: <desc> (#<issue>)`
- [ ] Do NOT run `git push`

---

## Error Feedback on Retry

When implementation fails verification, errors are passed into the next attempt
so Claude doesn't repeat the same mistake.

**In-process:** `implement()` accepts a `previous_errors` parameter. The retry
loop passes the last failure's error text into the next attempt, appended as a
`## Previous Attempt Failed` section in the prompt.

**Durable (GitHub):** Each failed attempt posts a comment on the issue:

```
**AI-DLC Attempt 2 failed:**
```
Tests failed: ...
```
```

`build_implementation_prompt` reads these comments (matching `"AI-DLC Attempt"`)
so errors survive process restarts. The next cron invocation picks up where the
last one left off.

---

## Batch Mode

```bash
uv run python ai-dlc/implement_issue.py --max-issues 3
```

Processes up to N ready issues sequentially in one run. Stops if an issue fails
(may indicate a systemic problem). Issues with unmet dependencies are skipped
and labeled `blocked`.

---

## Cost/Token Tracking

Every run logs timing and estimated cost to both console and
`ai-dlc/run_history.jsonl`:

```json
{"timestamp":"2026-07-01T02:15:00Z","issue":14,"success":true,"attempts":1,"duration_seconds":180,"estimated_cost":2.5}
```

PR descriptions include an **AI-DLC Run Stats** section:

```markdown
## AI-DLC Run Stats
- Attempts: 1/3
- Claude calls: 1
- Duration: 180s
- Estimated cost: ~$2.50
```

---

## GitHub Comment Conventions

`build_implementation_prompt` reads issue comments matching these prefixes:

| Prefix | Source | Purpose |
|--------|--------|---------|
| `**Auto-triage**` | Triage bot | File discovery, approval/rejection reasons |
| `**AI-DLC Attempt N failed:**` | Implementation bot | Verification errors from prior attempts |
| `**Implementation Detail:**` | Human | Specs, design notes, context not in the repo |

The `**Implementation Detail:**` convention lets users post detailed guidance
as a comment from any device. The VPS agent picks it up automatically.

---

## Issue Creator (`ai-dlc/create_issue.py`)

### Modes

```bash
# Interactive — prompts for each field, submits via gh
uv run python ai-dlc/create_issue.py

# Skip suggestions
uv run python ai-dlc/create_issue.py --type feature --no-suggest

# Create issues from a spec file
uv run python ai-dlc/create_issue.py --from-spec docs/features/spec.md --dry-run
uv run python ai-dlc/create_issue.py --from-spec docs/features/spec.md --skip 1

# Fix a rejected issue
uv run python ai-dlc/create_issue.py --edit 10

# Preview without submitting
uv run python ai-dlc/create_issue.py --dry-run
```

### `--from-spec` behavior

1. Parses `## Enhancement N:` sections from the spec file
2. Calls Claude to generate structured issue fields (title, expected behavior, criteria)
3. Creates each issue via `gh issue create`
4. Posts the full spec section as an `**Implementation Detail:**` comment
5. Use `--skip 1,2` to skip already-created enhancements

---

## Scheduling

### Option A: launchd (macOS, survives reboot)

```xml
<!-- ~/Library/LaunchAgents/com.patina.triage.plist -->
<key>ProgramArguments</key>
<array>
    <string>/path/to/patina/.venv/bin/python</string>
    <string>/path/to/patina/ai-dlc/triage_issues.py</string>
</array>
<key>StartInterval</key><integer>21600</integer>
```

```xml
<!-- ~/Library/LaunchAgents/com.patina.implement.plist -->
<key>ProgramArguments</key>
<array>
    <string>/path/to/patina/.venv/bin/python</string>
    <string>/path/to/patina/ai-dlc/implement_issue.py</string>
</array>
<key>StartCalendarInterval</key>
<dict><key>Hour</key><integer>2</integer></dict>
```

### Option B: cron

```bash
0 */6 * * * cd ~/Git/patina && uv run python ai-dlc/triage_issues.py >> /tmp/patina-triage.log 2>&1
0 2 * * *   cd ~/Git/patina && uv run python ai-dlc/implement_issue.py >> /tmp/patina-implement.log 2>&1
```

### Option C: manual

```bash
uv run python ai-dlc/triage_issues.py
uv run python ai-dlc/implement_issue.py
```

---

## Issue Creator (`ai-dlc/create_issue.py`)

Interactive CLI that builds a well-formed issue from the template, validates
required fields locally, and either prints markdown for copy-paste or submits
directly via `gh issue create`.

### Usage

```bash
# Interactive — prompts for each field, submits via gh
uv run python ai-dlc/create_issue.py

# Interactive — prints markdown to stdout for copy-paste
uv run python ai-dlc/create_issue.py --dry-run

# Skip the type prompt
uv run python ai-dlc/create_issue.py --type feature
uv run python ai-dlc/create_issue.py --type bug --dry-run
```

### Behavior

1. Prompt for each template field in order
2. Required fields (Summary, Type, Expected Behavior, Acceptance Criteria)
   must be non-empty — re-prompt until provided
3. Optional fields (Files to Modify, Implementation Hints, Dependencies,
   Context) accept blank input and are omitted or filled with defaults
4. Acceptance Criteria always pre-populates the three standard items:
   - `[ ] New unit tests pass`
   - `[ ] All existing tests pass (uv run pytest)`
   - `[ ] uv run ruff check && uv run ruff format --check clean`
   The user can add additional criteria on top of these
5. Story Points is always left blank (triage bot estimates)
6. Current Behavior is only prompted when Type is `bug`

### Script

```python
#!/usr/bin/env python3
"""Build a well-formed GitHub issue from the AI-DLC template."""

import argparse
import subprocess
import sys

REPO = "Sanctum-Origo-Systems/patina"

DEFAULT_ACCEPTANCE = [
    "New unit tests pass",
    "All existing tests pass (`uv run pytest`)",
    "`uv run ruff check && uv run ruff format --check` clean",
]

VALID_TYPES = {"bug", "feature", "refactor"}


def prompt_required(label: str) -> str:
    """Prompt until a non-empty value is provided."""
    while True:
        value = input(f"{label}: ").strip()
        if value:
            return value
        print(f"  {label} is required.")


def prompt_optional(label: str, hint: str = "") -> str:
    """Prompt for an optional field. Returns empty string if skipped."""
    suffix = f" ({hint})" if hint else ""
    return input(f"{label}{suffix} [Enter to skip]: ").strip()


def prompt_multiline(label: str, hint: str = "") -> str:
    """Prompt for multi-line input. Empty line finishes."""
    suffix = f" ({hint})" if hint else ""
    print(f"{label}{suffix} (blank line to finish):")
    lines = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines)


def build_issue(issue_type: str | None = None) -> tuple[str, str]:
    """Interactively build the issue. Returns (title, body)."""
    summary = prompt_required("Summary")

    if issue_type is None:
        while True:
            issue_type = input("Type (bug / feature / refactor): ").strip().lower()
            if issue_type in VALID_TYPES:
                break
            print(f"  Must be one of: {', '.join(sorted(VALID_TYPES))}")

    files = prompt_multiline(
        "Files to Modify",
        "one per line, e.g. src/patina/store.py"
    )

    current_behavior = ""
    if issue_type == "bug":
        current_behavior = prompt_multiline(
            "Current Behavior",
            "what happens now? include error messages"
        )

    expected = prompt_required("Expected Behavior")

    print("\nDefault acceptance criteria (always included):")
    for item in DEFAULT_ACCEPTANCE:
        print(f"  - [ ] {item}")
    extra_criteria = prompt_multiline(
        "Additional Acceptance Criteria",
        "one per line, beyond the defaults above"
    )

    hints = prompt_multiline("Implementation Hints", "optional")
    deps = prompt_optional("Dependencies", "e.g. Depends on #43")
    context = prompt_multiline("Context", "links, related issues, etc.")

    # Build markdown body
    sections = [f"## Summary\n{summary}", f"## Type\n{issue_type}"]

    if files:
        file_lines = "\n".join(f"- {f}" for f in files.split("\n") if f.strip())
        sections.append(f"## Files to Modify\n{file_lines}")
    else:
        sections.append("## Files to Modify\nUnknown")

    if issue_type == "bug" and current_behavior:
        sections.append(f"## Current Behavior\n{current_behavior}")

    sections.append(f"## Expected Behavior\n{expected}")

    criteria_lines = [f"- [ ] {c}" for c in DEFAULT_ACCEPTANCE]
    if extra_criteria:
        for line in extra_criteria.split("\n"):
            line = line.strip().lstrip("- ").lstrip("[] ").strip()
            if line:
                criteria_lines.append(f"- [ ] {line}")
    sections.append(f"## Acceptance Criteria\n" + "\n".join(criteria_lines))

    if hints:
        sections.append(f"## Implementation Hints\n{hints}")

    if deps:
        sections.append(f"## Dependencies\n{deps}")

    if context:
        sections.append(f"## Context\n{context}")

    sections.append("## Story Points\n<!-- Triage bot will estimate -->")

    body = "\n\n".join(sections)
    return summary, body


def main():
    parser = argparse.ArgumentParser(description="Create a Patina GitHub issue")
    parser.add_argument(
        "--type", choices=sorted(VALID_TYPES), default=None,
        help="Issue type (skips the type prompt)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print markdown to stdout instead of creating the issue"
    )
    args = parser.parse_args()

    title, body = build_issue(issue_type=args.type)

    if args.dry_run:
        print("\n--- Issue Markdown ---\n")
        print(f"**Title:** {title}\n")
        print(body)
        return

    result = subprocess.run(
        ["gh", "issue", "create", "--repo", REPO,
         "--title", title, "--body", body],
        text=True
    )
    if result.returncode == 0:
        print("Issue created.")
    else:
        print("Failed to create issue. Printing markdown so you can copy-paste:\n")
        print(f"**Title:** {title}\n")
        print(body)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

---

## Example Issue (Good — Ready)

```markdown
## Summary
Add `--verbose` flag to `patina ingest` that prints each message as ingested.

## Type
feature

## Files to Modify
- `src/patina/cli.py` — add `--verbose` option to `ingest` command
- `src/patina/ingest.py` — pass verbose flag, print on insert
- `tests/test_ingest.py` — test verbose output with capsys

## Expected Behavior
`patina ingest --verbose` prints one line per inserted message:
`[source] sender: first 80 chars of text (timestamp)`

## Acceptance Criteria
- [ ] `patina ingest --verbose` prints one line per inserted message
- [ ] `patina ingest` (without flag) prints nothing extra
- [ ] `uv run pytest tests/test_ingest.py` passes with new test
- [ ] All existing tests pass

## Implementation Hints
Follow the existing `--dry-run` flag pattern in `cli.py`.
`_ingest_messages()` in `ingest.py` is the right place to add the print.

## Story Points
1
```

---

## Example Issue (Bad — Rejected)

```markdown
## Summary
Make ingestion faster

## Type
feature

## Expected Behavior
It should be faster.

## Acceptance Criteria
(none)
```

Rejection: "Needs (1) specific metric for 'faster', (2) which part is slow,
(3) acceptance criteria with measurable thresholds."

---

## Critical Files

| File | Purpose |
|------|---------|
| `ai-dlc/create_issue.py` | Issue builder — interactive, `--from-spec`, `--edit`, `--dry-run` |
| `ai-dlc/triage_issues.py` | Cron 1: evaluate, discover files, label/decompose, cost tracking |
| `ai-dlc/implement_issue.py` | Cron 2: implement, verify, PR, error feedback, batch mode |
| `ai-dlc/run_history.jsonl` | Auto-created — cost/timing log for all runs |
| `.claude/settings.json` | Pre-approved tool permissions for agent |
| `tests/ai_dlc/` | Unit tests for all three scripts |

**Dependencies:** `gh` CLI (authenticated), `claude` CLI (in PATH), `uv`
