"""Eval: uncapped contradiction detection on a labeled, anonymized fixture.

Run: uv run python eval/deterministic/contradiction_eval.py [--fixture PATH] [--thresholds PATH]
Pass/fail gates for precision, recall and precision@k come from
``contradiction_thresholds.toml``. Exits 1 when any metric is below its gate.

The fixture's claims are loaded into an in-memory store and scored with
``find_all_contradictions`` (no MAX_CONTRADICTIONS cap); no config or store
on disk is read.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tomllib
from collections import Counter
from pathlib import Path

from patina.beliefs.contradictions import count_by_predicate, find_all_contradictions
from patina.graph import insert_claim, upsert_entity
from patina.models import Claim, Entity
from patina.store import (
    _FTS,
    _FTS_TRIGGERS,
    _INDEXES,
    _SCHEMA_VERSION,
    _TABLES,
    ensure_objective_target_columns,
    run_pending_migrations,
)

FIXTURE_PATH = Path(__file__).with_name("contradiction_fixture.json")
THRESHOLDS_PATH = Path(__file__).with_name("contradiction_thresholds.toml")

LABEL_CONTRADICTION = "contradiction"
LABEL_PROMOTION = "promotion"
LABEL_TEMPORAL_CHANGE = "temporal_change"
LABEL_FALSE_POSITIVE = "false_positive"
LABELS = (LABEL_CONTRADICTION, LABEL_PROMOTION, LABEL_TEMPORAL_CHANGE, LABEL_FALSE_POSITIVE)

# Relation tags find_all_contradictions emits; only "conflict" is a predicted contradiction.
CONFLICT = "conflict"
RELATIONS = (CONFLICT, "possible_promotion", "temporal_change", "contained_org")

THRESHOLD_KEYS = ("min_precision", "min_recall", "min_precision_at_k")

PairKey = frozenset[str]


def load_fixture(path: Path = FIXTURE_PATH) -> dict:
    """Load a labeled fixture; raises ``ValueError`` on a missing label or category."""
    with open(path, encoding="utf-8") as f:
        fixture = json.load(f)
    claims = {c["id"]: c for c in fixture.get("claims", [])}
    seen: set[PairKey] = set()
    for pair in fixture.get("pairs", []):
        pid = pair.get("id")
        label = pair.get("label")
        if label not in LABELS:
            raise ValueError(f"pair {pid!r}: missing or unknown label {label!r}")
        category = pair.get("category")
        if label == LABEL_FALSE_POSITIVE and not (isinstance(category, str) and category.strip()):
            raise ValueError(f"pair {pid!r}: false_positive needs a non-empty category")
        if label != LABEL_FALSE_POSITIVE and category is not None:
            raise ValueError(f"pair {pid!r}: only false_positive pairs carry a category")
        ids = pair.get("claims", [])
        if len(ids) != 2 or any(i not in claims for i in ids) or ids[0] == ids[1]:
            raise ValueError(f"pair {pid!r}: needs two distinct claim ids from the fixture")
        c1, c2 = claims[ids[0]], claims[ids[1]]
        if (c1["subject_id"], c1["predicate"]) != (c2["subject_id"], c2["predicate"]):
            raise ValueError(f"pair {pid!r}: claims differ in subject or predicate")
        key = frozenset(ids)
        if key in seen:
            raise ValueError(f"pair {pid!r}: labeled more than once")
        seen.add(key)
    return fixture


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, float]:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    missing = [k for k in THRESHOLD_KEYS if k not in raw]
    if missing:
        raise ValueError(f"{path}: missing thresholds {missing}")
    return {k: float(raw[k]) for k in THRESHOLD_KEYS}


def memory_store(fixture: dict) -> sqlite3.Connection:
    """An in-memory store with the full schema and the fixture's entities and claims."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_TABLES)
    ensure_objective_target_columns(conn)
    conn.executescript(_FTS)
    conn.executescript(_FTS_TRIGGERS)
    conn.executescript(_INDEXES)
    conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,))
    conn.commit()
    run_pending_migrations(conn)
    for raw in fixture.get("entities", []):
        upsert_entity(conn, Entity(id=raw["id"], type="person", name=raw["name"]))
    for raw in fixture.get("claims", []):
        insert_claim(
            conn,
            Claim(
                id=raw["id"],
                subject_id=raw["subject_id"],
                predicate=raw["predicate"],
                object=raw["object"],
                confidence=raw.get("confidence", 0.5),
                first_asserted=raw.get("first_asserted", ""),
                last_confirmed=raw.get("last_confirmed", ""),
            ),
        )
    return conn


