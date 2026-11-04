"""Daily changelog + version bump: fetch merged PRs, append, bump, create PR."""

from __future__ import annotations

import argparse
import json
import os
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

_COMMIT_PREFIXES = ("fix", "feat", "refactor", "test", "docs", "chore")

DEFAULT_LOOKBACK_DAYS = 7

_ENTRY_RE = re.compile(r"^- #(\d+): (.*)$")
_HEADER_RE = re.compile(r"^## v(\d+\.\d+\.\d+)\b")

_BOT_NAME = "github-actions[bot]"
_BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"


def clean_title(title: str) -> str:
    """Strip duplicate conventional-commit prefixes and trailing (#NNN) refs."""
    title = title.strip()
    title = re.sub(r"\s*\(#\d+\)\s*$", "", title)
    for p in _COMMIT_PREFIXES:
        dup = re.compile(rf"^{p}:\s*{p}:\s*", re.IGNORECASE)
        if dup.match(title):
            return dup.sub(f"{p.capitalize()}: ", title).strip()
    for p in _COMMIT_PREFIXES:
        single = re.compile(rf"^{p}:", re.IGNORECASE)
        if single.match(title):
            return (p.capitalize() + title[len(p) :]).strip()
    return title.strip()


def current_version(pyproject_path: Path | None = None) -> str:
    path = pyproject_path or PYPROJECT_PATH
    text = path.read_text()
    match = re.search(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def append_entry(
    number: int,
    title: str,
    cost: float,
    *,
    version: str,
    changelog_path: Path | None = None,
    today: date | None = None,
) -> None:
    path = changelog_path or CHANGELOG_PATH
    stamp = (today or date.today()).isoformat()
    cleaned = clean_title(title)
    entry = f"- #{number}: {cleaned} (${cost:.2f})"
    header_line = f"## v{version} ({stamp})"

    if not path.exists() or not path.read_text().strip():
        path.write_text(f"{header_line}\n{entry}\nTotal: 1 PRs, ${cost:.2f}\n")
        return

    text = path.read_text()
    lines = text.splitlines(keepends=True)

    version_prefix = f"## v{version} "
    header_idx = None
    for i, line in enumerate(lines):
        if line.startswith(version_prefix):
            header_idx = i
            break

    if header_idx is not None:
        total_idx = None
        for i in range(header_idx + 1, len(lines)):
            if lines[i].startswith("Total:"):
                total_idx = i
                break
            if lines[i].startswith("## "):
                break

        if total_idx is not None:
            total_match = re.match(r"Total: (\d+) PRs?, \$(\d+\.?\d*)", lines[total_idx])
            if total_match:
                n = int(total_match.group(1)) + 1
                total_cost = float(total_match.group(2)) + cost
                lines.insert(total_idx, entry + "\n")
                lines[total_idx + 1] = f"Total: {n} PRs, ${total_cost:.2f}\n"
        else:
            lines.insert(header_idx + 1, entry + "\n")
            lines.insert(header_idx + 2, f"Total: 1 PRs, ${cost:.2f}\n")
    else:
        block = f"{header_line}\n{entry}\nTotal: 1 PRs, ${cost:.2f}\n\n"
        path.write_text(block + text)
        return

    path.write_text("".join(lines))


def _parse_version_blocks(text: str) -> list[tuple[date | None, str]]:
    """Parse changelog into (header_date, block_text) tuples."""
    blocks: list[tuple[date | None, str]] = []
    current_date: date | None = None
    current_lines: list[str] = []

    for line in text.splitlines(keepends=True):
        if line.startswith("## "):
            if current_lines:
                blocks.append((current_date, "".join(current_lines)))
            current_lines = [line]
            m = re.search(r"\((\d{4}-\d{2}-\d{2})\)", line)
            current_date = date.fromisoformat(m.group(1)) if m else None
        else:
            current_lines.append(line)

    if current_lines:
        blocks.append((current_date, "".join(current_lines)))

    return blocks


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
    if not text.strip():
        return

    blocks = _parse_version_blocks(text)
    keep: list[str] = []
    archive: list[str] = []

    for block_date, block_text in blocks:
        if block_date is not None and block_date < cutoff:
            archive.append(block_text)
        else:
            keep.append(block_text)

    if not archive:
        return

    with open(ar, "a") as f:
        f.writelines(archive)

    cl.write_text("".join(keep))


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


def next_version(version: str, kind: str) -> str:
    """Return version bumped by kind (minor or patch), without touching any file."""
    major, minor, patch = (int(part) for part in version.split("."))
    if kind == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


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
    new = next_version(f"{major}.{minor}.{patch}", kind)

    old_version = f'version = "{major}.{minor}.{patch}"'
    new_version = f'version = "{new}"'
    path.write_text(text.replace(old_version, new_version, 1))
    return new


def set_version(new: str, *, pyproject_path: Path | None = None) -> None:
    """Overwrite the pyproject.toml version with new."""
    path = pyproject_path or PYPROJECT_PATH
    text = path.read_text()
    path.write_text(
        re.sub(
            r'^(version\s*=\s*)"\d+\.\d+\.\d+"',
            rf'\g<1>"{new}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
    )


def top_block(changelog_path: Path | None = None) -> tuple[str | None, list[tuple[int, str]]]:
    """Return the top version block's version and its (number, title) entries."""
    path = changelog_path or CHANGELOG_PATH
    if not path.exists():
        return None, []
    version = None
    entries: list[tuple[int, str]] = []
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            if version is not None:
                break
            match = _HEADER_RE.match(line)
            if match:
                version = match.group(1)
            continue
        entry = _ENTRY_RE.match(line)
        if version is not None and entry:
            entries.append((int(entry.group(1)), entry.group(2)))
    return version, entries


def rename_top_block(old: str, new: str, *, changelog_path: Path | None = None) -> None:
    """Rename the first `## v{old} (...)` header to `## v{new} (...)`, keeping its date."""
    path = changelog_path or CHANGELOG_PATH
    text = path.read_text()
    path.write_text(
        re.sub(rf"^## v{re.escape(old)}\b", f"## v{new}", text, count=1, flags=re.MULTILINE)
    )


def latest_block_date(changelog_path: Path | None = None) -> date | None:
    """Return the date of the newest dated version block in the changelog."""
    path = changelog_path or CHANGELOG_PATH
    if not path.exists():
        return None
    for block_date, _ in _parse_version_blocks(path.read_text()):
        if block_date is not None:
            return block_date
    return None


def lookback_days(
    since_days: int = 1,
    *,
    changelog_path: Path | None = None,
    today: date | None = None,
) -> int:
    """Days to look back: everything since the latest changelog block, at least since_days.

    Falls back to DEFAULT_LOOKBACK_DAYS when the changelog has no dated block.
    Repeat coverage is safe because daily() skips PRs already listed.
    """
    latest = latest_block_date(changelog_path)
    ref = today or date.today()
    days = (ref - latest).days if latest else DEFAULT_LOOKBACK_DAYS
    return max(since_days, days)


def existing_pr_numbers(changelog_path: Path | None = None) -> set[int]:
    """Return PR numbers already in the changelog to avoid duplicates."""
    path = changelog_path or CHANGELOG_PATH
    if not path.exists():
        return set()
    numbers = set()
    for match in re.finditer(r"^- #(\d+):", path.read_text(), re.MULTILINE):
        numbers.add(int(match.group(1)))
    return numbers


def find_open_changelog_pr(repo: str) -> dict | None:
    """Return the open chore/changelog-* PR as {"number", "headRefName"}, or None."""
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
            "number,headRefName",
            "--limit",
            "1",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    prs = json.loads(result.stdout)
    return prs[0] if prs else None


def has_open_changelog_pr(repo: str) -> bool:
    """Check if an open PR already exists from a chore/changelog-* branch."""
    return find_open_changelog_pr(repo) is not None


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


def _bot_env() -> dict[str, str]:
    return {
        **os.environ,
        "GIT_AUTHOR_NAME": _BOT_NAME,
        "GIT_AUTHOR_EMAIL": _BOT_EMAIL,
        "GIT_COMMITTER_NAME": _BOT_NAME,
        "GIT_COMMITTER_EMAIL": _BOT_EMAIL,
    }


def update_open_pr(repo: str, open_pr: dict, prs: list[dict]) -> None:
    """Add new merged PRs to an open changelog PR's branch, building on its head.

    The version is recomputed from main's pyproject.toml over every PR in the
    branch's top block, so bumps never stack. Never force-pushes or resets.
    """
    number = open_pr["number"]
    branch = open_pr["headRefName"]

    # Read main's state before switching to the branch.
    main_existing = existing_pr_numbers()
    main_version = current_version()

    candidates = [pr for pr in prs if pr["number"] not in main_existing]
    if not candidates:
        print("All merged PRs already in changelog.")
        return

    for cmd in (
        ["git", "fetch", "origin", branch],
        ["git", "checkout", branch],
        ["git", "merge", "--ff-only", f"origin/{branch}"],
    ):
        result = subprocess.run(cmd, cwd=REPO_DIR)
        if result.returncode != 0:
            print(f"Could not sync {branch} ({' '.join(cmd)} failed) — leaving PR #{number}.")
            subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR)
            return

    branch_existing = existing_pr_numbers()
    new_prs = [pr for pr in candidates if pr["number"] not in branch_existing]
    if not new_prs:
        print(f"All merged PRs already in changelog PR #{number}.")
        subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR)
        return

    block_version, block_entries = top_block()
    titles = [title for n, title in block_entries if n not in main_existing]
    titles += [pr["title"] for pr in new_prs]
    kind = highest_bump_type(titles)
    version = next_version(main_version, kind) if kind else (block_version or main_version)

    if block_version and block_version not in (main_version, version):
        rename_top_block(block_version, version)
        print(f"  Renamed block v{block_version} -> v{version}")

    version_changed = current_version() != version
    if version_changed:
        set_version(version)
        subprocess.run(["uv", "lock"], cwd=REPO_DIR, check=True)
        print(f"  Set version to {version}")

    for pr in new_prs:
        cost = extract_cost(pr.get("body", ""))
        append_entry(pr["number"], pr["title"], cost, version=version)
        print(f"  Added #{pr['number']}: {pr['title']}")

    trim_changelog()

    subprocess.run(["git", "add", "eval/cognitive/CHANGELOG.md"], cwd=REPO_DIR)
    subprocess.run(
        ["git", "add", "eval/cognitive/changelog-archive.md"],
        cwd=REPO_DIR,
        capture_output=True,
    )
    if version_changed:
        subprocess.run(["git", "add", "pyproject.toml"], cwd=REPO_DIR)
        subprocess.run(["git", "add", "uv.lock"], cwd=REPO_DIR)

    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_DIR, capture_output=True)
    if diff.returncode == 0:
        print("No changes to commit.")
        subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR)
        return

    refs = ", ".join(f"#{pr['number']}" for pr in new_prs)
    commit_msg = f"chore: add {refs} to v{version} changelog"
    subprocess.run(["git", "commit", "-m", commit_msg], cwd=REPO_DIR, env=_bot_env())
    subprocess.run(["git", "push", "origin", branch], cwd=REPO_DIR)

    added = len([n for n, _ in top_block()[1] if n not in main_existing])
    stamp = date.today().isoformat()
    pr_title = f"chore: update changelog and version (v{version})"
    pr_body = f"Daily changelog update ({stamp}). {added} PR(s) added."
    subprocess.run(
        [
            "gh",
            "pr",
            "edit",
            str(number),
            "--repo",
            repo,
            "--title",
            pr_title,
            "--body",
            pr_body,
        ],
        cwd=REPO_DIR,
    )
    subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR)
    print(f"Updated PR #{number}: {pr_title}")


