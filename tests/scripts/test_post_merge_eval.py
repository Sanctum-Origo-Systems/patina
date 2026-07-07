"""Tests for scripts/post_merge_eval.sh."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _PROJECT_ROOT / "scripts" / "post_merge_eval.sh"

_DELTA_REPORT = json.dumps(
    {
        "deltas": [
            {
                "metric": "merge_rate",
                "baseline": 0.5,
                "latest": 0.7,
                "absolute_delta": 0.2,
                "percent_delta": 40.0,
            },
            {
                "metric": "time_to_implement",
                "baseline": 20.0,
                "latest": 15.0,
                "absolute_delta": -5.0,
                "percent_delta": -25.0,
            },
            {
                "metric": "tool_reliability",
                "baseline": 0.8,
                "latest": 0.9,
                "absolute_delta": 0.1,
                "percent_delta": 12.5,
            },
        ]
    },
    indent=2,
)


def _write_mock_scripts(
    eval_dir: Path,
    *,
    run_exits: int = 0,
    compare_exits: int = 0,
    compare_output: str = _DELTA_REPORT,
) -> None:
    if run_exits == 0:
        (eval_dir / "run.py").write_text("# no-op success\n")
    else:
        (eval_dir / "run.py").write_text(f"import sys; sys.exit({run_exits})\n")

    if compare_exits == 0:
        (eval_dir / "compare.py").write_text(f"print({compare_output!r})\n")
    else:
        (eval_dir / "compare.py").write_text(
            "import sys\n"
            "print('error: baseline file not found', file=sys.stderr)\n"
            f"sys.exit({compare_exits})\n"
        )


def _run_script(
    eval_dir: Path,
    changelog: Path,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "EVAL_DIR": str(eval_dir),
        "CHANGELOG_FILE": str(changelog),
        "PYTHON": sys.executable,
    }
    return subprocess.run(
        ["bash", str(_SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
    )


# --- success path ---


class TestSuccess:
    def test_exits_zero(self, tmp_path: Path) -> None:
        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        changelog = tmp_path / "CHANGELOG"
        _write_mock_scripts(eval_dir)

        result = _run_script(eval_dir, changelog)

        assert result.returncode == 0, result.stderr

    def test_appends_delta_to_changelog(self, tmp_path: Path) -> None:
        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        changelog = tmp_path / "CHANGELOG"
        _write_mock_scripts(eval_dir)

        _run_script(eval_dir, changelog)

        content = changelog.read_text()
        assert "## Eval Delta" in content
        assert "merge_rate" in content
        assert "absolute_delta" in content
        assert "percent_delta" in content

    def test_changelog_contains_timestamp(self, tmp_path: Path) -> None:
        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        changelog = tmp_path / "CHANGELOG"
        _write_mock_scripts(eval_dir)

        _run_script(eval_dir, changelog)

        content = changelog.read_text()
        assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", content)

    def test_changelog_contains_full_delta_output(self, tmp_path: Path) -> None:
        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        changelog = tmp_path / "CHANGELOG"
        _write_mock_scripts(eval_dir)

        _run_script(eval_dir, changelog)

        content = changelog.read_text()
        assert _DELTA_REPORT in content

    def test_two_runs_append_two_entries(self, tmp_path: Path) -> None:
        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        changelog = tmp_path / "CHANGELOG"
        _write_mock_scripts(eval_dir)

        _run_script(eval_dir, changelog)
        _run_script(eval_dir, changelog)

        content = changelog.read_text()
        assert content.count("## Eval Delta") == 2

    def test_preserves_existing_changelog_content(self, tmp_path: Path) -> None:
        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        changelog = tmp_path / "CHANGELOG"
        changelog.write_text("# Existing Content\n\nSome prior entries.\n")
        _write_mock_scripts(eval_dir)

        _run_script(eval_dir, changelog)

        content = changelog.read_text()
        assert content.startswith("# Existing Content\n")
        assert "## Eval Delta" in content

    def test_all_three_metrics_present(self, tmp_path: Path) -> None:
        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        changelog = tmp_path / "CHANGELOG"
        _write_mock_scripts(eval_dir)

        _run_script(eval_dir, changelog)

        content = changelog.read_text()
        assert "merge_rate" in content
        assert "time_to_implement" in content
        assert "tool_reliability" in content


# --- run.py failure ---


class TestRunFailure:
    def test_exits_nonzero(self, tmp_path: Path) -> None:
        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        changelog = tmp_path / "CHANGELOG"
        _write_mock_scripts(eval_dir, run_exits=1)

        result = _run_script(eval_dir, changelog)

        assert result.returncode != 0

    def test_changelog_not_created(self, tmp_path: Path) -> None:
        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        changelog = tmp_path / "CHANGELOG"
        _write_mock_scripts(eval_dir, run_exits=1)

        _run_script(eval_dir, changelog)

        assert not changelog.exists()

    def test_existing_changelog_unmodified(self, tmp_path: Path) -> None:
        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        changelog = tmp_path / "CHANGELOG"
        changelog.write_text("original\n")
        _write_mock_scripts(eval_dir, run_exits=1)

        _run_script(eval_dir, changelog)

        assert changelog.read_text() == "original\n"


# --- compare.py failure ---


class TestCompareFailure:
    def test_exits_nonzero(self, tmp_path: Path) -> None:
        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        changelog = tmp_path / "CHANGELOG"
        _write_mock_scripts(eval_dir, compare_exits=1)

        result = _run_script(eval_dir, changelog)

        assert result.returncode != 0

    def test_changelog_not_created(self, tmp_path: Path) -> None:
        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        changelog = tmp_path / "CHANGELOG"
        _write_mock_scripts(eval_dir, compare_exits=1)

        _run_script(eval_dir, changelog)

        assert not changelog.exists()

    def test_existing_changelog_unmodified(self, tmp_path: Path) -> None:
        eval_dir = tmp_path / "eval"
        eval_dir.mkdir()
        changelog = tmp_path / "CHANGELOG"
        changelog.write_text("original\n")
        _write_mock_scripts(eval_dir, compare_exits=1)

        _run_script(eval_dir, changelog)

        assert changelog.read_text() == "original\n"
