from __future__ import annotations

from patina.store import DEFAULT_HOME


def profile_read() -> str:
    path = DEFAULT_HOME / "PROFILE.md"
    if not path.exists():
        return "No PROFILE.md found. Run `patina profile refresh` to generate."
    return path.read_text()


def soul_read() -> str:
    path = DEFAULT_HOME / "SOUL.md"
    if not path.exists():
        return "No SOUL.md found. Create one at ~/.patina/SOUL.md to define agent personality."
    return path.read_text()


def register(mcp):
    mcp.tool()(profile_read)
    mcp.tool()(soul_read)
