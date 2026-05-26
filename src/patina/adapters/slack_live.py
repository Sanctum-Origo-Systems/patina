from __future__ import annotations

import json
import time
import urllib.request
from urllib.error import HTTPError

from patina.models import ChatMessage


class SlackAPIError(Exception):
    pass


class SlackLiveAdapter:
    def __init__(self, token: str) -> None:
        self._token = token

    @property
    def platform(self) -> str:
        return "slack"

    def _api(self, method: str, params: dict | None = None) -> dict:
        url = f"https://slack.com/api/{method}"
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {self._token}")

        retries = 3
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
                if not data.get("ok"):
                    error = data.get("error", "unknown")
                    if error == "invalid_auth" or error == "not_authed":
                        raise SlackAPIError(f"Authentication failed: {error}")
                    raise SlackAPIError(f"Slack API error: {error}")
                return data
            except HTTPError as e:
                if e.code == 429:
                    retry_after = int(e.headers.get("Retry-After", 5))
                    time.sleep(retry_after)
                    continue
                raise SlackAPIError(f"HTTP {e.code}: {e.reason}") from e
        raise SlackAPIError("Max retries exceeded")

    def _parse_messages(
        self, messages: list[dict], channel_id: str, channel_name: str = ""
    ) -> list[ChatMessage]:
        result = []
        for msg in messages:
            if msg.get("subtype") in ("bot_message", "channel_join", "channel_leave"):
                continue
            user_id = msg.get("user", "")
            text = msg.get("text", "")
            if not user_id or not text:
                continue

            ts_str = msg.get("ts", "0")
            thread_ts = msg.get("thread_ts")
            thread_id = thread_ts if thread_ts and thread_ts != ts_str else None

            result.append(
                ChatMessage(
                    user_id=user_id,
                    text=text,
                    timestamp=float(ts_str),
                    channel_id=channel_id,
                    thread_id=thread_id,
                    channel_name=channel_name,
                    reactions=msg.get("reactions", []),
                )
            )
        return result

    def list_dm_messages(self, since: float) -> list[ChatMessage]:
        convos = self._api("conversations.list", {"types": "im", "limit": "100"})
        all_msgs: list[ChatMessage] = []
        for ch in convos.get("channels", []):
            history = self._api(
                "conversations.history",
                {"channel": ch["id"], "oldest": str(since), "limit": "200"},
            )
            all_msgs.extend(self._parse_messages(history.get("messages", []), ch["id"]))
        return all_msgs

    def list_mentions(self, since: float) -> list[ChatMessage]:
        data = self._api(
            "search.messages",
            {"query": "to:me", "sort": "timestamp", "count": "100"},
        )
        messages = data.get("messages", {}).get("matches", [])
        result = []
        for msg in messages:
            ts = float(msg.get("ts", "0"))
            if ts < since:
                continue
            channel = msg.get("channel", {})
            result.append(
                ChatMessage(
                    user_id=msg.get("user", msg.get("username", "")),
                    text=msg.get("text", ""),
                    timestamp=ts,
                    channel_id=channel.get("id", ""),
                    channel_name=channel.get("name", ""),
                )
            )
        return result

    def list_channel_messages(self, channel_id: str, since: float) -> list[ChatMessage]:
        history = self._api(
            "conversations.history",
            {"channel": channel_id, "oldest": str(since), "limit": "200"},
        )
        return self._parse_messages(history.get("messages", []), channel_id)

    def get_thread(self, channel_id: str, thread_id: str) -> list[ChatMessage]:
        data = self._api(
            "conversations.replies",
            {"channel": channel_id, "ts": thread_id, "limit": "200"},
        )
        return self._parse_messages(data.get("messages", []), channel_id)
