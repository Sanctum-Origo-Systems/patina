from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _mcp_requirement() -> Requirement:
    data = tomllib.loads(PYPROJECT.read_text())
    reqs = [Requirement(dep) for dep in data["project"]["dependencies"]]
    matches = [r for r in reqs if r.name == "mcp"]
    assert len(matches) == 1, f"expected exactly one mcp requirement, got {matches}"
    return matches[0]


def test_mcp_requirement_excludes_2_x():
    # mcp 2.x renamed FastMCP to MCPServer; patina-mcp crashes on import there.
    spec = _mcp_requirement().specifier
    assert "2.0" not in spec, f"mcp requirement allows 2.x: {spec}"
    assert "2.3.0" not in spec
    assert "1.30.0" in spec


def test_mcp_requirement_keeps_cli_extra():
    assert "cli" in _mcp_requirement().extras


def test_fastmcp_importable():
    from mcp.server.fastmcp import FastMCP

    assert FastMCP is not None
