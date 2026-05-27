from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from patina.store import DEFAULT_HOME


@dataclass
class InboundMessage:
    channel: str
    user_id: str
    text: str
    timestamp: float
    platform: str


@dataclass
class OutboundMessage:
    channel: str
    text: str


class GatewayAdapter(ABC):
    def __init__(self, agent_url: str = "http://127.0.0.1:8321") -> None:
        self.agent_url = agent_url

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    async def send_to_agent(self, message: InboundMessage) -> str:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.agent_url}/message",
                json={
                    "channel": message.channel,
                    "user_id": message.user_id,
                    "prompt": message.text,
                },
            )
            response.raise_for_status()
            return response.json()["response"]


@dataclass
class TelegramConfig:
    enabled: bool = False
    token: str = ""
    allowed_users: list[int] = field(default_factory=list)


@dataclass
class GatewayConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    agent_url: str = "http://127.0.0.1:8321"


def _resolve_env(value: str) -> str:
    if not isinstance(value, str):
        return str(value)
    if value.startswith("${") and value.endswith("}"):
        var_name = value[2:-1]
        resolved = os.environ.get(var_name)
        if resolved is None:
            raise ValueError(
                f"Environment variable {var_name} not set. "
                f"Either set it or put the token directly in gateway.yaml."
            )
        return resolved
    return value


def load_gateway_config(path: Path | None = None) -> GatewayConfig:
    config_path = path or (DEFAULT_HOME / "gateway.yaml")
    config = GatewayConfig()

    if not config_path.exists():
        return config

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    if "agent_url" in data:
        config.agent_url = data["agent_url"]

    tg = data.get("adapters", {}).get("telegram", {})
    if tg:
        config.telegram.enabled = tg.get("enabled", False)
        if "token" in tg:
            config.telegram.token = _resolve_env(tg["token"])
        config.telegram.allowed_users = tg.get("allowed_users", [])

    return config
