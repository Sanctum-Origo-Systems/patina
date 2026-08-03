from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
SRC_DIR = REPO_ROOT / "src"


def test_autoloop_not_in_dependencies():
    content = PYPROJECT.read_text()
    for line in content.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("#"):
            continue
        assert "autoloop" not in stripped or "[dependency-groups]" in stripped, (
            f"autoloop should not be a Python dependency: {line.strip()}"
        )


def test_no_python_imports_of_autoloop():
    for py_file in SRC_DIR.rglob("*.py"):
        content = py_file.read_text()
        for lineno, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "import autoloop" not in stripped, (
                f"{py_file.relative_to(REPO_ROOT)}:{lineno} imports autoloop as a Python module"
            )
