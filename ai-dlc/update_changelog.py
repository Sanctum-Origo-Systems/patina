#!/usr/bin/env python3
"""Update eval/cognitive/CHANGELOG.md from recently merged PRs.

Run daily via cron or manually:
    uv run python ai-dlc/update_changelog.py
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROLLING_DAYS = 14

_MODULE_DIR = Path(__file__).resolve().parent


@dataclass
class ChangelogCfg:
    repo: str = "Sanctum-Origo-Systems/patina"
    repo_dir: Path = field(default_factory=lambda: _MODULE_DIR.parent)


def fetch_merged_prs(since_days: int = 7) -> list[dict]:
    """Fetch PRs merged in the last N days."""
    cfg = ChangelogCfg()
    since = (datetime.now(UTC) - timedelta(days=since_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            cfg.repo,
            "--state",
            "merged",
            "--json",
            "number,title,body,mergedAt",
            "--limit",
            "50",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    prs = json.loads(result.stdout)
    return [p for p in prs if p.get("mergedAt", "") >= since]


def extract_cost(body: str) -> float:
    """Extract cost from PR body's AI-DLC Run Stats section."""
    match = re.search(r"- Cost: \$(\d+\.?\d*)", body or "")
    return float(match.group(1)) if match else 0.0


def extract_issue_number(body: str) -> int | None:
    """Extract linked issue number from Closes #N."""
    match = re.search(r"Closes #(\d+)", body or "")
    return int(match.group(1)) if match else None


def existing_entries(cfg: ChangelogCfg) -> set[int]:
    """Return PR numbers already in the changelog."""
    changelog = cfg.repo_dir / "eval" / "cognitive" / "CHANGELOG.md"
    if not changelog.exists():
        return set()
    numbers = set()
    for match in re.finditer(r"PR #(\d+)", changelog.read_text()):
        numbers.add(int(match.group(1)))
    return numbers


def append_entries(prs: list[dict], cfg: ChangelogCfg) -> int:
    """Append new PR entries to CHANGELOG.md. Returns count added."""
    changelog = cfg.repo_dir / "eval" / "cognitive" / "CHANGELOG.md"
    known = existing_entries(cfg)
    new_prs = [p for p in prs if p["number"] not in known]
    if not new_prs:
        return 0

    changelog.parent.mkdir(parents=True, exist_ok=True)

    by_date: dict[str, list[str]] = {}
    for pr in sorted(new_prs, key=lambda p: p["mergedAt"]):
        date = pr["mergedAt"][:10]
        cost = extract_cost(pr.get("body", ""))
        issue = extract_issue_number(pr.get("body", ""))
        cost_str = f" (${cost:.2f})" if cost else ""
        issue_str = f" #{issue}" if issue else ""
        entry = f"- {pr['title']}{issue_str}{cost_str} (PR #{pr['number']})"
        by_date.setdefault(date, []).append(entry)

    new_lines = []
    for date in sorted(by_date.keys(), reverse=True):
        new_lines.append(f"\n## {date}")
        new_lines.extend(by_date[date])

    if changelog.exists():
        existing = changelog.read_text()
    else:
        existing = "# Cognitive Changelog\n"

    header = "# Cognitive Changelog\n"
    rest = existing.replace(header, "", 1)
    changelog.write_text(header + "\n".join(new_lines) + "\n" + rest)

    return len(new_prs)


def trim_changelog(cfg: ChangelogCfg) -> None:
    """Move entries older than ROLLING_DAYS to the archive."""
    changelog = cfg.repo_dir / "eval" / "cognitive" / "CHANGELOG.md"
    archive = cfg.repo_dir / "eval" / "cognitive" / "changelog-archive.md"
    if not changelog.exists():
        return

    cutoff = (datetime.now(UTC) - timedelta(days=ROLLING_DAYS)).strftime("%Y-%m-%d")
    lines = changelog.read_text().split("\n")

    keep = []
    archive_lines = []
    current_date = None

    for line in lines:
        date_match = re.match(r"^## (\d{4}-\d{2}-\d{2})", line)
        if date_match:
            current_date = date_match.group(1)

        if current_date and current_date < cutoff:
            archive_lines.append(line)
        else:
            keep.append(line)

    if archive_lines:
        changelog.write_text("\n".join(keep))
        archive_text = "\n".join(archive_lines) + "\n"
        if archive.exists():
            archive_text = archive_text + archive.read_text()
        archive.write_text(archive_text)


def commit_and_create_pr() -> None:
    """Commit changelog changes to a branch and create a PR."""
    cfg = ChangelogCfg()
    changelog = cfg.repo_dir / "eval" / "cognitive" / "CHANGELOG.md"
    archive = cfg.repo_dir / "eval" / "cognitive" / "changelog-archive.md"

    subprocess.run(["git", "add", str(changelog)], cwd=cfg.repo_dir)
    if archive.exists():
        subprocess.run(["git", "add", str(archive)], cwd=cfg.repo_dir)

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=cfg.repo_dir,
    )
    if result.returncode == 0:
        return

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    branch = f"chore/changelog-{today}"

    existing = subprocess.run(
        ["git", "branch", "--list", branch],
        capture_output=True,
        text=True,
        cwd=cfg.repo_dir,
    )
    if existing.stdout.strip():
        print(f"Branch {branch} already exists, skipping.")
        subprocess.run(["git", "checkout", "--", "."], cwd=cfg.repo_dir)
        return

    subprocess.run(["git", "checkout", "-b", branch], cwd=cfg.repo_dir)
    subprocess.run(
        ["git", "commit", "-m", "chore: update cognitive changelog"],
        cwd=cfg.repo_dir,
    )
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=cfg.repo_dir)

    subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            cfg.repo,
            "--title",
            f"chore: update cognitive changelog ({today})",
            "--body",
            "Automated changelog update from merged PRs.\n\n"
            "Generated by `ai-dlc/update_changelog.py`.",
            "--head",
            branch,
            "--base",
            "main",
        ],
        cwd=cfg.repo_dir,
    )

    subprocess.run(["git", "checkout", "main"], cwd=cfg.repo_dir)


def main():
    cfg = ChangelogCfg()
    subprocess.run(["git", "checkout", "main"], cwd=cfg.repo_dir)
    subprocess.run(["git", "pull", "--ff-only", "origin", "main"], cwd=cfg.repo_dir)

    prs = fetch_merged_prs(since_days=ROLLING_DAYS)
    added = append_entries(prs, cfg)
    trim_changelog(cfg)

    if added:
        print(f"Added {added} new entries to CHANGELOG.md")
        commit_and_create_pr()
    else:
        print("No new entries to add.")


if __name__ == "__main__":
    main()
