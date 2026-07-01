#!/usr/bin/env python3
"""Build a well-formed GitHub issue from the AI-DLC template."""

from __future__ import annotations

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


def build_issue_body(
    summary: str,
    issue_type: str,
    files: str,
    current_behavior: str,
    expected: str,
    extra_criteria: str,
    hints: str,
    deps: str,
    context: str,
) -> str:
    """Assemble the markdown issue body from field values."""
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
    sections.append("## Acceptance Criteria\n" + "\n".join(criteria_lines))

    if hints:
        sections.append(f"## Implementation Hints\n{hints}")

    if deps:
        sections.append(f"## Dependencies\n{deps}")

    if context:
        sections.append(f"## Context\n{context}")

    sections.append("## Story Points\n<!-- Triage bot will estimate -->")

    return "\n\n".join(sections)


def build_issue(issue_type: str | None = None) -> tuple[str, str]:
    """Interactively build the issue. Returns (title, body)."""
    summary = prompt_required("Summary")

    if issue_type is None:
        while True:
            issue_type = input("Type (bug / feature / refactor): ").strip().lower()
            if issue_type in VALID_TYPES:
                break
            print(f"  Must be one of: {', '.join(sorted(VALID_TYPES))}")

    files = prompt_multiline("Files to Modify", "one per line, e.g. src/patina/store.py")

    current_behavior = ""
    if issue_type == "bug":
        current_behavior = prompt_multiline(
            "Current Behavior",
            "what happens now? include error messages",
        )

    expected = prompt_required("Expected Behavior")

    print("\nDefault acceptance criteria (always included):")
    for item in DEFAULT_ACCEPTANCE:
        print(f"  - [ ] {item}")
    extra_criteria = prompt_multiline(
        "Additional Acceptance Criteria",
        "one per line, beyond the defaults above",
    )

    hints = prompt_multiline("Implementation Hints", "optional")
    deps = prompt_optional("Dependencies", "e.g. Depends on #43")
    context = prompt_multiline("Context", "links, related issues, etc.")

    body = build_issue_body(
        summary,
        issue_type,
        files,
        current_behavior,
        expected,
        extra_criteria,
        hints,
        deps,
        context,
    )
    return summary, body


def main():
    parser = argparse.ArgumentParser(description="Create a Patina GitHub issue")
    parser.add_argument(
        "--type",
        choices=sorted(VALID_TYPES),
        default=None,
        help="Issue type (skips the type prompt)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print markdown to stdout instead of creating the issue",
    )
    args = parser.parse_args()

    title, body = build_issue(issue_type=args.type)

    if args.dry_run:
        print("\n--- Issue Markdown ---\n")
        print(f"**Title:** {title}\n")
        print(body)
        return

    result = subprocess.run(
        ["gh", "issue", "create", "--repo", REPO, "--title", title, "--body", body],
        text=True,
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
