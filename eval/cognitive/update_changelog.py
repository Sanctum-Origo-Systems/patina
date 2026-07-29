"""Daily changelog + version bump: fetch merged PRs, append, bump, create PR."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

CHANGELOG_DIR = Path(__file__).parent
CHANGELOG_PATH = CHANGELOG_DIR / "CHANGELOG.md"
ARCHIVE_PATH = CHANGELOG_DIR / "changelog-archive.md"
PYPROJECT_PATH = CHANGELOG_DIR.parent.parent / "pyproject.toml"
REPO_DIR = CHANGELOG_DIR.parent.parent

MINOR_PREFIXES = ("feat:",)
PATCH_PREFIXES = ("fix:", "refactor:", "test:", "docs:")


def append_entry(
    number: int,
    title: str,
    cost: float,
    *,
    changelog_path: Path | None = None,
    today: date | None = None,
) -> None:
    path = changelog_path or CHANGELOG_PATH
    stamp = (today or date.today()).isoformat()
    line = f"- #{number}: {title} (${cost}) [{stamp}]\n"
    with open(path, "a") as f:
        f.write(line)


def trim_changelog(
    days: int = 14,
    *,
    changelog_path: Path | None = None,
    archive_path: Path | None = None,
    today: date | None = None,
) -> None:
    cl = changelog_path or CHANGELOG_PATH
    ar = archive_path or ARCHIVE_PATH
    ref = today or date.today()
    cutoff = ref - timedelta(days=days)

    if not cl.exists():
        return

    text = cl.read_text()
    if not text:
        return

    keep: list[str] = []
    archive: list[str] = []

    for line in text.splitlines(keepends=True):
        entry_date = _parse_date(line)
        if entry_date is not None and entry_date < cutoff:
            archive.append(line)
        else:
            keep.append(line)

    if not archive:
        return

    with open(ar, "a") as f:
        f.writelines(archive)

    cl.write_text("".join(keep))


def _parse_date(line: str) -> date | None:
    start = line.rfind("[")
    end = line.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return date.fromisoformat(line[start + 1 : end])
    except ValueError:
        return None


def bump_type_from_title(title: str) -> str | None:
    lower = title.lower().strip()
    if any(lower.startswith(p) for p in MINOR_PREFIXES):
        return "minor"
    if any(lower.startswith(p) for p in PATCH_PREFIXES):
        return "patch"
    return None


def highest_bump_type(titles: list[str]) -> str | None:
    """Return the highest bump type across multiple PR titles."""
    has_minor = any(bump_type_from_title(t) == "minor" for t in titles)
    has_patch = any(bump_type_from_title(t) == "patch" for t in titles)
    if has_minor:
        return "minor"
    if has_patch:
        return "patch"
    return None


def bump_version(
    kind: str,
    *,
    pyproject_path: Path | None = None,
) -> str | None:
    """Bump pyproject.toml version by kind (minor or patch). Returns new version or None."""
    path = pyproject_path or PYPROJECT_PATH
    text = path.read_text()
    match = re.search(r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', text, re.MULTILINE)
    if not match:
        return None

    major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if kind == "minor":
        new = f"{major}.{minor + 1}.0"
    else:
        new = f"{major}.{minor}.{patch + 1}"

    old_version = f'version = "{major}.{minor}.{patch}"'
    new_version = f'version = "{new}"'
    path.write_text(text.replace(old_version, new_version, 1))
    return new


def existing_pr_numbers(changelog_path: Path | None = None) -> set[int]:
    """Return PR numbers already in the changelog to avoid duplicates."""
    path = changelog_path or CHANGELOG_PATH
    if not path.exists():
        return set()
    numbers = set()
    for match in re.finditer(r"^- #(\d+):", path.read_text(), re.MULTILINE):
        numbers.add(int(match.group(1)))
    return numbers


def has_open_changelog_pr(repo: str) -> bool:
    """Check if an open PR already exists from a chore/changelog-* branch."""
    result = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "open",
            "--search",
            "head:chore/changelog-",
            "--json",
            "number",
            "--limit",
            "1",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    prs = json.loads(result.stdout)
    return len(prs) > 0


def fetch_merged_prs(repo: str, since_days: int = 1) -> list[dict]:
    """Fetch PRs merged in the last N days, excluding chore: PRs."""
    since = (date.today() - timedelta(days=since_days)).isoformat()
    result = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "merged",
            "--search",
            f"merged:>={since}",
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
    return [pr for pr in prs if not pr["title"].lower().startswith("chore:")]


def extract_cost(body: str) -> float:
    match = re.search(r"- Cost: \$(\d+\.?\d*)", body or "")
    return float(match.group(1)) if match else 0.0


def daily(repo: str, since_days: int = 1) -> None:
    """Batch changelog + version bump for all PRs merged since last run."""
    if has_open_changelog_pr(repo):
        print("Open changelog PR already exists — skipping.")
        return

    prs = fetch_merged_prs(repo, since_days)
    if not prs:
        print("No new merged PRs.")
        return

    existing = existing_pr_numbers()
    new_prs = [pr for pr in prs if pr["number"] not in existing]
    if not new_prs:
        print("All merged PRs already in changelog.")
        return

    for pr in new_prs:
        cost = extract_cost(pr.get("body", ""))
        append_entry(pr["number"], pr["title"], cost)
        print(f"  Added #{pr['number']}: {pr['title']}")

    trim_changelog()

    titles = [pr["title"] for pr in new_prs]
    kind = highest_bump_type(titles)
    new_version = None
    if kind:
        new_version = bump_version(kind)
        if new_version:
            print(f"  Bumped version to {new_version}")

    stamp = date.today().isoformat()
    branch = f"chore/changelog-{stamp}"
    subprocess.run(["git", "checkout", "-b", branch], cwd=REPO_DIR)
    subprocess.run(["git", "add", "eval/cognitive/CHANGELOG.md"], cwd=REPO_DIR)
    subprocess.run(
        ["git", "add", "eval/cognitive/changelog-archive.md"],
        cwd=REPO_DIR,
        capture_output=True,
    )
    if new_version:
        subprocess.run(["git", "add", "pyproject.toml"], cwd=REPO_DIR)

    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_DIR, capture_output=True)
    if diff.returncode == 0:
        print("No changes to commit.")
        subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR)
        return

    version_suffix = f" (v{new_version})" if new_version else ""
    commit_msg = f"chore: update changelog and version{version_suffix}"
    subprocess.run(
        ["git", "commit", "-m", commit_msg],
        cwd=REPO_DIR,
        env={
            **__import__("os").environ,
            "GIT_AUTHOR_NAME": "github-actions[bot]",
            "GIT_AUTHOR_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "github-actions[bot]",
            "GIT_COMMITTER_EMAIL": "41898282+github-actions[bot]@users.noreply.github.com",
        },
    )
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=REPO_DIR)

    pr_title = f"chore: update changelog and version{version_suffix}"
    pr_body = f"Daily changelog update ({stamp}). {len(new_prs)} PR(s) added."
    subprocess.run(
        ["gh", "pr", "create", "--title", pr_title, "--body", pr_body, "--base", "main"],
        cwd=REPO_DIR,
    )
    subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR)
    print(f"Created PR: {pr_title}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Update changelog and bump version")
    sub = parser.add_subparsers(dest="command")

    single = sub.add_parser("single", help="Append a single PR entry")
    single.add_argument("--number", type=int, required=True)
    single.add_argument("--title", required=True)
    single.add_argument("--cost", type=float, required=True)

    batch = sub.add_parser("daily", help="Batch update from merged PRs and create PR")
    batch.add_argument("--repo", required=True, help="GitHub owner/repo")
    batch.add_argument("--since-days", type=int, default=1, help="Look back N days (default: 1)")

    args = parser.parse_args(argv)

    if args.command == "single":
        append_entry(number=args.number, title=args.title, cost=args.cost)
        trim_changelog()
        kind = bump_type_from_title(args.title)
        if kind:
            new_version = bump_version(kind)
            if new_version:
                print(f"Bumped version to {new_version}")
    elif args.command == "daily":
        daily(args.repo, args.since_days)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
