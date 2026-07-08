from __future__ import annotations

import pytest
from autoloop.config import AutoLoopConfig, load_config, verify_implementation

# --- Config loads correctly from a tmp_path autoloop.toml ---


def test_load_from_toml(autoloop_toml, monkeypatch):
    for var in (
        "PATINA_AIDLC_TRIAGE_MODEL",
        "PATINA_AIDLC_IMPL_MODEL",
        "PATINA_AIDLC_TIMEOUT",
        "PATINA_AIDLC_REVIEWER",
        "PATINA_AIDLC_TRIAGE_TIMEOUT",
        "PATINA_AIDLC_TEST_TIMEOUT",
        "PATINA_AIDLC_MAX_RETRIES",
        "PATINA_AIDLC_REPO",
    ):
        monkeypatch.delenv(var, raising=False)

    config = load_config(autoloop_toml)

    assert config.repo == "acme-corp/widget"
    assert config.triage_model == "haiku"
    assert config.impl_model == "opus"
    assert config.impl_timeout == 600
    assert config.triage_timeout == 45
    assert config.test_timeout == 60
    assert config.pr_reviewer == "review-bot"
    assert config.max_retries == 5
    assert config.tree_truncation == 2000
    assert config.diff_truncation == 6000
    assert config.error_truncation == 1500
    assert config.spec_truncation == 3000
    assert config.verify_command == "echo ok"
    assert config.triage_labels == ["ready", "blocked"]


def test_partial_toml_keeps_defaults(tmp_path, monkeypatch):
    for var in (
        "PATINA_AIDLC_TRIAGE_MODEL",
        "PATINA_AIDLC_IMPL_MODEL",
        "PATINA_AIDLC_TIMEOUT",
        "PATINA_AIDLC_REVIEWER",
    ):
        monkeypatch.delenv(var, raising=False)

    toml_path = tmp_path / "autoloop.toml"
    toml_path.write_text('triage_model = "haiku"\n')

    config = load_config(toml_path)

    assert config.triage_model == "haiku"
    assert config.impl_model == "claude-opus-4-6[1m]"
    assert config.impl_timeout == 900
    assert config.verify_command == "uv run pytest"
    assert len(config.triage_labels) == 6


# --- Env var override takes precedence ---


def test_env_var_overrides_toml(autoloop_toml, monkeypatch):
    monkeypatch.setenv("PATINA_AIDLC_TRIAGE_MODEL", "sonnet")
    monkeypatch.setenv("PATINA_AIDLC_TIMEOUT", "1200")
    monkeypatch.delenv("PATINA_AIDLC_IMPL_MODEL", raising=False)
    monkeypatch.delenv("PATINA_AIDLC_REVIEWER", raising=False)
    monkeypatch.delenv("PATINA_AIDLC_TRIAGE_TIMEOUT", raising=False)
    monkeypatch.delenv("PATINA_AIDLC_TEST_TIMEOUT", raising=False)
    monkeypatch.delenv("PATINA_AIDLC_MAX_RETRIES", raising=False)
    monkeypatch.delenv("PATINA_AIDLC_REPO", raising=False)

    config = load_config(autoloop_toml)

    assert config.triage_model == "sonnet"
    assert config.impl_timeout == 1200
    assert config.impl_model == "opus"


def test_env_var_overrides_all_mapped_fields(autoloop_toml, monkeypatch):
    monkeypatch.setenv("PATINA_AIDLC_TRIAGE_MODEL", "env-triage")
    monkeypatch.setenv("PATINA_AIDLC_IMPL_MODEL", "env-impl")
    monkeypatch.setenv("PATINA_AIDLC_TIMEOUT", "999")
    monkeypatch.setenv("PATINA_AIDLC_TRIAGE_TIMEOUT", "30")
    monkeypatch.setenv("PATINA_AIDLC_TEST_TIMEOUT", "15")
    monkeypatch.setenv("PATINA_AIDLC_REVIEWER", "env-reviewer")
    monkeypatch.setenv("PATINA_AIDLC_MAX_RETRIES", "7")
    monkeypatch.setenv("PATINA_AIDLC_REPO", "env-org/env-repo")

    config = load_config(autoloop_toml)

    assert config.triage_model == "env-triage"
    assert config.impl_model == "env-impl"
    assert config.impl_timeout == 999
    assert config.triage_timeout == 30
    assert config.test_timeout == 15
    assert config.pr_reviewer == "env-reviewer"
    assert config.max_retries == 7
    assert config.repo == "env-org/env-repo"


# --- Missing autoloop.toml raises a descriptive error ---


def test_missing_toml_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_config(tmp_path / "nonexistent.toml")


def test_missing_toml_error_includes_path(tmp_path):
    missing = tmp_path / "absent.toml"
    with pytest.raises(FileNotFoundError, match=str(missing)):
        load_config(missing)


# --- verify_implementation propagates exit codes ---


def test_verify_implementation_passing_command():
    config = AutoLoopConfig(verify_command="true")
    assert verify_implementation(config) == 0


def test_verify_implementation_failing_command():
    config = AutoLoopConfig(verify_command="false")
    result = verify_implementation(config)
    assert result != 0


def test_verify_implementation_specific_exit_code():
    config = AutoLoopConfig(verify_command="exit 42")
    assert verify_implementation(config) == 42


def test_verify_implementation_uses_config_verify_command():
    config = AutoLoopConfig(verify_command="echo hello")
    assert verify_implementation(config) == 0
