from __future__ import annotations

import re
from datetime import UTC, datetime

from patina.adapters._mcp_client import (
    McpClientError,
    McpSyncBridge,
    parse_json_content,
    strip_slack_content_tags,
)
from patina.models import ChatMessage, DmChannel


class SlackMcpAdapter:
    def __init__(self, bridge: McpSyncBridge) -> None:
        self._bridge = bridge
        self._user_cache: dict[str, str | None] = {}

    @property
    def platform(self) -> str:
        return "slack_mcp"

    def close(self) -> None:
        self._bridge.close()

    def _resolve_user_name(self, user_id: str) -> str | None:
        if not user_id or not re.match(r"^[UW][A-Z0-9]+$", user_id):
            return None
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        try:
            result = self._bridge.call_tool("get_user_profile", {"user_id": user_id})
            raw = parse_json_content(result)
            name = _extract_display_name(raw)
            self._user_cache[user_id] = name
            return name
        except Exception:
            self._user_cache[user_id] = None
            return None

    def _resolve_message_names(self, msgs: list[ChatMessage]) -> list[ChatMessage]:
        for msg in msgs:
            if not msg.user_name and msg.user_id:
                msg.user_name = self._resolve_user_name(msg.user_id)
        return msgs

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
        return self._resolve_message_names([m for m in msgs if m.timestamp >= since and _is_dm(m)])

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
        return self._resolve_message_names(_extract_search_messages(raw))

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
            return self._resolve_message_names(
                [_msg_from_raw(m) for m in raw if isinstance(m, dict)]
            )
        if isinstance(raw, dict):
            items = raw.get("messages", [])
            if isinstance(items, list):
                return self._resolve_message_names(
                    [_msg_from_raw(m) for m in items if isinstance(m, dict)]
                )
        return []

    def list_participant_channels(self, owner_user_id: str) -> list[tuple[str, str]]:
        channels = self.list_mpim_channels(owner_user_id)
        return [(ch["id"], ch["name"]) for ch in channels]

    def list_mpim_channels(self, owner_user_id: str) -> list[dict]:
        try:
            result = self._bridge.call_tool("conversations_list", {"types": "mpim"})
        except Exception:
            return []
        try:
            raw = parse_json_content(result)
        except McpClientError:
            return []
        if not isinstance(raw, dict):
            return []
        channels = raw.get("channels")
        if not isinstance(channels, list):
            return []
        # conversations_list with types=mpim already scopes to the authenticated
        # user's conversations, so no per-channel membership filter is needed.
        return [
            {"id": ch.get("id", ""), "name": ch.get("name", "")}
            for ch in channels
            if isinstance(ch, dict)
        ]

    list_group_dms = list_mpim_channels

    def list_dms(self, include_dormant: bool = False) -> list[DmChannel]:
        try:
            result = self._bridge.call_tool("list_dms", {"includeDormant": include_dormant})
        except Exception:
            return []
        try:
            raw = parse_json_content(result)
        except McpClientError:
            return []
        items = []
        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict):
            items = raw.get("channels", raw.get("dms", []))
            if not isinstance(items, list):
                items = []
        return [
            DmChannel(
                channel_id=ch.get("channel_id", ch.get("id", "")),
                is_group=ch.get("is_group", False),
                last_activity_ts=float(ch.get("last_activity_ts", ch.get("last_activity", 0.0))),
            )
            for ch in items
            if isinstance(ch, dict)
        ]

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
            return self._resolve_message_names(
                [_msg_from_raw(m) for m in raw if isinstance(m, dict)]
            )
        if isinstance(raw, dict):
            items = raw.get("replies", [])
            if isinstance(items, list):
                return self._resolve_message_names(
                    [_msg_from_raw(m) for m in items if isinstance(m, dict)]
                )
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
        user_name = (
            user_raw.get("real_name") or user_raw.get("display_name") or user_raw.get("name")
        )
    else:
        user_id = str(user_raw) if user_raw else ""
        user_name = raw.get("username") or raw.get("user_name")

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
        user_name=user_name,
        reactions=reactions,
    )
    msg._is_dm = is_dm  # type: ignore[attr-defined]
    return msg


def _extract_display_name(raw) -> str | None:
    if not isinstance(raw, dict):
        return None
    for key in ("real_name", "display_name", "name"):
        val = raw.get(key)
        if val and isinstance(val, str):
            return val
    user = raw.get("user")
    if isinstance(user, dict):
        for key in ("real_name", "display_name", "name"):
            val = user.get(key)
            if val and isinstance(val, str):
                return val
        profile = user.get("profile")
        if isinstance(profile, dict):
            for key in ("display_name", "real_name"):
                val = profile.get(key)
                if val and isinstance(val, str):
                    return val
    profile = raw.get("profile")
    if isinstance(profile, dict):
        for key in ("display_name", "real_name"):
            val = profile.get(key)
            if val and isinstance(val, str):
                return val
    return None


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
