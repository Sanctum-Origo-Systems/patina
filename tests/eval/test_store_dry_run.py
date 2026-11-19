"""Tests for eval/deterministic/store_dry_run.py — the combined dry-run report (#668)."""

from __future__ import annotations

import eval.deterministic.store_dry_run as store_dry_run
from eval.deterministic.relevance_eval import evaluate, format_report, report_sections
from eval.deterministic.store_dry_run import (
    DOWNSTREAM_FEATURES,
    DOWNSTREAM_TITLE,
    REPLAY_TITLE,
    assemble_report,
    downstream_deltas,
)

from tests.eval.test_relevance_eval import MIXED

BEFORE = {"hidden_allies": 4, "catch_up": 12, "relationships": 9}
AFTER = {"hidden_allies": 3, "catch_up": 5, "relationships": 9}


def test_deltas_cover_each_feature_in_order():
    deltas = downstream_deltas(BEFORE, AFTER)

    assert [d.feature for d in deltas] == list(DOWNSTREAM_FEATURES)
    assert [(d.before, d.after, d.delta) for d in deltas] == [(4, 3, -1), (12, 5, -7), (9, 9, 0)]
    assert [d.line() for d in deltas] == [
        "hidden_allies: 4 -> 3 (-1)",
        "catch_up: 12 -> 5 (-7)",
        "relationships: 9 -> 9 (+0)",
    ]


def test_assemble_report_reuses_step_one_sections(monkeypatch):
    calls = []

    def spy(report, min_recall):
        calls.append((report, min_recall))
        return report_sections(report, min_recall)

    monkeypatch.setattr(store_dry_run, "report_sections", spy)
    relevance = evaluate(MIXED)

    sections = assemble_report(relevance, downstream_deltas(BEFORE, AFTER), min_recall=0.5)

    assert calls == [(relevance, 0.5)]
    step_one = report_sections(relevance, 0.5)
    assert [s for s in sections if s[0] not in (DOWNSTREAM_TITLE, REPLAY_TITLE)] == step_one
    titles = [t for t, _ in sections]
    assert titles == [
        "Recall",
        "False drops by reason",
        DOWNSTREAM_TITLE,
        REPLAY_TITLE,
        "Edge cases",
    ]


def test_assembled_report_has_recall_false_drops_and_deltas():
    sections = assemble_report(
        evaluate(MIXED),
        downstream_deltas(BEFORE, AFTER),
        min_recall=0.5,
        replay_lines=["would-be drops: 2"],
        retain_only=1,
    )
    out = format_report(sections)

    assert "recall: 0.400 (2/5 labeled-relevant kept)" in out
    assert "not_direct: 2" in out
    assert "bot_or_list: 1" in out
    assert "catch_up: 12 -> 5 (-7)" in out
    assert "would-be drops: 2" in out
    assert "would-be drops in RETAIN_ONLY: 1" in out


def test_retain_only_absent_is_marked_not_available():
    sections = dict(assemble_report(evaluate(MIXED), [], min_recall=0.5, retain_only=None))

    assert sections[REPLAY_TITLE] == ["would-be drops in RETAIN_ONLY: not available"]
