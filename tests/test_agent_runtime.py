from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from patina.agent.config import AgentConfig
from patina.agent.runtime import AgentRuntime, _build_tool_guide


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
    assert opts["system_prompt"].startswith("Be direct.")
    assert "Operational Instructions" in opts["system_prompt"]


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


def test_build_options_cwd_is_home(tmp_path):
    config = AgentConfig(soul_path=tmp_path / "SOUL.md")
    (tmp_path / "SOUL.md").write_text("")
    runtime = AgentRuntime(config)
    opts = runtime._build_options(None)
    assert opts["cwd"] == str(Path.home())


def test_profile_included_in_system_prompt(tmp_path):
    config = AgentConfig(
        soul_path=tmp_path / "SOUL.md",
        profile_path=tmp_path / "PROFILE.md",
    )
    (tmp_path / "SOUL.md").write_text("Be direct.")
    (tmp_path / "PROFILE.md").write_text("User prefers bullet points.")
    runtime = AgentRuntime(config)
    opts = runtime._build_options(None)
    assert "User prefers bullet points." in opts["system_prompt"]


def test_profile_absent_starts_without_error(tmp_path):
    config = AgentConfig(
        soul_path=tmp_path / "SOUL.md",
        profile_path=tmp_path / "PROFILE.md",
    )
    (tmp_path / "SOUL.md").write_text("Be direct.")
    runtime = AgentRuntime(config)
    opts = runtime._build_options(None)
    assert "system_prompt" in opts


def test_profile_absent_omits_profile_content(tmp_path):
    config = AgentConfig(
        soul_path=tmp_path / "SOUL.md",
        profile_path=tmp_path / "PROFILE.md",
    )
    (tmp_path / "SOUL.md").write_text("Be direct.")
    runtime = AgentRuntime(config)
    assert runtime.profile == ""


def test_profile_appears_after_soul_in_system_prompt(tmp_path):
    config = AgentConfig(
        soul_path=tmp_path / "SOUL.md",
        profile_path=tmp_path / "PROFILE.md",
    )
    (tmp_path / "SOUL.md").write_text("SOUL_CONTENT")
    (tmp_path / "PROFILE.md").write_text("PROFILE_CONTENT")
    runtime = AgentRuntime(config)
    opts = runtime._build_options(None)
    prompt = opts["system_prompt"]
    assert prompt.index("SOUL_CONTENT") < prompt.index("PROFILE_CONTENT")


class TestBuildToolGuide:
    def test_returns_non_empty(self):
        guide = _build_tool_guide()
        assert len(guide) > 0

    def test_contains_header(self):
        guide = _build_tool_guide()
        assert "## MCP Tools (use proactively)" in guide

    def test_contains_known_tools(self):
        guide = _build_tool_guide()
        for name in [
            "catch_up",
            "relationships",
            "hidden_allies",
            "beliefs",
            "journal_write",
            "profile_read",
            "autonomy_status",
        ]:
            assert f"**{name}**" in guide, f"tool '{name}' missing"

    def test_contains_descriptions(self):
        guide = _build_tool_guide()
        assert "Summarize recent unread" in guide
        assert "high-trust, low-noise" in guide
        assert "communication style" in guide

    def test_all_tools_have_descriptions(self):
        guide = _build_tool_guide()
        for line in guide.split("\n"):
            if line.startswith("- **"):
                assert "— " in line
                desc = line.split("— ", 1)[1]
                assert len(desc) > 5, f"empty description: {line}"

    def test_graceful_fallback_on_import_error(self):
        with patch(
            "patina.mcp.server.mcp",
            new_callable=lambda: type(
                "BadMcp",
                (),
                {"_tool_manager": property(lambda s: (_ for _ in ()).throw(ImportError))},
            ),
        ):
            guide = _build_tool_guide()
            assert guide == ""

    def test_system_prompt_includes_tool_guide(self, tmp_path):
        config = AgentConfig(soul_path=tmp_path / "SOUL.md")
        (tmp_path / "SOUL.md").write_text("Be helpful.")
        runtime = AgentRuntime(config)
        opts = runtime._build_options(None)
        prompt = opts["system_prompt"]
        assert "MCP Tools (use proactively)" in prompt
        assert "catch_up" in prompt
        assert "hidden_allies" in prompt

    def test_tool_guide_after_operational_instructions(self, tmp_path):
        config = AgentConfig(soul_path=tmp_path / "SOUL.md")
        (tmp_path / "SOUL.md").write_text("")
        runtime = AgentRuntime(config)
        opts = runtime._build_options(None)
        prompt = opts["system_prompt"]
        ops_idx = prompt.index("Operational Instructions")
        tools_idx = prompt.index("MCP Tools (use proactively)")
        assert tools_idx > ops_idx
