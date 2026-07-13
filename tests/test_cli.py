from __future__ import annotations

import json
import zipfile

from typer.testing import CliRunner

from patina.cli import _bootstrap_home, app

runner = CliRunner()


def test_bootstrap_home_soul_context_persistence(tmp_path):
    _bootstrap_home(tmp_path)
    soul_text = (tmp_path / "SOUL.md").read_text()
    assert "## Context Persistence" in soul_text
    assert "## Journal Search" in soul_text


def test_bootstrap_home_soul_references_journal_tools(tmp_path):
    _bootstrap_home(tmp_path)
    soul_text = (tmp_path / "SOUL.md").read_text()
    persistence, _, search = soul_text.partition("## Journal Search")
    assert "journal_write" in persistence.partition("## Context Persistence")[2]
    assert "journal_search" in search


def test_bootstrap_home_does_not_overwrite_existing_soul(tmp_path):
    soul = tmp_path / "SOUL.md"
    soul.write_text("custom soul content")
    _bootstrap_home(tmp_path)
    assert soul.read_text() == "custom soul content"


def test_init_creates_database(tmp_path):
    result = runner.invoke(app, ["init", "--home", str(tmp_path)], input="\n")
    assert result.exit_code == 0
    assert "Initialized" in result.output
    assert (tmp_path / "store.db").exists()


def test_ingest_no_adapters_shows_message(tmp_path):
    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "No adapters configured" in result.output


def test_ingest_with_valid_zip(tmp_path):
    zip_path = tmp_path / "export.zip"
    users = [{"id": "U001", "real_name": "Alice", "name": "alice"}]
    channels = [{"id": "C001", "name": "general"}]
    messages = [{"user": "U001", "text": "Hello!", "ts": "1700000100.000"}]

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("users.json", json.dumps(users))
        zf.writestr("channels.json", json.dumps(channels))
        zf.writestr("general/2023-11-15.json", json.dumps(messages))

    home = tmp_path / "patina_home"
    result = runner.invoke(app, ["ingest", "--from-export", str(zip_path), "--home", str(home)])
    assert result.exit_code == 0
    assert "Done" in result.output


def test_ingest_lookback_days_default(tmp_path, monkeypatch):
    called_with = {}

    def fake_ingest_all(*, home=None, lookback_days=3):
        called_with["lookback_days"] = lookback_days
        return {
            "messages_inserted": 0,
            "messages_skipped": 0,
            "entities_created": 0,
            "total_observations": 0,
            "total_entities": 0,
            "adapters_run": 1,
        }

    monkeypatch.setattr("patina.ingest.ingest_all", fake_ingest_all)

    result = runner.invoke(app, ["ingest", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert called_with["lookback_days"] == 3


def test_ingest_lookback_days_custom(tmp_path, monkeypatch):
    called_with = {}

    def fake_ingest_all(*, home=None, lookback_days=3):
        called_with["lookback_days"] = lookback_days
        return {
            "messages_inserted": 5,
            "messages_skipped": 2,
            "entities_created": 3,
            "total_observations": 10,
            "total_entities": 5,
            "adapters_run": 1,
        }

    monkeypatch.setattr("patina.ingest.ingest_all", fake_ingest_all)

    result = runner.invoke(app, ["ingest", "--lookback-days", "30", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert called_with["lookback_days"] == 30
    assert "Done" in result.output


def test_status_uninitialized(tmp_path):
    home = tmp_path / "empty_home"
    home.mkdir()
    result = runner.invoke(app, ["status", "--home", str(home)])
    assert result.exit_code == 1


def test_status_after_init(tmp_path):
    runner.invoke(app, ["init", "--home", str(tmp_path)])
    result = runner.invoke(app, ["status", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "Observations" in result.output
    assert "Entities" in result.output
