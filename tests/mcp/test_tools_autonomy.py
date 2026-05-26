from __future__ import annotations

from patina.mcp.tools_autonomy import autonomy_status
from patina.store import init_db


def test_autonomy_status_returns_string(db_path, tmp_path):
    init_db(db_path)
    result = autonomy_status()
    assert isinstance(result, str)
    assert "Level" in result
