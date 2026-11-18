"""Tests for eval/deterministic/contradiction_eval.py on small hand-built fixtures."""

from __future__ import annotations

import json

import pytest
from eval.deterministic.contradiction_eval import (
    check_thresholds,
    evaluate,
    load_fixture,
    load_thresholds,
    main,
    run,
)

import patina.beliefs.contradictions as contradictions_module


def _claim(claim_id, subject_id, predicate, obj, *, confidence=0.8, first="", last=""):
    return {
        "id": claim_id,
        "subject_id": subject_id,
        "predicate": predicate,
        "object": obj,
        "confidence": confidence,
        "first_asserted": first,
        "last_confirmed": last,
    }


def _pair(pair_id, claims, label, category=None):
    pair = {"id": pair_id, "claims": claims, "label": label}
    if category is not None:
        pair["category"] = category
    return pair


# Labels only; evaluate() is fed hand-built ranked results, so no store is needed.
LABELED = {
    "entities": [],
    "claims": [],
    "pairs": [
        _pair("t1", ["a1", "a2"], "contradiction"),
        _pair("t2", ["b1", "b2"], "contradiction"),
        _pair("promo", ["c1", "c2"], "promotion"),
        _pair("moved", ["d1", "d2"], "temporal_change"),
        _pair("fp-unit", ["e1", "e2"], "false_positive", "parent_and_unit"),
        _pair("fp-place", ["f1", "f2"], "false_positive", "same_place_two_ways"),
    ],
}


def _result(id1, id2, predicate, relation):
    return {"claim_id_1": id1, "claim_id_2": id2, "predicate": predicate, "relation": relation}


# Ranked: a false positive first, one true contradiction, tagged pairs, the other truth.
RANKED = [
    _result("e2", "e1", "org", "conflict"),
    _result("a1", "a2", "title", "conflict"),
    _result("c1", "c2", "title", "possible_promotion"),
    _result("d1", "d2", "org", "temporal_change"),
    _result("f1", "f2", "location", "contained_org"),
    _result("b1", "b2", "location", "conflict"),
]

# Smallest store-backed fixture: one overlapping two-employer conflict, one promotion.
TINY = {
    "entities": [
        {"id": "p-jordan", "name": "Jordan Example"},
        {"id": "p-dana", "name": "Dana Brook"},
    ],
    "claims": [
        _claim(
            "j1",
            "p-jordan",
            "org",
            "Contoso Example",
            first="2025-02-03T09:00:00+00:00",
            last="2026-09-01T17:00:00+00:00",
        ),
        _claim(
            "j2",
            "p-jordan",
            "org",
            "Fabrikam Example",
            first="2026-01-12T09:00:00+00:00",
            last="2026-09-01T17:00:00+00:00",
        ),
        _claim(
            "d1",
            "p-dana",
            "title",
            "Analyst",
            first="2025-02-03T09:00:00+00:00",
            last="2025-10-20T17:00:00+00:00",
        ),
        _claim(
            "d2",
            "p-dana",
            "title",
            "Manager",
            first="2026-01-12T09:00:00+00:00",
            last="2026-09-01T17:00:00+00:00",
        ),
    ],
    "pairs": [
        _pair("case-3", ["j1", "j2"], "contradiction"),
        _pair("case-2", ["d1", "d2"], "promotion"),
    ],
}


