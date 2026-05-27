from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from patina.store import DEFAULT_HOME


@dataclass
class AgentConfig:
    provider: str = "anthropic"
    model: str | None = None
    soul_path: Path = field(default_factory=lambda: DEFAULT_HOME / "SOUL.md")
    mcp_server_command: str = "patina-mcp"
    mcp_server_args: list[str] = field(default_factory=list)
    session_ttl_seconds: int = 300
    repl_mode: bool = False
    permission_mode: str = "auto"
    max_turns: int = 50


def load_config(path: Path | None = None) -> AgentConfig:
    config_path = path or (DEFAULT_HOME / "agent.yaml")
    config = AgentConfig()

    if config_path.exists():
        import yaml

        with open(config_path) as f:
            data = yaml.safe_load(f) or {}

        if "provider" in data:
            config.provider = data["provider"]
        if "model" in data:
            config.model = data["model"]
        if "session_ttl_seconds" in data:
            config.session_ttl_seconds = data["session_ttl_seconds"]
        if "permission_mode" in data:
            config.permission_mode = data["permission_mode"]
        if "max_turns" in data:
            config.max_turns = data["max_turns"]

    if env_provider := os.environ.get("PATINA_PROVIDER"):
        config.provider = env_provider
    if env_model := os.environ.get("PATINA_MODEL"):
        config.model = env_model

    return config


def load_soul(config: AgentConfig) -> str:
    path = config.soul_path
    if not path.exists():
        raise FileNotFoundError(
            f"SOUL.md not found at {path}. Run 'patina init' or create it manually."
        )
    return path.read_text()
