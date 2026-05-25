from __future__ import annotations

import json
import zipfile
from pathlib import Path, PurePosixPath

from patina.models import ChatMessage

_SKIP_SUBTYPES = {"bot_message", "channel_join", "channel_leave"}


def parse_slack_export(
    zip_path: Path,
) -> tuple[list[ChatMessage], dict[str, str], dict[str, str]]:
    with zipfile.ZipFile(zip_path) as zf:
        users = _load_users(zf)
        channels = _load_channels(zf)
        channel_name_to_id = {ch_name: ch_id for ch_id, ch_name in channels.items()}
        messages = _load_messages(zf, users, channel_name_to_id)

    messages.sort(key=lambda m: m.timestamp)
    return messages, users, channels


def _load_users(zf: zipfile.ZipFile) -> dict[str, str]:
    for name in zf.namelist():
        if PurePosixPath(name).name == "users.json":
            data = json.loads(zf.read(name))
            return {u["id"]: u.get("real_name") or u.get("name", u["id"]) for u in data}
    return {}


def _load_channels(zf: zipfile.ZipFile) -> dict[str, str]:
    for name in zf.namelist():
        if PurePosixPath(name).name == "channels.json":
            data = json.loads(zf.read(name))
            return {c["id"]: c["name"] for c in data}
    return {}


def _load_messages(
    zf: zipfile.ZipFile,
    users: dict[str, str],
    channel_name_to_id: dict[str, str],
) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for name in zf.namelist():
        path = PurePosixPath(name)
        if path.suffix != ".json" or path.name in ("users.json", "channels.json"):
            continue

        channel_name = path.parent.name
        if not channel_name:
            continue

        channel_id = channel_name_to_id.get(channel_name, channel_name)

        try:
            data = json.loads(zf.read(name))
        except (json.JSONDecodeError, KeyError):
            continue

        if not isinstance(data, list):
            continue

        for msg in data:
            if not isinstance(msg, dict):
                continue
            if msg.get("subtype") in _SKIP_SUBTYPES:
                continue

            user_id = msg.get("user", "")
            text = msg.get("text", "")
            if not user_id or not text:
                continue

            ts_str = msg.get("ts", "0")
            ts = float(ts_str)

            thread_ts = msg.get("thread_ts")
            thread_id = None
            if thread_ts and thread_ts != ts_str:
                thread_id = thread_ts

            reactions = msg.get("reactions", [])

            messages.append(
                ChatMessage(
                    user_id=user_id,
                    text=text,
                    timestamp=ts,
                    channel_id=channel_id,
                    thread_id=thread_id,
                    user_name=users.get(user_id),
                    channel_name=channel_name,
                    reactions=reactions,
                )
            )

    return messages
