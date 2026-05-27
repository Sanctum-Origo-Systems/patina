from __future__ import annotations

from starlette.testclient import TestClient

from patina.serve import create_app


def _make_app(tmp_path):
    from patina.agent.config import AgentConfig

    soul_path = tmp_path / "SOUL.md"
    soul_path.write_text("Be helpful.")
    config = AgentConfig(soul_path=soul_path)
    return create_app(config)


def test_health(tmp_path):
    app = _make_app(tmp_path)
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_message_missing_prompt(tmp_path):
    app = _make_app(tmp_path)
    client = TestClient(app)
    response = client.post("/message", json={"channel": "test"})
    assert response.status_code == 400
    assert "prompt required" in response.json()["error"]
