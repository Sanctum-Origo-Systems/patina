from __future__ import annotations

import os
import shutil
from collections.abc import AsyncIterator
from typing import Any

from patina.agent.config import AgentConfig, load_soul
from patina.agent.session_cache import SessionCache


class AgentRuntime:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self._soul: str | None = None
        self.cache = SessionCache(ttl_seconds=config.session_ttl_seconds)
        self._repl_session_id: str | None = None

    @property
    def soul(self) -> str:
        if self._soul is None:
            try:
                self._soul = load_soul(self.config)
            except FileNotFoundError:
                self._soul = ""
        return self._soul

    def _build_options(self, session_id: str | None) -> dict[str, Any]:
        mcp_cmd = self.config.mcp_server_command
        mcp_path = shutil.which(mcp_cmd)

        mcp_servers = {}
        if mcp_path:
            mcp_servers["cognitive"] = {
                "command": mcp_path,
                "args": self.config.mcp_server_args,
            }

        opts: dict[str, Any] = {
            "system_prompt": self.soul,
            "mcp_servers": mcp_servers,
            "permission_mode": self.config.permission_mode,
            "allowed_tools": ["mcp__cognitive__*"],
            "max_turns": self.config.max_turns,
        }

        if session_id:
            opts["resume"] = session_id

        if self.config.model:
            opts["model"] = self.config.model

        env: dict[str, str] = {}
        if os.environ.get("CLAUDE_CODE_USE_BEDROCK"):
            env["CLAUDE_CODE_USE_BEDROCK"] = "1"
            env["AWS_REGION"] = os.environ.get("AWS_REGION", "us-west-2")
        if os.environ.get("AWS_PROFILE"):
            env["AWS_PROFILE"] = os.environ["AWS_PROFILE"]
        env["PATH"] = os.environ.get("PATH", "")
        if env:
            opts["env"] = env

        return opts

    async def query(
        self,
        prompt: str,
        channel: str = "repl-local",
        user_id: str = "default",
    ) -> AsyncIterator[Any]:
        session_key = f"{channel}-{user_id}"
        if self.config.repl_mode:
            session_id = self._repl_session_id
        else:
            session_id = self.cache.get(session_key)

        options = self._build_options(session_id)

        from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

        sdk_options = ClaudeAgentOptions(**options)

        async for message in query(prompt=prompt, options=sdk_options):
            if isinstance(message, ResultMessage):
                if not session_id and hasattr(message, "session_id"):
                    new_sid = message.session_id
                    if new_sid:
                        if self.config.repl_mode:
                            self._repl_session_id = new_sid
                        else:
                            self.cache.set(session_key, new_sid)
            yield message
