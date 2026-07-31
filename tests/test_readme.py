from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"


def test_readme_exists():
    assert README.exists()


def test_readme_contains_autoloop_section():
    content = README.read_text()
    assert "## Related" in content


def test_readme_contains_autoloop_link():
    content = README.read_text()
    assert "https://github.com/Sanctum-Origo-Systems/autoloop" in content


def test_readme_autoloop_description():
    content = README.read_text()
    assert "autonomous builder pipeline" in content
