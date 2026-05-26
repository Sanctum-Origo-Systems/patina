from __future__ import annotations

from patina.scheduler import heartbeat_once


def test_heartbeat_once_runs_all_tasks(tmp_path):
    result = heartbeat_once(home=tmp_path)
    assert "tasks_run" in result
    assert "ingest" in result["tasks_run"]
    assert "decay" in result["tasks_run"]
    assert "escalation_check" in result["tasks_run"]
    assert result["errors"] == []


def test_heartbeat_once_returns_ingest_results(tmp_path):
    result = heartbeat_once(home=tmp_path)
    assert result["ingest"]["adapters_run"] == 0
    assert result["decay"]["stale_count"] == 0
    assert result["escalation"]["shifts"] == 0
