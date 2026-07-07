"""Auto-bump pyproject.toml version based on PR title prefix."""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

PYPROJECT_PATH = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"

MINOR_PREFIXES = ("feat:",)
PATCH_PREFIXES = ("fix:", "refactor:", "test:", "docs:")


def parse_version(pyproject_text: str) -> tuple[int, int, int]:
    match = re.search(r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', pyproject_text, re.MULTILINE)
    if not match:
        raise ValueError("Could not find version in pyproject.toml")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def bump_type_from_title(title: str) -> str | None:
    lower = title.lower().strip()
    if any(lower.startswith(p) for p in MINOR_PREFIXES):
        return "minor"
    if any(lower.startswith(p) for p in PATCH_PREFIXES):
        return "patch"
    return None


def compute_new_version(major: int, minor: int, patch: int, kind: str) -> tuple[int, int, int]:
    if kind == "minor":
        return major, minor + 1, 0
    return major, minor, patch + 1


def already_bumped_today(pyproject_path: Path, today: date | None = None) -> bool:
    import subprocess

    ref = today or date.today()
    try:
        cmd = [
            "git",
            "log",
            "--since",
            ref.isoformat(),
            "--all",
            "--oneline",
            "--",
            str(pyproject_path),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=pyproject_path.parent,
        )
        return bool(result.stdout.strip())
    except FileNotFoundError:
        return False


def bump_version(
    title: str,
    *,
    pyproject_path: Path | None = None,
    today: date | None = None,
    skip_git_check: bool = False,
) -> str | None:
    path = pyproject_path or PYPROJECT_PATH
    kind = bump_type_from_title(title)
    if kind is None:
        return None

    if not skip_git_check and already_bumped_today(path, today):
        return None

    text = path.read_text()
    major, minor, patch = parse_version(text)
    new_major, new_minor, new_patch = compute_new_version(major, minor, patch, kind)

    old_version = f'version = "{major}.{minor}.{patch}"'
    new_version = f'version = "{new_major}.{new_minor}.{new_patch}"'
    new_text = text.replace(old_version, new_version, 1)
    path.write_text(new_text)

    return f"{new_major}.{new_minor}.{new_patch}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bump pyproject.toml version from PR title")
    parser.add_argument("title", help="PR title (e.g. 'feat: add widget')")
    args = parser.parse_args()
    result = bump_version(args.title)
    if result:
        print(f"Bumped to {result}")
    else:
        print("No bump needed")
