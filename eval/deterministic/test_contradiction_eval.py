"""Eval: the checked-in contradiction fixture meets the thresholds gate (CI path)."""

from __future__ import annotations

import copy
import json

import pytest
from contradiction_eval import (
    CONFLICT,
    FIXTURE_PATH,
    LABEL_CONTRADICTION,
    LABEL_FALSE_POSITIVE,
    LABELS,
    THRESHOLD_KEYS,
    THRESHOLDS_PATH,
    labels_by_pair,
    load_fixture,
    load_thresholds,
    main,
    memory_store,
    pair_key,
    run,
)

import patina.beliefs.contradictions as contradictions_module
from patina.beliefs.contradictions import count_by_predicate, find_all_contradictions

REPORT_KEYS = (
    "precision",
    "recall",
    "false_positives_by_category",
    "ranking",
    "uncapped_counts_by_predicate",
    "tag_counts",
)


@pytest.fixture
def fixture():
    return load_fixture()


@pytest.fixture
def results(fixture):
    conn = memory_store(fixture)
    yield find_all_contradictions(conn)
    conn.close()


def _pair(fixture: dict, pair_id: str) -> dict:
    return next(p for p in fixture["pairs"] if p["id"] == pair_id)


def _claim(fixture: dict, claim_id: str) -> dict:
    return next(c for c in fixture["claims"] if c["id"] == claim_id)


def _find(results: list[dict], pair: dict) -> tuple[int, dict]:
    return next((i, r) for i, r in enumerate(results) if pair_key(r) == frozenset(pair["claims"]))


def _write(tmp_path, fixture: dict):
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    return path


def test_every_fixture_pair_has_one_known_label_and_fp_category(fixture):
    for pair in fixture["pairs"]:
        assert pair["label"] in LABELS, pair["id"]
        if pair["label"] == LABEL_FALSE_POSITIVE:
            assert pair["category"].strip(), pair["id"]
        else:
            assert "category" not in pair, pair["id"]
    assert {p["label"] for p in fixture["pairs"]} == set(LABELS)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.pop("label"),
        lambda p: p.update(label=""),
        lambda p: p.update(label="maybe"),
    ],
    ids=["no-label", "empty-label", "unknown-label"],
)
def test_fixture_validation_rejects_pair_without_label(tmp_path, fixture, mutate):
    broken = copy.deepcopy(fixture)
    mutate(broken["pairs"][0])
    with pytest.raises(ValueError, match="label"):
        load_fixture(_write(tmp_path, broken))


@pytest.mark.parametrize("category", [None, "", "  "], ids=["missing", "empty", "blank"])
def test_fixture_validation_rejects_false_positive_without_category(tmp_path, fixture, category):
    broken = copy.deepcopy(fixture)
    pair = next(p for p in broken["pairs"] if p["label"] == LABEL_FALSE_POSITIVE)
    if category is None:
        pair.pop("category")
    else:
        pair["category"] = category
    with pytest.raises(ValueError, match="category"):
        load_fixture(_write(tmp_path, broken))


def test_every_reported_pair_is_labeled(fixture, results):
    labels = labels_by_pair(fixture)
    unlabeled = [(r["object_1"], r["object_2"]) for r in results if pair_key(r) not in labels]
    assert not unlabeled


def test_report_has_every_key_populated(fixture):
    report = run(fixture)
    assert set(report) == set(REPORT_KEYS)
    assert 0.0 < report["precision"] <= 1.0
    assert 0.0 < report["recall"] <= 1.0
    assert report["false_positives_by_category"]
    assert report["ranking"]["precision_at_k"] > 0.0
    assert report["ranking"]["mean_rank_true"] >= 1.0
    assert report["uncapped_counts_by_predicate"]
    assert report["tag_counts"]


def test_report_values_on_checked_in_fixture(fixture):
    report = run(fixture)
    assert report["precision"] == pytest.approx(3 / 6)
    assert report["recall"] == 1.0
    assert report["false_positives_by_category"] == {
        "engagement_note": 0,
        "multi_valued_predicate": 1,
        "parent_and_unit": 0,
        "same_company_other_name": 1,
        "same_place_two_ways": 1,
        "status_as_title": 0,
        "temporary_location": 0,
    }
    # Ranked: title conflict, Case 3, a low-confidence org FP, then locations.
    assert report["ranking"] == {
        "k": 3,
        "precision_at_k": pytest.approx(2 / 3),
        "mean_rank_true": pytest.approx((1 + 2 + 5) / 3),
    }


