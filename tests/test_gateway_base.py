from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from patina.gateway.base import (
    InboundMessage,
    load_gateway_config,
)


class ConcreteAdapter:
    """Minimal concrete adapter for testing base class."""

    def __init__(self, agent_url="http://127.0.0.1:8321"):
        self.agent_url = agent_url

    async def start(self):
        pass

    async def stop(self):
        pass


def test_load_gateway_config_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr("patina.gateway.base.DEFAULT_HOME", tmp_path)
    config = load_gateway_config()
    assert config.telegram.enabled is False
    assert config.agent_url == "http://127.0.0.1:8321"


def test_load_gateway_config_from_yaml(tmp_path, monkeypatch):
    monkeypatch.setattr("patina.gateway.base.DEFAULT_HOME", tmp_path)
    import yaml

    config_path = tmp_path / "gateway.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "agent_url": "http://localhost:9999",
                "adapters": {
                    "telegram": {
                        "enabled": True,
                        "token": "test-token",
                        "allowed_users": [123],
                    }
                },
            }
        )
    )

    config = load_gateway_config(config_path)
    assert config.telegram.enabled is True
    assert config.telegram.token == "test-token"
    assert config.telegram.allowed_users == [123]
    assert config.agent_url == "http://localhost:9999"


def test_env_var_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr("patina.gateway.base.DEFAULT_HOME", tmp_path)
    monkeypatch.setenv("TEST_TG_TOKEN", "resolved-token")
    import yaml

    config_path = tmp_path / "gateway.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "adapters": {
                    "telegram": {
                        "enabled": True,
                        "token": "${TEST_TG_TOKEN}",
                    }
                }
            }
        )
    )

    config = load_gateway_config(config_path)
    assert config.telegram.token == "resolved-token"


def test_missing_env_var_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("patina.gateway.base.DEFAULT_HOME", tmp_path)
    import yaml

    config_path = tmp_path / "gateway.yaml"
    config_path.write_text(
        yaml.dump(
            {
                "adapters": {
                    "telegram": {
                        "enabled": True,
                        "token": "${NONEXISTENT_VAR_XYZ}",
                    }
                }
            }
        )
    )

    with pytest.raises(ValueError, match="NONEXISTENT_VAR_XYZ"):
        load_gateway_config(config_path)


def test_send_to_agent_correct_payload():
    from patina.gateway.base import GatewayAdapter

    class TestAdapter(GatewayAdapter):
        async def start(self):
            pass

        async def stop(self):
            pass

    adapter = TestAdapter(agent_url="http://test:8321")
    msg = InboundMessage(
        channel="test-ch",
        user_id="u1",
        text="hello",
        timestamp=1000.0,
        platform="test",
    )

    mock_response = MagicMock()
    mock_response.json.return_value = {"response": "hi there"}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    import httpx

    with patch.object(httpx, "AsyncClient", return_value=mock_client):
        result = asyncio.run(adapter.send_to_agent(msg))

    assert result == "hi there"
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert call_kwargs.kwargs["json"]["prompt"] == "hello"
    assert call_kwargs.kwargs["json"]["channel"] == "test-ch"
