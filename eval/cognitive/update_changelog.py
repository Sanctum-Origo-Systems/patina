"""Append and trim logic for eval/cognitive/CHANGELOG.md."""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

CHANGELOG_DIR = Path(__file__).parent
CHANGELOG_PATH = CHANGELOG_DIR / "CHANGELOG.md"
ARCHIVE_PATH = CHANGELOG_DIR / "changelog-archive.md"


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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Append an entry to CHANGELOG.md")
    parser.add_argument("--number", type=int, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--cost", type=float, required=True)
    args = parser.parse_args(argv)
    append_entry(number=args.number, title=args.title, cost=args.cost)
    trim_changelog()


if __name__ == "__main__":
    main()
