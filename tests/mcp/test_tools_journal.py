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


def test_journal_search_returns_full_content(db_path):
    long_body = "Design session notes\n\n" + "Detail paragraph. " * 80
    journal_write("2026-07-01", long_body)

    result = journal_search("Design session")
    assert long_body in result


def test_journal_search_respects_snippet_chars(db_path):
    long_body = "A" * 3000
    journal_write("2026-07-02", long_body)

    result = journal_search("A", snippet_chars=500)
    entry_text = result.split("] ", 1)[1]
    assert len(entry_text) == 501  # 500 chars + ellipsis character
    assert entry_text.endswith("…")
    assert entry_text[:500] == "A" * 500


def test_journal_search_snippet_chars_zero_returns_unlimited(db_path):
    long_body = "B" * 5000
    journal_write("2026-07-03", long_body)

    result = journal_search("B", snippet_chars=0)
    assert long_body in result


def test_journal_search_no_truncation_when_under_limit(db_path):
    short_body = "Quick note about the meeting"
    journal_write("2026-07-04", short_body)

    result = journal_search("Quick note", snippet_chars=2000)
    assert short_body in result
    assert "…" not in result


def test_journal_search_default_snippet_chars_is_2000(db_path):
    body = "X" * 2500
    journal_write("2026-07-05", body)

    result = journal_search("X")
    entry_text = result.split("] ", 1)[1]
    assert len(entry_text) == 2001  # 2000 chars + ellipsis
    assert entry_text.endswith("…")


def test_journal_search_limit_controls_result_count(db_path):
    for i in range(5):
        journal_write(f"2026-07-0{i + 1}", f"Entry number {i} about widgets")

    result = journal_search("widgets", limit=3)
    assert result.count("- [") == 3

    result_all = journal_search("widgets", limit=10)
    assert result_all.count("- [") == 5