def daily(repo: str, since_days: int = 1) -> None:
    """Batch changelog + version bump for all PRs merged since last run.

    With an open chore/changelog-* PR, the new PRs are added to that PR's
    branch; otherwise a new branch and PR are created.
    """
    open_pr = find_open_changelog_pr(repo)

    prs = fetch_merged_prs(repo, lookback_days(since_days))
    if not prs:
        print("No new merged PRs.")
        return

    if open_pr:
        update_open_pr(repo, open_pr, prs)
        return

    existing = existing_pr_numbers()
    new_prs = [pr for pr in prs if pr["number"] not in existing]
    if not new_prs:
        print("All merged PRs already in changelog.")
        return

    titles = [pr["title"] for pr in new_prs]
    kind = highest_bump_type(titles)
    new_version = None
    if kind:
        new_version = bump_version(kind)
        if new_version:
            subprocess.run(["uv", "lock"], cwd=REPO_DIR, check=True)
            print(f"  Bumped version to {new_version}")

    version = new_version or current_version()

    for pr in new_prs:
        cost = extract_cost(pr.get("body", ""))
        append_entry(pr["number"], pr["title"], cost, version=version)
        print(f"  Added #{pr['number']}: {pr['title']}")

    trim_changelog()

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
        subprocess.run(["git", "add", "uv.lock"], cwd=REPO_DIR)

    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_DIR, capture_output=True)
    if diff.returncode == 0:
        print("No changes to commit.")
        subprocess.run(["git", "checkout", "main"], cwd=REPO_DIR)
        return

    version_suffix = f" (v{new_version})" if new_version else ""
    commit_msg = f"chore: update changelog and version{version_suffix}"
    subprocess.run(["git", "commit", "-m", commit_msg], cwd=REPO_DIR, env=_bot_env())
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
    single.add_argument("--version", help="Version to group under (default: current)")

    batch = sub.add_parser("daily", help="Batch update from merged PRs and create PR")
    batch.add_argument("--repo", required=True, help="GitHub owner/repo")
    batch.add_argument(
        "--since-days",
        type=int,
        default=1,
        help="Look back at least N days (default: 1; widened to the latest changelog block date)",
    )

    args = parser.parse_args(argv)

    if args.command == "single":
        version = args.version or current_version()
        append_entry(number=args.number, title=args.title, cost=args.cost, version=version)
        trim_changelog()
        kind = bump_type_from_title(args.title)
        if kind:
            new_version = bump_version(kind)
            if new_version:
                subprocess.run(["uv", "lock"], cwd=REPO_DIR, check=True)
                print(f"Bumped version to {new_version}")
    elif args.command == "daily":
        daily(args.repo, args.since_days)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
