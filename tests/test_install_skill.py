"""Test that installs the file-issue skill to a temporary directory."""

from __future__ import annotations

from patina.issue_draft import install_skill


def test_install_skill_to_project(tmp_path):
    path = install_skill(project_root=tmp_path)
    assert path.exists()
    content = path.read_text()
    assert "file-issue" in content
    assert "gh issue create" in content
