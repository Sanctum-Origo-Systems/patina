"""Tests for update_changelog.py CLI argument parsing and exit behavior."""

from __future__ import annotations

import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

from eval.cognitive.update_changelog import main

SCRIPT = str(
    Path(__file__).resolve().parent.parent.parent / "eval" / "cognitive" / "update_changelog.py"
)


# --- CLI error cases (subprocess, validating non-zero exit) ---


def test_no_args_exits_nonzero():
    result = subprocess.run(
        [sys.executable, SCRIPT],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_missing_number_exits_nonzero():
    result = subprocess.run(
        [sys.executable, SCRIPT, "--title", "Fix bug", "--cost", "1.23"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_missing_title_exits_nonzero():
    result = subprocess.run(
        [sys.executable, SCRIPT, "--number", "42", "--cost", "1.23"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_missing_cost_exits_nonzero():
    result = subprocess.run(
        [sys.executable, SCRIPT, "--number", "42", "--title", "Fix bug"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_invalid_number_type_exits_nonzero():
    result = subprocess.run(
        [sys.executable, SCRIPT, "--number", "abc", "--title", "Fix", "--cost", "1.23"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_invalid_cost_type_exits_nonzero():
    result = subprocess.run(
        [sys.executable, SCRIPT, "--number", "42", "--title", "Fix", "--cost", "not-a-number"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_missing_args_shows_error_on_stderr():
    result = subprocess.run(
        [sys.executable, SCRIPT],
        capture_output=True,
        text=True,
    )
    assert "required" in result.stderr.lower() or "usage" in result.stderr.lower()


# --- main() function tests (in-process, with path overrides) ---


def test_main_appends_entry(tmp_path, monkeypatch):
    changelog = tmp_path / "CHANGELOG.md"
    monkeypatch.setattr("eval.cognitive.update_changelog.CHANGELOG_PATH", changelog)
    monkeypatch.setattr("eval.cognitive.update_changelog.ARCHIVE_PATH", tmp_path / "archive.md")

    main(["--number", "42", "--title", "Fix login bug", "--cost", "1.23"])

    text = changelog.read_text()
    assert "#42: Fix login bug ($1.23)" in text


def test_main_trims_old_entries(tmp_path, monkeypatch):
    changelog = tmp_path / "CHANGELOG.md"
    archive = tmp_path / "archive.md"
    monkeypatch.setattr("eval.cognitive.update_changelog.CHANGELOG_PATH", changelog)
    monkeypatch.setattr("eval.cognitive.update_changelog.ARCHIVE_PATH", archive)

    old_date = (date.today() - timedelta(days=30)).isoformat()
    changelog.write_text(f"- #1: Old entry ($0.50) [{old_date}]\n")

    main(["--number", "42", "--title", "New entry", "--cost", "0.75"])

    cl_text = changelog.read_text()
    assert "#42: New entry" in cl_text
    assert "#1: Old entry" not in cl_text

    ar_text = archive.read_text()
    assert "#1: Old entry" in ar_text


def test_main_preserves_recent_entries(tmp_path, monkeypatch):
    changelog = tmp_path / "CHANGELOG.md"
    archive = tmp_path / "archive.md"
    monkeypatch.setattr("eval.cognitive.update_changelog.CHANGELOG_PATH", changelog)
    monkeypatch.setattr("eval.cognitive.update_changelog.ARCHIVE_PATH", archive)

    recent_date = (date.today() - timedelta(days=3)).isoformat()
    changelog.write_text(f"- #1: Recent entry ($0.50) [{recent_date}]\n")

    main(["--number", "42", "--title", "Another entry", "--cost", "0.75"])

    cl_text = changelog.read_text()
    assert "#1: Recent entry" in cl_text
    assert "#42: Another entry" in cl_text
    assert not archive.exists()