def _write(tmp_path, data, name="fixture.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_precision_and_recall_count_only_conflict_pairs():
    report = evaluate(LABELED, RANKED)

    # 3 conflicts, 2 of them labeled contradictions; both truths found.
    assert report["precision"] == pytest.approx(2 / 3)
    assert report["recall"] == 1.0


def test_tagged_pair_is_not_a_predicted_contradiction():
    # Retagging a truth as possible_promotion drops it from hits and recall.
    retagged = [dict(r) for r in RANKED]
    retagged[1]["relation"] = "possible_promotion"

    report = evaluate(LABELED, retagged)

    assert report["precision"] == pytest.approx(1 / 2)
    assert report["recall"] == pytest.approx(1 / 2)


def test_false_positives_counted_only_when_tagged_conflict():
    report = evaluate(LABELED, RANKED)

    # fp-place is tagged contained_org, so it is listed but not counted.
    assert report["false_positives_by_category"] == {
        "parent_and_unit": 1,
        "same_place_two_ways": 0,
    }


def test_ranking_uses_k_equal_to_labeled_contradictions():
    report = evaluate(LABELED, RANKED)

    # Truths at ranks 2 and 6; only rank 2 is within k = 2.
    assert report["ranking"] == {
        "k": 2,
        "precision_at_k": pytest.approx(1 / 2),
        "mean_rank_true": pytest.approx((2 + 6) / 2),
    }


def test_counts_and_tags_cover_every_relation():
    report = evaluate(LABELED, RANKED)

    assert report["uncapped_counts_by_predicate"] == {"location": 2, "org": 2, "title": 2}
    assert report["tag_counts"] == {
        "conflict": 3,
        "possible_promotion": 1,
        "temporal_change": 1,
        "contained_org": 1,
    }


def test_empty_results_report_zeroes_not_errors():
    report = evaluate(LABELED, [])

    assert report["precision"] == 0.0
    assert report["recall"] == 0.0
    assert report["ranking"]["precision_at_k"] == 0.0
    assert report["ranking"]["mean_rank_true"] == 0.0
    assert report["tag_counts"] == dict.fromkeys(
        ("conflict", "possible_promotion", "temporal_change", "contained_org"), 0
    )


def test_run_scores_store_output_and_ignores_cap(monkeypatch):
    default = run(TINY)
    monkeypatch.setattr(contradictions_module, "MAX_CONTRADICTIONS", 1)

    assert run(TINY) == default
    assert default["precision"] == 1.0
    assert default["recall"] == 1.0
    assert default["tag_counts"]["conflict"] == 1
    assert sum(default["tag_counts"].values()) == 2
    assert default["uncapped_counts_by_predicate"] == {"org": 1, "title": 1}


@pytest.mark.parametrize(
    ("pairs", "match"),
    [
        ([_pair("x", ["j1", "j2"], "contradiction", "oops")], "only false_positive"),
        ([_pair("x", ["j1", "d1"], "contradiction")], "subject or predicate"),
        ([_pair("x", ["j1", "missing"], "contradiction")], "two distinct claim ids"),
        ([_pair("x", ["j1", "j1"], "contradiction")], "two distinct claim ids"),
        (
            [_pair("x", ["j1", "j2"], "contradiction"), _pair("y", ["j2", "j1"], "contradiction")],
            "labeled more than once",
        ),
        ([_pair("x", ["j1", "j2"], "false_positive")], "non-empty category"),
        ([{"id": "x", "claims": ["j1", "j2"]}], "label"),
    ],
    ids=[
        "category-on-truth",
        "mixed-predicate",
        "unknown-claim",
        "same-claim",
        "duplicate",
        "fp-no-category",
        "no-label",
    ],
)
def test_load_fixture_rejects_malformed_pairs(tmp_path, pairs, match):
    with pytest.raises(ValueError, match=match):
        load_fixture(_write(tmp_path, {**TINY, "pairs": pairs}))


def test_load_thresholds_requires_every_gate(tmp_path):
    path = tmp_path / "thresholds.toml"
    path.write_text("min_precision = 0.5\nmin_recall = 1.0\n")

    with pytest.raises(ValueError, match="min_precision_at_k"):
        load_thresholds(path)


def test_check_thresholds_names_each_metric_below_gate():
    report = evaluate(LABELED, RANKED)  # precision 0.667, recall 1.0, p@k 0.5
    gates = {"min_precision": 0.7, "min_recall": 1.0, "min_precision_at_k": 0.6}

    failures = check_thresholds(report, gates)

    assert failures == ["precision 0.667 < 0.700", "precision_at_k 0.500 < 0.600"]
    lowered = {**gates, "min_precision": 0.6, "min_precision_at_k": 0.5}
    assert check_thresholds(report, lowered) == []


def test_main_reads_gates_from_toml(tmp_path, capsys):
    fixture = _write(tmp_path, TINY)
    passing = tmp_path / "pass.toml"
    passing.write_text("min_precision = 1.0\nmin_recall = 1.0\nmin_precision_at_k = 1.0\n")
    failing = tmp_path / "fail.toml"
    failing.write_text("min_precision = 1.1\nmin_recall = 1.0\nmin_precision_at_k = 1.0\n")

    assert main(["--fixture", str(fixture), "--thresholds", str(passing)]) == 0
    assert "PASS" in capsys.readouterr().out
    assert main(["--fixture", str(fixture), "--thresholds", str(failing)]) == 1
    assert "precision 1.000 < 1.100" in capsys.readouterr().out
