from __future__ import annotations

import re
from datetime import UTC, datetime

from patina.adapters._mcp_client import (
    McpClientError,
    McpSyncBridge,
    parse_json_content,
    strip_slack_content_tags,
)
from patina.models import ChatMessage


class SlackMcpAdapter:
    def __init__(self, bridge: McpSyncBridge) -> None:
        self._bridge = bridge

    @property
    def platform(self) -> str:
        return "slack_mcp"

    def close(self) -> None:
        self._bridge.close()

    def list_dm_messages(self, since: float) -> list[ChatMessage]:
        try:
            result = self._bridge.call_tool("get_unreads")
        except Exception:
            return []
        try:
            raw = parse_json_content(result)
        except McpClientError:
            return []
        messages_raw: list[dict] = []
        if isinstance(raw, list):
            messages_raw = raw
        elif isinstance(raw, dict):
            for key in ("dms", "threads", "channels"):
                val = raw.get(key, [])
                if isinstance(val, list):
                    messages_raw.extend(val)
        msgs = [_msg_from_raw(m) for m in messages_raw if isinstance(m, dict)]
        return [m for m in msgs if m.timestamp >= since and _is_dm(m)]

    def list_mentions(self, since: float) -> list[ChatMessage]:
        since_dt = datetime.fromtimestamp(since, tz=UTC)
        query = f"to:me after:{since_dt.strftime('%Y-%m-%d')}"
        try:
            args = {
                "query": query,
                "count": 100,
                "scope": "messages",
                "sort": "timestamp",
                "sort_dir": "desc",
            }
            result = self._bridge.call_tool("search", args)
        except Exception:
            return []
        try:
            raw = parse_json_content(result)
        except McpClientError:
            return []
        return _extract_search_messages(raw)

    def list_channel_messages(self, channel_id: str, since: float) -> list[ChatMessage]:
        since_iso = datetime.fromtimestamp(since, tz=UTC).isoformat()
        try:
            result = self._bridge.call_tool(
                "get_messages", {"channel": channel_id, "since": since_iso}
            )
        except Exception:
            return []
        try:
            raw = parse_json_content(result)
        except McpClientError:
            return []
        if isinstance(raw, list):
            return [_msg_from_raw(m) for m in raw if isinstance(m, dict)]
        if isinstance(raw, dict):
            items = raw.get("messages", [])
            if isinstance(items, list):
                return [_msg_from_raw(m) for m in items if isinstance(m, dict)]
        return []

    def get_thread(self, channel_id: str, thread_id: str) -> list[ChatMessage]:
        try:
            result = self._bridge.call_tool(
                "get_thread", {"channel": channel_id, "threadTs": thread_id}
            )
        except Exception:
            return []
        try:
            raw = parse_json_content(result)
        except McpClientError:
            return []
        if isinstance(raw, list):
            return [_msg_from_raw(m) for m in raw if isinstance(m, dict)]
        if isinstance(raw, dict):
            items = raw.get("replies", [])
            if isinstance(items, list):
                return [_msg_from_raw(m) for m in items if isinstance(m, dict)]
        return []


def _is_dm(msg: ChatMessage) -> bool:
    return msg.channel_id.startswith("D") or getattr(msg, "_is_dm", False)


def _msg_from_raw(raw: dict) -> ChatMessage:
    channel_raw = raw.get("channel", "")
    if isinstance(channel_raw, dict):
        channel_id = channel_raw.get("id", "")
        channel_name = channel_raw.get("name", channel_id)
        is_dm = channel_raw.get("is_im", False)
    else:
        channel_id = channel_raw or raw.get("channel_id", "")
        channel_name = raw.get("channel_name", channel_id)
        is_dm = raw.get("is_dm", raw.get("isDm", False))

    user_raw = raw.get("user", raw.get("userId", ""))
    if isinstance(user_raw, dict):
        user_id = user_raw.get("id", user_raw.get("userId", ""))
    else:
        user_id = str(user_raw) if user_raw else ""

    ts = str(raw.get("ts", ""))
    text = raw.get("text", "")
    if not ts and "<slack-user-content" in text:
        ts_match = re.search(r'ts="([^"]+)"', text)
        if ts_match:
            ts = ts_match.group(1)

    if "<slack-user-content" in text:
        text = strip_slack_content_tags(text)

    reactions = raw.get("reactions", [])

    thread_ts = raw.get("thread_ts")
    thread_id = thread_ts if thread_ts and thread_ts != ts else None

    msg = ChatMessage(
        user_id=user_id,
        text=text,
        timestamp=float(ts) if ts else 0.0,
        channel_id=channel_id,
        thread_id=thread_id,
        channel_name=channel_name,
        reactions=reactions,
    )
    msg._is_dm = is_dm  # type: ignore[attr-defined]
    return msg


def _extract_search_messages(raw) -> list[ChatMessage]:
    if isinstance(raw, list):
        return [_msg_from_raw(m) for m in raw if isinstance(m, dict)]
    if isinstance(raw, dict):
        matches = raw.get("messages", raw)
        if isinstance(matches, dict):
            matches = matches.get("matches", matches.get("results", []))
        if isinstance(matches, list):
            return [_msg_from_raw(m) for m in matches if isinstance(m, dict)]
    return []
