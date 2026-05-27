from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from patina.agent.config import AgentConfig
from patina.agent.runtime import AgentRuntime
from patina.conversations import store_exchange
from patina.store import connect, get_db_path, init_db

_runtime: AgentRuntime | None = None


def _get_runtime() -> AgentRuntime:
    if _runtime is None:
        raise RuntimeError("Server not initialized")
    return _runtime


async def handle_message(request: Request) -> JSONResponse:
    body = await request.json()
    channel = body.get("channel", "http-default")
    user_id = body.get("user_id", "default")
    prompt = body.get("prompt")

    if not prompt:
        return JSONResponse({"error": "prompt required"}, status_code=400)

    runtime = _get_runtime()
    result_text = ""

    from claude_agent_sdk import ResultMessage

    async for message in runtime.query(prompt, channel=channel, user_id=user_id):
        if isinstance(message, ResultMessage):
            result_text = message.result if hasattr(message, "result") else ""

    db_path = get_db_path()
    init_db(db_path)
    conn = connect(db_path)
    try:
        store_exchange(conn, channel, user_id, "user", prompt)
        if result_text:
            store_exchange(conn, channel, user_id, "assistant", result_text)
    finally:
        conn.close()

    return JSONResponse({"response": result_text, "channel": channel})


async def handle_health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def create_app(config: AgentConfig | None = None) -> Starlette:
    global _runtime
    if config is None:
        from patina.agent.config import load_config

        config = load_config()
    config.repl_mode = False
    _runtime = AgentRuntime(config)

    return Starlette(
        routes=[
            Route("/message", handle_message, methods=["POST"]),
            Route("/health", handle_health, methods=["GET"]),
        ]
    )
