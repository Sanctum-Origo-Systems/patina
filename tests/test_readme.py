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


def test_readme_cognitive_framework_framing():
    content = README.read_text()
    assert "cognitive framework" in content.lower()
    assert "assistant" not in content.split("##")[0].lower()


def test_readme_observer_builder_loop():
    content = README.read_text()
    assert "observer" in content.lower()
    assert "builder" in content.lower()
    assert "human gates" in content.lower() or "human gate" in content.lower()


def test_readme_blog_post_links():
    content = README.read_text()
    assert "https://andywidjaja.com/blog/110-pipeline" in content
    assert "https://andywidjaja.com/blog/observer-builder" in content


def test_readme_read_more_section():
    content = README.read_text()
    assert "## Read More" in content
