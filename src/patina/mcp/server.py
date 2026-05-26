from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from patina.mcp import (
    tools_autonomy,
    tools_beliefs,
    tools_catch_up,
    tools_journal,
    tools_objectives,
    tools_profile,
    tools_style,
)
from patina.store import get_db_path, init_db

mcp = FastMCP("patina-core")

tools_catch_up.register(mcp)
tools_beliefs.register(mcp)
tools_style.register(mcp)
tools_journal.register(mcp)
tools_profile.register(mcp)
tools_objectives.register(mcp)
tools_autonomy.register(mcp)


def main():
    db_path = get_db_path()
    init_db(db_path)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
