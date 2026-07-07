from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import patina.store as store_module

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SLACK_HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z][\w.-]*")


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:60].rstrip("-")


def strip_sensitive(text: str, names: list[str] | None = None) -> str:
    result = _EMAIL_RE.sub("[REDACTED]", text)
    result = _SLACK_HANDLE_RE.sub("[REDACTED]", result)
    if names:
        for name in names:
            name = name.strip()
            if name:
                result = re.sub(re.escape(name), "[REDACTED]", result, flags=re.IGNORECASE)
    return result


def format_draft(
    title: str,
    problem: str,
    issue_type: str,
    files: list[str],
    expected_behavior: str,
    acceptance_criteria: list[str],
) -> str:
    files_str = "\n".join(f"- {f}" for f in files)
    criteria_str = "\n".join(f"- [ ] {c}" for c in acceptance_criteria)

    return (
        f"# {title}\n"
        f"\n"
        f"## Summary\n"
        f"{problem}\n"
        f"\n"
        f"## Type\n"
        f"{issue_type}\n"
        f"\n"
        f"## Files to Modify\n"
        f"{files_str}\n"
        f"\n"
        f"## Expected Behavior\n"
        f"{expected_behavior}\n"
        f"\n"
        f"## Acceptance Criteria\n"
        f"{criteria_str}\n"
    )


_SKILL_CONTENT = """\
# file-issue

File a GitHub issue from conversation context with human review before submission.

## When to use

When the user wants to capture a bug, feature request, or improvement noticed
during a conversation and file it as a GitHub issue without leaving the session
or manually re-typing context.

## Instructions

### Step 1: Extract context from the conversation

Identify the following from the current conversation:

- **Title**: A concise issue title (under 70 characters)
- **Problem**: What went wrong or what is missing
- **Type**: One of bug, feat, refactor, docs, test
- **Files to Modify**: Which source files are affected (use file paths, not line numbers)
- **Expected Behavior**: What should happen instead
- **Acceptance Criteria**: Testable conditions that define done

If any of these are unclear from the conversation, ask the user to clarify
before proceeding.

### Step 2: Strip sensitive data

Before saving the draft, remove all sensitive information using the
patina.issue_draft module. Run via uv run python:

    from patina.issue_draft import strip_sensitive
    sanitized = strip_sensitive(text, names=["CustomerName", "CompanyName"])

Also manually review the draft and remove:
- Real customer or company names (replace with [REDACTED])
- Internal Slack channel names or URLs
- Any credentials, tokens, or API keys
- Real person names that are not project contributors

### Step 3: Save the draft

Save the sanitized draft to ~/.patina/proposed/ using the module.
Run via uv run python:

    from patina.issue_draft import format_draft, strip_sensitive, save_draft

    content = format_draft(
        title="TITLE",
        problem="PROBLEM",
        issue_type="TYPE",
        files=["file1.py", "file2.py"],
        expected_behavior="EXPECTED",
        acceptance_criteria=["criterion 1", "criterion 2"],
    )
    sanitized = strip_sensitive(content, names=["Name1", "Name2"])
    path = save_draft("TITLE", sanitized)

### Step 4: Display the draft for review

Read the saved draft file and display it to the user. Ask whether they want to:
1. Submit - create the GitHub issue now
2. Edit - make changes before submitting
3. Decline - keep the draft in ~/.patina/proposed/ for later

### Step 5a: On approval - submit the issue

Create the issue:

    gh issue create --title "TITLE" --body-file DRAFT_PATH

Then post the implementation detail comment:

    gh issue comment ISSUE_NUMBER --body "**Implementation Detail:**
    **Problem:** PROBLEM_SUMMARY
    **Files:** FILE_LIST
    **Change:** CHANGE_DESCRIPTION"

Display the created issue URL to the user.

### Step 5b: On decline - keep draft

Confirm that the draft remains at its saved path in ~/.patina/proposed/
for later editing. Do not create any issue.

### Step 5c: On edit - modify and re-display

Apply the user requested changes to the draft file, re-display the
updated version, and return to Step 4.
"""


def install_skill(project_root: Path | None = None) -> Path:
    root = project_root or Path.cwd()
    skill_dir = root / ".claude" / "skills"
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "file-issue.md"
    path.write_text(_SKILL_CONTENT)
    return path


def _proposed_dir() -> Path:
    return store_module.DEFAULT_HOME / "proposed"


def save_draft(
    title: str,
    content: str,
    proposed_dir: Path | None = None,
) -> Path:
    dir_path = proposed_dir or _proposed_dir()
    dir_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    slug = slugify(title)
    filename = f"{timestamp}-{slug}.md"

    path = dir_path / filename
    path.write_text(content)
    return path
