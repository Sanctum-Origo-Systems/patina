from __future__ import annotations

from patina.gateway.base import GatewayAdapter


class SlackAdapter(GatewayAdapter):
    """Slack gateway adapter. Stub for v0.3.0, implement in v0.3.1."""

    async def start(self) -> None:
        raise NotImplementedError("Slack adapter not yet implemented")

    async def stop(self) -> None:
        pass
