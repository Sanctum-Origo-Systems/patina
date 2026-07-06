from __future__ import annotations

import json
from datetime import datetime

from eval.cognitive.run import collect_tool_reliability


def test_tool_reliability_populated_log(tmp_path):
    log = tmp_path / "call_log.jsonl"
    records = [
        {"tool": "beliefs", "success": True},
        {"tool": "priorities", "success": True},
        {"tool": "relationships", "success": False},
        {"tool": "store_search", "success": True},
        {"tool": "beliefs", "success": False},
    ]
    log.write_text("\n".join(json.dumps(r) for r in records))

    result = collect_tool_reliability(log_path=log)

    assert result.value == 0.6
    assert isinstance(result.value, float)
    datetime.fromisoformat(result.collected_at)


def test_tool_reliability_empty_log(tmp_path):
    log = tmp_path / "call_log.jsonl"
    log.write_text("")

    result = collect_tool_reliability(log_path=log)

    assert result.value == 0.0
    datetime.fromisoformat(result.collected_at)


def test_tool_reliability_missing_path(tmp_path):
    missing = tmp_path / "nonexistent" / "call_log.jsonl"

    result = collect_tool_reliability(log_path=missing)

    assert result.value == 0.0
    assert result.unavailable is True
    datetime.fromisoformat(result.collected_at)
