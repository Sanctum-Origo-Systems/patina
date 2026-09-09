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
    long_body = "widget " * 500
    journal_write("2026-07-02", long_body)

    result = journal_search("widget", snippet_chars=500)
    entry_text = result.split("] ", 1)[1]
    assert len(entry_text) == 501  # 500 chars + ellipsis character
    assert entry_text.endswith("…")
    assert entry_text[:500] == long_body[:500]


def test_journal_search_snippet_chars_zero_returns_unlimited(db_path):
    long_body = "gadget " * 750
    journal_write("2026-07-03", long_body)

    result = journal_search("gadget", snippet_chars=0)
    assert long_body in result


def test_journal_search_no_truncation_when_under_limit(db_path):
    short_body = "Quick note about the meeting"
    journal_write("2026-07-04", short_body)

    result = journal_search("Quick note", snippet_chars=2000)
    assert short_body in result
    assert "…" not in result


def test_journal_search_default_snippet_chars_is_2000(db_path):
    body = "sprocket " * 300
    journal_write("2026-07-05", body)

    result = journal_search("sprocket")
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


def test_journal_search_multi_word_non_adjacent(db_path):
    journal_write(
        "2026-07-10",
        "Discussed the alpha project timeline and reviewed beta docs before gamma release",
    )

    result = journal_search("alpha beta gamma")
    assert "alpha" in result
    assert "2026-07-10" in result

    result2 = journal_search("alpha gamma")
    assert "2026-07-10" in result2


def test_journal_search_colon_does_not_crash(db_path):
    journal_write("2026-07-11", "Follow-up on re:Invent planning session")

    result = journal_search("re:Invent")
    assert "re:Invent" in result


def test_journal_search_or_fallback_partial_match(db_path):
    journal_write("2026-08-01", "The quick brown fox jumped over the lazy dog")

    result = journal_search("quick brown lazy cat")
    assert "quick brown fox" in result
    assert "2026-08-01" in result


def test_journal_search_or_fallback_single_term_match(db_path):
    journal_write("2026-08-02", "Reviewed the quarterly budget forecast")

    result = journal_search("budget roadmap timeline")
    assert "budget" in result
    assert "2026-08-02" in result


def test_journal_search_and_preferred_over_or(db_path):
    journal_write("2026-08-03", "Alpha and beta testing completed")
    journal_write("2026-08-04", "Only alpha was mentioned here")

    result = journal_search("alpha beta")
    assert "2026-08-03" in result


def test_journal_search_recency_mode_empty_query(db_path):
    journal_write("2026-08-10", "First entry about the project kickoff")
    journal_write("2026-08-11", "Second entry about design review")
    journal_write("2026-08-12", "Third entry about sprint planning")

    result = journal_search("")
    assert "2026-08-12" in result
    assert "2026-08-11" in result
    assert "2026-08-10" in result


def test_journal_search_recency_mode_no_query_arg(db_path):
    journal_write("2026-08-15", "Entry without explicit query arg")

    result = journal_search()
    assert "2026-08-15" in result


def test_journal_search_recency_mode_respects_limit(db_path):
    for i in range(5):
        journal_write(f"2026-08-2{i}", f"Recency entry number {i}")

    result = journal_search("", limit=3)
    assert result.count("- [") == 3


def test_journal_search_recency_mode_ordered_by_date_desc(db_path):
    journal_write("2026-08-01", "Oldest entry for ordering test")
    journal_write("2026-08-03", "Newest entry for ordering test")
    journal_write("2026-08-02", "Middle entry for ordering test")

    result = journal_search("", limit=3)
    lines = result.strip().split("\n")
    assert "2026-08-03" in lines[0]
    assert "2026-08-02" in lines[1]
    assert "2026-08-01" in lines[2]


def test_journal_search_recency_mode_empty_db(db_path):
    result = journal_search("")
    assert result == "No journal entries yet."
