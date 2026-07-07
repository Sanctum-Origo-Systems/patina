"""Install the file-issue skill to .claude/skills/file-issue.md."""

from pathlib import Path

from patina.issue_draft import install_skill


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    path = install_skill(project_root=project_root)
    print(f"Installed skill: {path}")


if __name__ == "__main__":
    main()