def test_only_conflict_counts_as_predicted_contradiction(fixture, results):
    report = run(fixture)
    labels = labels_by_pair(fixture)
    conflicts = [r for r in results if r["relation"] == CONFLICT]
    hits = [r for r in conflicts if labels[pair_key(r)]["label"] == LABEL_CONTRADICTION]
    true_total = sum(1 for p in fixture["pairs"] if p["label"] == LABEL_CONTRADICTION)

    assert report["precision"] == len(hits) / len(conflicts)
    assert report["recall"] == len(hits) / true_total
    # Tagged pairs stay in the output but are never predicted contradictions.
    tagged = [r for r in results if r["relation"] in {"possible_promotion", "temporal_change"}]
    assert {r["relation"] for r in tagged} == {"possible_promotion", "temporal_change"}
    assert all(r not in conflicts for r in tagged)
    assert sum(report["false_positives_by_category"].values()) == len(conflicts) - len(hits)


def test_uncapped_counts_match_count_by_predicate(fixture, results):
    report = run(fixture)
    assert report["uncapped_counts_by_predicate"] == count_by_predicate(results)
    assert report["uncapped_counts_by_predicate"] == {
        "expertise": 1,
        "location": 2,
        "org": 4,
        "title": 3,
    }


def test_tag_counts_have_every_relation(fixture):
    tags = run(fixture)["tag_counts"]
    assert set(tags) >= {"conflict", "possible_promotion", "temporal_change", "contained_org"}
    assert tags == {
        "conflict": 6,
        "possible_promotion": 1,
        "temporal_change": 2,
        "contained_org": 1,
    }


def test_report_identical_with_cap_of_one(fixture, monkeypatch):
    default = run(fixture)
    monkeypatch.setattr(contradictions_module, "MAX_CONTRADICTIONS", 1)
    assert run(fixture) == default


def test_case_2_promotion_is_not_a_conflict(fixture, results):
    pair = _pair(fixture, "case-2")
    claims = [_claim(fixture, cid) for cid in pair["claims"]]
    assert {c["object"] for c in claims} == {"Analyst", "Manager"}
    assert claims[0]["first_asserted"].startswith("2025")
    assert claims[1]["first_asserted"].startswith("2026")

    _, result = _find(results, pair)
    assert result["subject"] == "Dana Brook"
    assert result["relation"] in {"possible_promotion", "temporal_change"}
    assert result["relation"] != CONFLICT


def test_case_3_overlapping_employers_rank_above_every_false_positive(fixture, results):
    pair = _pair(fixture, "case-3")
    claims = [_claim(fixture, cid) for cid in pair["claims"]]
    assert claims[0]["object"] != claims[1]["object"]
    assert claims[0]["first_asserted"] <= claims[1]["last_confirmed"]
    assert claims[1]["first_asserted"] <= claims[0]["last_confirmed"]

    rank, result = _find(results, pair)
    assert result["relation"] == CONFLICT
    labels = labels_by_pair(fixture)
    fp_ranks = [
        i
        for i, r in enumerate(results)
        if r["relation"] == CONFLICT and labels[pair_key(r)]["label"] == LABEL_FALSE_POSITIVE
    ]
    assert fp_ranks
    assert all(rank < fp for fp in fp_ranks)


def test_thresholds_read_from_toml():
    thresholds = load_thresholds()
    assert set(thresholds) == set(THRESHOLD_KEYS)
    assert THRESHOLDS_PATH.name == "contradiction_thresholds.toml"


def test_checked_in_fixture_meets_thresholds(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "PASS" in out
    for key in REPORT_KEYS:
        assert key in out


def test_stricter_toml_fails_without_code_change(tmp_path):
    path = tmp_path / "thresholds.toml"
    path.write_text("min_precision = 1.0\nmin_recall = 1.0\nmin_precision_at_k = 1.0\n")
    assert main(["--thresholds", str(path), "--fixture", str(FIXTURE_PATH)]) == 1
