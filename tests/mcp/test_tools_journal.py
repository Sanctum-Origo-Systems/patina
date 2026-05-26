from __future__ import annotations

from patina.mcp.tools_journal import journal_search, journal_write
from patina.store import init_db


def test_journal_write_and_search(db_path, tmp_path):
    init_db(db_path)

    result = journal_write("2025-05-25", "Met with the team about Atlas migration")
    assert "saved" in result

    search_result = journal_search("Atlas")
    assert "Atlas" in search_result


def test_journal_search_no_results(db_path, tmp_path):
    init_db(db_path)
    result = journal_search("nonexistent_xyz")
    assert "No journal entries" in result
