from __future__ import annotations

import asyncio

import pytest

from patina.mcp.server import mcp


@pytest.fixture
def tool_names():
    tools = asyncio.run(mcp.list_tools())
    return [t.name for t in tools]


def test_server_has_tools(tool_names):
    assert "catch_up" in tool_names
    assert "priorities" in tool_names
    assert "dismiss" in tool_names
    assert "beliefs" in tool_names
    assert "stale" in tool_names
    assert "contradictions" in tool_names
    assert "relationships" in tool_names
    assert "style_show" in tool_names
    assert "draft_reply" in tool_names
    assert "journal_write" in tool_names
    assert "journal_search" in tool_names
    assert "profile_read" in tool_names
    assert "soul_read" in tool_names
    assert "objective_list" in tool_names
    assert "objective_add" in tool_names
    assert "objective_remove" in tool_names
    assert "autonomy_status" in tool_names
    assert "approve" in tool_names
    assert "reject" in tool_names


def test_no_soul_write_tool(tool_names):
    assert "soul_write" not in tool_names
    assert "soul_update" not in tool_names
