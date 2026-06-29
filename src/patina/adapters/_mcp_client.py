from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class McpClientError(Exception):
    pass


class McpSyncBridge:
    def __init__(self, session: ClientSession, loop: asyncio.AbstractEventLoop, cleanup_fn) -> None:
        self._session = session
        self._loop = loop
        self._cleanup_fn = cleanup_fn

    def call_tool(self, name: str, arguments: dict | None = None, *, max_retries: int = 2) -> Any:
        return self._loop.run_until_complete(
            _call_tool(self._session, name, arguments, max_retries=max_retries)
        )

    def close(self) -> None:
        self._cleanup_fn()


def connect_mcp_sync(
    command: str, args: list[str] | None = None, env: dict[str, str] | None = None
) -> McpSyncBridge:
    loop = asyncio.new_event_loop()
    if env:
        os.environ.update(env)

    server_params = StdioServerParameters(command=command, args=args or [])
    ctx_stack: list = []

    async def setup() -> ClientSession:
        stdio_ctx = stdio_client(server_params)
        streams = await stdio_ctx.__aenter__()
        ctx_stack.append(stdio_ctx)
        session_ctx = ClientSession(streams[0], streams[1])
        session = await session_ctx.__aenter__()
        ctx_stack.append(session_ctx)
        await session.initialize()
        return session

    async def teardown() -> None:
        for ctx in reversed(ctx_stack):
            with contextlib.suppress(BaseException):
                await ctx.__aexit__(None, None, None)

    try:
        session = loop.run_until_complete(setup())
    except Exception as exc:
        loop.run_until_complete(teardown())
        loop.close()
        raise McpClientError(f"Failed to connect MCP server '{command}': {exc}") from exc

    def cleanup() -> None:
        loop.run_until_complete(teardown())
        loop.close()

    return McpSyncBridge(session, loop, cleanup)


async def _call_tool(
    session: ClientSession, name: str, arguments: dict | None = None, *, max_retries: int = 2
) -> Any:
    for attempt in range(max_retries + 1):
        result = await session.call_tool(name, arguments or {})
        if not result.isError:
            return result
        error_text = " ".join(c.text for c in result.content if hasattr(c, "text"))
        if "Rate limit exceeded" not in error_text:
            return result
        if attempt == max_retries:
            return result
        retry_match = re.search(r"Retry after (\d+)s", error_text)
        wait_seconds = int(retry_match.group(1)) + 1 if retry_match else 45
        await asyncio.sleep(wait_seconds)
    return result  # pragma: no cover


def parse_text_content(result: Any) -> str:
    if result.isError:
        texts = [c.text for c in result.content if hasattr(c, "text")]
        raise McpClientError(f"MCP error: {' '.join(texts)}")
    texts = [c.text for c in result.content if hasattr(c, "text")]
    return "\n".join(texts)


def parse_json_content(result: Any) -> Any:
    text = parse_text_content(result)
    if not text.strip():
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    if "\n---\n" in text:
        json_part = text.split("\n---\n")[-1].strip()
        try:
            return json.loads(json_part)
        except json.JSONDecodeError:
            pass
    last_json_start = max(text.rfind("\n{"), text.rfind("\n["))
    if last_json_start >= 0:
        try:
            return json.loads(text[last_json_start:])
        except json.JSONDecodeError:
            pass
    return []


def parse_outlook_content(result: Any) -> Any:
    if result.isError:
        texts = [c.text for c in result.content if hasattr(c, "text")]
        raise McpClientError(f"Outlook MCP error: {' '.join(texts)}")
    texts = [c.text for c in result.content if hasattr(c, "text")]
    text = "\n".join(texts)
    if not text.strip():
        return []
    if "untrusted_content_" in text:
        text = re.sub(r"</?untrusted_content_[^>]*>", "", text).strip()
    if "IMPORTANT:" in text:
        text = text[: text.rfind("IMPORTANT:")].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for start_char in ("[", "{"):
        idx = text.find(start_char)
        if idx >= 0:
            try:
                return json.loads(text[idx:])
            except json.JSONDecodeError:
                pass
    return []


def strip_slack_content_tags(text: str) -> str:
    text = re.sub(r"<slack-user-content[^>]*>\n?", "", text)
    text = re.sub(r"\n?</slack-user-content>", "", text)
    return text.strip()
