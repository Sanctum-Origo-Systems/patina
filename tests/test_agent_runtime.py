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
