from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_HOME = Path.home() / ".patina"

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_SLACK_HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z][\w-]*\.[A-Za-z][\w.-]*")
_SLACK_URL_RE = re.compile(r"https?://[A-Za-z0-9.-]*\.slack\.com/\S*")


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:60].rstrip("-")


def strip_sensitive(text: str, names: list[str] | None = None) -> str:
    result = _EMAIL_RE.sub("[REDACTED]", text)
    result = _SLACK_HANDLE_RE.sub("[REDACTED]", result)
    result = _SLACK_URL_RE.sub("[REDACTED]", result)
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


_PACKAGE_DIR = Path(__file__).resolve().parent


def _skill_source_path() -> Path:
    return _PACKAGE_DIR.parent.parent / ".claude" / "skills" / "file-issue.md"


def install_skill(project_root: Path | None = None) -> Path:
    root = project_root or Path.cwd()
    skill_dir = root / ".claude" / "skills"
    skill_dir.mkdir(parents=True, exist_ok=True)
    dest = skill_dir / "file-issue.md"
    dest.write_text(_skill_source_path().read_text())
    return dest


def _proposed_dir() -> Path:
    return _DEFAULT_HOME / "proposed"


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