def pair_key(result: dict) -> PairKey:
    return frozenset((result["claim_id_1"], result["claim_id_2"]))


def labels_by_pair(fixture: dict) -> dict[PairKey, dict]:
    return {frozenset(p["claims"]): p for p in fixture.get("pairs", [])}


def evaluate(fixture: dict, results: list[dict]) -> dict:
    """Score ranked ``find_all_contradictions`` output against the fixture's labels."""
    labels = labels_by_pair(fixture)

    def label(result: dict) -> str | None:
        pair = labels.get(pair_key(result))
        return pair["label"] if pair else None

    true_total = sum(1 for p in labels.values() if p["label"] == LABEL_CONTRADICTION)
    predicted = [r for r in results if r["relation"] == CONFLICT]
    hits = sum(1 for r in predicted if label(r) == LABEL_CONTRADICTION)

    categories = sorted({p["category"] for p in labels.values() if "category" in p})
    false_positives = dict.fromkeys(categories, 0)
    for r in predicted:
        pair = labels.get(pair_key(r))
        if pair and pair["label"] == LABEL_FALSE_POSITIVE:
            false_positives[pair["category"]] += 1

    true_ranks = [
        i
        for i, r in enumerate(results, 1)
        if r["relation"] == CONFLICT and label(r) == LABEL_CONTRADICTION
    ]
    top_k = sum(1 for rank in true_ranks if rank <= true_total)

    tags = Counter(r["relation"] for r in results)
    return {
        "precision": hits / len(predicted) if predicted else 0.0,
        "recall": hits / true_total if true_total else 0.0,
        "false_positives_by_category": false_positives,
        "ranking": {
            "k": true_total,
            "precision_at_k": top_k / true_total if true_total else 0.0,
            "mean_rank_true": sum(true_ranks) / len(true_ranks) if true_ranks else 0.0,
        },
        "uncapped_counts_by_predicate": count_by_predicate(results),
        "tag_counts": {relation: tags.get(relation, 0) for relation in RELATIONS},
    }


def run(fixture: dict) -> dict:
    """Load ``fixture`` into an in-memory store and score the uncapped output."""
    conn = memory_store(fixture)
    try:
        return evaluate(fixture, find_all_contradictions(conn))
    finally:
        conn.close()


def check_thresholds(report: dict, thresholds: dict[str, float]) -> list[str]:
    """One line per metric below its gate; empty when every gate passes."""
    metrics = {
        "min_precision": ("precision", report["precision"]),
        "min_recall": ("recall", report["recall"]),
        "min_precision_at_k": ("precision_at_k", report["ranking"]["precision_at_k"]),
    }
    return [
        f"{name} {value:.3f} < {thresholds[key]:.3f}"
        for key, (name, value) in metrics.items()
        if value < thresholds[key]
    ]


def main(argv: list[str] | None = None) -> int:
    """Print the report; return 1 when any metric is below its threshold, else 0."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--thresholds", type=Path, default=THRESHOLDS_PATH)
    args = parser.parse_args(argv)

    thresholds = load_thresholds(args.thresholds)
    report = run(load_fixture(args.fixture))
    failures = check_thresholds(report, thresholds)
    print("Contradiction eval")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"thresholds: {json.dumps(thresholds)} -> {'FAIL' if failures else 'PASS'}")
    for line in failures:
        print(f"  {line}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
