from __future__ import annotations

from patina.agent.config import AgentConfig
from patina.agent.runtime import AgentRuntime


def test_runtime_initializes(tmp_path):
    config = AgentConfig(soul_path=tmp_path / "SOUL.md")
    (tmp_path / "SOUL.md").write_text("Be helpful.")
    runtime = AgentRuntime(config)
    assert runtime.soul == "Be helpful."


def test_runtime_soul_fallback_empty(tmp_path):
    config = AgentConfig(soul_path=tmp_path / "nonexistent.md")
    runtime = AgentRuntime(config)
    assert runtime.soul == ""


def test_build_options_includes_soul(tmp_path):
    config = AgentConfig(soul_path=tmp_path / "SOUL.md")
    (tmp_path / "SOUL.md").write_text("Be direct.")
    runtime = AgentRuntime(config)
    opts = runtime._build_options(None)
    assert opts["system_prompt"] == "Be direct."


def test_build_options_includes_max_turns(tmp_path):
    config = AgentConfig(soul_path=tmp_path / "SOUL.md", max_turns=25)
    (tmp_path / "SOUL.md").write_text("")
    runtime = AgentRuntime(config)
    opts = runtime._build_options(None)
    assert opts["max_turns"] == 25


def test_build_options_with_resume(tmp_path):
    config = AgentConfig(soul_path=tmp_path / "SOUL.md")
    (tmp_path / "SOUL.md").write_text("")
    runtime = AgentRuntime(config)
    opts = runtime._build_options("session-123")
    assert opts["resume"] == "session-123"


def test_build_options_without_resume(tmp_path):
    config = AgentConfig(soul_path=tmp_path / "SOUL.md")
    (tmp_path / "SOUL.md").write_text("")
    runtime = AgentRuntime(config)
    opts = runtime._build_options(None)
    assert "resume" not in opts


def test_build_options_includes_model(tmp_path):
    config = AgentConfig(soul_path=tmp_path / "SOUL.md", model="claude-sonnet-4-6")
    (tmp_path / "SOUL.md").write_text("")
    runtime = AgentRuntime(config)
    opts = runtime._build_options(None)
    assert opts["model"] == "claude-sonnet-4-6"


def test_repl_mode_flag(tmp_path):
    config = AgentConfig(soul_path=tmp_path / "SOUL.md", repl_mode=True)
    (tmp_path / "SOUL.md").write_text("")
    runtime = AgentRuntime(config)
    assert runtime.config.repl_mode is True
    assert runtime._repl_session_id is None


def test_build_options_no_bedrock_env(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    config = AgentConfig(soul_path=tmp_path / "SOUL.md")
    (tmp_path / "SOUL.md").write_text("")
    runtime = AgentRuntime(config)
    opts = runtime._build_options(None)
    env = opts.get("env", {})
    assert "CLAUDE_CODE_USE_BEDROCK" not in env
    assert "AWS_REGION" not in env
    assert "AWS_PROFILE" not in env


def test_build_options_bedrock_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    config = AgentConfig(soul_path=tmp_path / "SOUL.md")
    (tmp_path / "SOUL.md").write_text("")
    runtime = AgentRuntime(config)
    opts = runtime._build_options(None)
    assert opts["env"]["CLAUDE_CODE_USE_BEDROCK"] == "1"
    assert opts["env"]["AWS_REGION"] == "eu-west-1"


def test_build_options_bedrock_default_region(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.delenv("AWS_REGION", raising=False)
    config = AgentConfig(soul_path=tmp_path / "SOUL.md")
    (tmp_path / "SOUL.md").write_text("")
    runtime = AgentRuntime(config)
    opts = runtime._build_options(None)
    assert opts["env"]["AWS_REGION"] == "us-west-2"


def test_build_options_aws_profile(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK", raising=False)
    monkeypatch.setenv("AWS_PROFILE", "my-profile")
    config = AgentConfig(soul_path=tmp_path / "SOUL.md")
    (tmp_path / "SOUL.md").write_text("")
    runtime = AgentRuntime(config)
    opts = runtime._build_options(None)
    assert opts["env"]["AWS_PROFILE"] == "my-profile"


def test_build_options_env_always_has_path(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    config = AgentConfig(soul_path=tmp_path / "SOUL.md")
    (tmp_path / "SOUL.md").write_text("")
    runtime = AgentRuntime(config)
    opts = runtime._build_options(None)
    assert "PATH" in opts["env"]


def test_build_options_cli_path_when_found(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "shutil.which",
        lambda cmd: "/usr/local/bin/claude" if cmd == "claude" else None,
    )
    config = AgentConfig(soul_path=tmp_path / "SOUL.md")
    (tmp_path / "SOUL.md").write_text("")
    runtime = AgentRuntime(config)
    opts = runtime._build_options(None)
    assert opts["cli_path"] == "/usr/local/bin/claude"


def test_build_options_no_cli_path_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    config = AgentConfig(soul_path=tmp_path / "SOUL.md")
    (tmp_path / "SOUL.md").write_text("")
    runtime = AgentRuntime(config)
    opts = runtime._build_options(None)
    assert "cli_path" not in opts
