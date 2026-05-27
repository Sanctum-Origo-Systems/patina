from __future__ import annotations

from patina.agent.config import AgentConfig, load_config, load_soul


def test_load_config_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("patina.agent.config.DEFAULT_HOME", tmp_path)
    config = load_config()
    assert config.provider == "anthropic"
    assert config.session_ttl_seconds == 300
    assert config.repl_mode is False


def test_load_config_from_yaml(tmp_path, monkeypatch):
    monkeypatch.setattr("patina.agent.config.DEFAULT_HOME", tmp_path)
    import yaml

    config_path = tmp_path / "agent.yaml"
    config_path.write_text(yaml.dump({"provider": "openai", "model": "gpt-4o"}))

    config = load_config(config_path)
    assert config.provider == "openai"
    assert config.model == "gpt-4o"


def test_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setattr("patina.agent.config.DEFAULT_HOME", tmp_path)
    monkeypatch.setenv("PATINA_PROVIDER", "google")
    monkeypatch.setenv("PATINA_MODEL", "gemini-pro")

    config = load_config()
    assert config.provider == "google"
    assert config.model == "gemini-pro"


def test_load_soul_reads_file(tmp_path):
    soul_path = tmp_path / "SOUL.md"
    soul_path.write_text("Be direct and concise.")
    config = AgentConfig(soul_path=soul_path)
    assert load_soul(config) == "Be direct and concise."


def test_load_soul_missing_raises(tmp_path):
    config = AgentConfig(soul_path=tmp_path / "nonexistent.md")
    try:
        load_soul(config)
        assert False, "Should have raised"
    except FileNotFoundError as e:
        assert "SOUL.md" in str(e)
