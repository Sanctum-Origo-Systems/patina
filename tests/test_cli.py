from __future__ import annotations

import json
import zipfile

from typer.testing import CliRunner

from patina.cli import app

runner = CliRunner()


def test_init_creates_database(tmp_path):
    result = runner.invoke(app, ["init", "--home", str(tmp_path)])
    assert result.exit_code == 0
    assert "Initialized" in result.output
    assert (tmp_path / "store.db").exists()


def test_ingest_requires_from_export():
    result = runner.invoke(app, ["ingest"])
    assert result.exit_code != 0


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
