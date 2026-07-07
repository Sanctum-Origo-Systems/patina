"""Tests for eval/cognitive/bump_version.py."""

from __future__ import annotations

from pathlib import Path

import pytest
from eval.cognitive.bump_version import (
    bump_type_from_title,
    bump_version,
    compute_new_version,
    parse_version,
)

TEMPLATE = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "patina"
version = "{version}"
description = "test"
"""


@pytest.fixture()
def pyproject(tmp_path: Path) -> Path:
    p = tmp_path / "pyproject.toml"
    p.write_text(TEMPLATE.format(version="0.6.0"))
    return p


class TestParseVersion:
    def test_parses_standard_version(self) -> None:
        text = TEMPLATE.format(version="1.2.3")
        assert parse_version(text) == (1, 2, 3)

    def test_parses_zero_version(self) -> None:
        text = TEMPLATE.format(version="0.0.0")
        assert parse_version(text) == (0, 0, 0)

    def test_raises_on_missing_version(self) -> None:
        with pytest.raises(ValueError, match="Could not find version"):
            parse_version("[project]\nname = 'x'\n")


class TestBumpTypeFromTitle:
    def test_feat_returns_minor(self) -> None:
        assert bump_type_from_title("feat: add new widget") == "minor"

    def test_feat_case_insensitive(self) -> None:
        assert bump_type_from_title("Feat: add new widget") == "minor"

    def test_fix_returns_patch(self) -> None:
        assert bump_type_from_title("fix: repair login") == "patch"

    def test_refactor_returns_patch(self) -> None:
        assert bump_type_from_title("refactor: clean up utils") == "patch"

    def test_test_returns_patch(self) -> None:
        assert bump_type_from_title("test: add coverage") == "patch"

    def test_docs_returns_patch(self) -> None:
        assert bump_type_from_title("docs: update readme") == "patch"

    def test_unknown_prefix_returns_none(self) -> None:
        assert bump_type_from_title("chore: update deps") is None

    def test_no_prefix_returns_none(self) -> None:
        assert bump_type_from_title("random PR title") is None

    def test_leading_whitespace(self) -> None:
        assert bump_type_from_title("  feat: spaced") == "minor"


class TestComputeNewVersion:
    def test_minor_bump(self) -> None:
        assert compute_new_version(0, 6, 0, "minor") == (0, 7, 0)

    def test_minor_bump_resets_patch(self) -> None:
        assert compute_new_version(0, 6, 3, "minor") == (0, 7, 0)

    def test_patch_bump(self) -> None:
        assert compute_new_version(0, 7, 0, "patch") == (0, 7, 1)

    def test_patch_bump_increments(self) -> None:
        assert compute_new_version(1, 2, 9, "patch") == (1, 2, 10)


class TestBumpVersion:
    def test_feat_bumps_minor(self, pyproject: Path) -> None:
        result = bump_version("feat: add widget", pyproject_path=pyproject, skip_git_check=True)
        assert result == "0.7.0"
        assert 'version = "0.7.0"' in pyproject.read_text()

    def test_fix_bumps_patch(self, pyproject: Path) -> None:
        result = bump_version("fix: repair bug", pyproject_path=pyproject, skip_git_check=True)
        assert result == "0.6.1"
        assert 'version = "0.6.1"' in pyproject.read_text()

    def test_refactor_bumps_patch(self, pyproject: Path) -> None:
        result = bump_version(
            "refactor: clean up code", pyproject_path=pyproject, skip_git_check=True
        )
        assert result == "0.6.1"

    def test_test_bumps_patch(self, pyproject: Path) -> None:
        result = bump_version(
            "test: add test coverage", pyproject_path=pyproject, skip_git_check=True
        )
        assert result == "0.6.1"

    def test_docs_bumps_patch(self, pyproject: Path) -> None:
        result = bump_version("docs: update readme", pyproject_path=pyproject, skip_git_check=True)
        assert result == "0.6.1"

    def test_unknown_prefix_skips(self, pyproject: Path) -> None:
        original = pyproject.read_text()
        result = bump_version("chore: update deps", pyproject_path=pyproject, skip_git_check=True)
        assert result is None
        assert pyproject.read_text() == original

    def test_preserves_rest_of_file(self, pyproject: Path) -> None:
        bump_version("feat: widget", pyproject_path=pyproject, skip_git_check=True)
        text = pyproject.read_text()
        assert 'name = "patina"' in text
        assert 'description = "test"' in text

    def test_minor_resets_patch_to_zero(self, pyproject: Path) -> None:
        pyproject.write_text(TEMPLATE.format(version="0.7.3"))
        result = bump_version("feat: new feature", pyproject_path=pyproject, skip_git_check=True)
        assert result == "0.8.0"

    def test_sequential_bumps(self, pyproject: Path) -> None:
        bump_version("feat: first", pyproject_path=pyproject, skip_git_check=True)
        result = bump_version("fix: second", pyproject_path=pyproject, skip_git_check=True)
        assert result == "0.7.1"
