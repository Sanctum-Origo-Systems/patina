from __future__ import annotations

from autoloop.config import AutoLoopConfig, load_config


def test_defaults_when_empty_toml_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOLOOP_TRIAGE_MODEL", raising=False)
    monkeypatch.delenv("AUTOLOOP_IMPL_MODEL", raising=False)
    monkeypatch.delenv("AUTOLOOP_TIMEOUT", raising=False)
    monkeypatch.delenv("AUTOLOOP_REVIEWER", raising=False)

    toml_path = tmp_path / "autoloop.toml"
    toml_path.write_text("")
    config = load_config(toml_path)

    assert config.repo == "Sanctum-Origo-Systems/patina"
    assert config.triage_model == "sonnet"
    assert config.impl_model == "claude-opus-4-6[1m]"
    assert config.impl_timeout == 900
    assert config.triage_timeout == 90
    assert config.test_timeout == 120
    assert config.pr_reviewer == "andywidjaja"
    assert config.max_retries == 3
    assert config.tree_truncation == 3000
    assert config.diff_truncation == 8000
    assert config.error_truncation == 2000
    assert config.spec_truncation == 4000
    assert "ready" in config.triage_labels
    assert "rejected" in config.triage_labels
    assert len(config.triage_labels) == 6


def test_load_from_toml(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOLOOP_TRIAGE_MODEL", raising=False)
    monkeypatch.delenv("AUTOLOOP_IMPL_MODEL", raising=False)
    monkeypatch.delenv("AUTOLOOP_TIMEOUT", raising=False)
    monkeypatch.delenv("AUTOLOOP_REVIEWER", raising=False)

    toml_path = tmp_path / "autoloop.toml"
    toml_path.write_text(
        'triage_model = "haiku"\n'
        'impl_model = "opus"\n'
        "impl_timeout = 600\n"
        'pr_reviewer = "reviewer-bot"\n'
        "max_retries = 5\n"
    )
    config = load_config(toml_path)

    assert config.triage_model == "haiku"
    assert config.impl_model == "opus"
    assert config.impl_timeout == 600
    assert config.pr_reviewer == "reviewer-bot"
    assert config.max_retries == 5
    # Unset fields keep defaults
    assert config.triage_timeout == 90
    assert config.tree_truncation == 3000


def test_env_overrides_toml(tmp_path, monkeypatch):
    toml_path = tmp_path / "autoloop.toml"
    toml_path.write_text(
        'triage_model = "haiku"\n'
        'impl_model = "opus"\n'
        "impl_timeout = 600\n"
        'pr_reviewer = "reviewer-bot"\n'
    )

    monkeypatch.setenv("AUTOLOOP_TRIAGE_MODEL", "sonnet")
    monkeypatch.setenv("AUTOLOOP_IMPL_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("AUTOLOOP_TIMEOUT", "1200")
    monkeypatch.setenv("AUTOLOOP_REVIEWER", "env-reviewer")

    config = load_config(toml_path)

    assert config.triage_model == "sonnet"
    assert config.impl_model == "claude-sonnet-4-6"
    assert config.impl_timeout == 1200
    assert config.pr_reviewer == "env-reviewer"


def test_env_overrides_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLOOP_TRIAGE_MODEL", "opus")
    monkeypatch.setenv("AUTOLOOP_TIMEOUT", "1800")
    monkeypatch.setenv("AUTOLOOP_REVIEWER", "ci-bot")

    toml_path = tmp_path / "autoloop.toml"
    toml_path.write_text("")
    config = load_config(toml_path)

    assert config.triage_model == "opus"
    assert config.impl_timeout == 1800
    assert config.pr_reviewer == "ci-bot"
    assert config.impl_model == "claude-opus-4-6[1m]"
    assert config.triage_timeout == 90


def test_triage_labels_from_toml(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOLOOP_TRIAGE_MODEL", raising=False)

    toml_path = tmp_path / "autoloop.toml"
    toml_path.write_text('triage_labels = ["ready", "blocked"]\n')

    config = load_config(toml_path)

    assert config.triage_labels == ["ready", "blocked"]


def test_partial_toml_keeps_other_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOLOOP_TRIAGE_MODEL", raising=False)
    monkeypatch.delenv("AUTOLOOP_IMPL_MODEL", raising=False)
    monkeypatch.delenv("AUTOLOOP_TIMEOUT", raising=False)
    monkeypatch.delenv("AUTOLOOP_REVIEWER", raising=False)

    toml_path = tmp_path / "autoloop.toml"
    toml_path.write_text("tree_truncation = 5000\n")

    config = load_config(toml_path)

    assert config.tree_truncation == 5000
    assert config.triage_model == "sonnet"
    assert config.impl_timeout == 900


def test_additional_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLOOP_TRIAGE_TIMEOUT", "45")
    monkeypatch.setenv("AUTOLOOP_TEST_TIMEOUT", "60")
    monkeypatch.setenv("AUTOLOOP_MAX_RETRIES", "10")
    monkeypatch.setenv("AUTOLOOP_REPO", "other-org/other-repo")

    toml_path = tmp_path / "autoloop.toml"
    toml_path.write_text("")
    config = load_config(toml_path)

    assert config.triage_timeout == 45
    assert config.test_timeout == 60
    assert config.max_retries == 10
    assert config.repo == "other-org/other-repo"


def test_default_config_path_resolves():
    from autoloop.config import DEFAULT_CONFIG_PATH

    assert DEFAULT_CONFIG_PATH.name == "autoloop.toml"


def test_autoloop_is_importable():
    import autoloop

    assert hasattr(autoloop, "__file__")


def test_config_dataclass_is_independent():
    a = AutoLoopConfig()
    b = AutoLoopConfig()
    a.triage_labels.append("custom")
    assert "custom" not in b.triage_labels
