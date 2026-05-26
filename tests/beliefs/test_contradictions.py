from __future__ import annotations

from patina.beliefs.contradictions import (
    find_contradictions_tier1,
    find_contradictions_tier3,
)
from patina.graph import insert_claim, upsert_entity
from patina.llm import MockLLM
from patina.models import Claim, Entity


def _setup_entity(db_conn, eid, name):
    upsert_entity(db_conn, Entity(id=eid, type="person", name=name))


def test_same_subject_predicate_diff_object(db_conn):
    _setup_entity(db_conn, "e1", "James")
    insert_claim(
        db_conn,
        Claim(id="c1", subject_id="e1", predicate="owns", object="Project A"),
    )
    insert_claim(
        db_conn,
        Claim(id="c2", subject_id="e1", predicate="owns", object="Project B"),
    )

    results = find_contradictions_tier1(db_conn)
    assert len(results) == 1
    assert results[0]["subject"] == "James"
    assert {results[0]["object_1"], results[0]["object_2"]} == {"Project A", "Project B"}


def test_same_object_not_contradiction(db_conn):
    _setup_entity(db_conn, "e1", "James")
    insert_claim(
        db_conn,
        Claim(id="c1", subject_id="e1", predicate="owns", object="Project A"),
    )
    insert_claim(
        db_conn,
        Claim(id="c2", subject_id="e1", predicate="owns", object="Project A"),
    )

    results = find_contradictions_tier1(db_conn)
    assert len(results) == 0


def test_different_subjects_not_contradiction(db_conn):
    _setup_entity(db_conn, "e1", "James")
    _setup_entity(db_conn, "e2", "Alice")
    insert_claim(
        db_conn,
        Claim(id="c1", subject_id="e1", predicate="owns", object="Project A"),
    )
    insert_claim(
        db_conn,
        Claim(id="c2", subject_id="e2", predicate="owns", object="Project B"),
    )

    results = find_contradictions_tier1(db_conn)
    assert len(results) == 0


def test_empty_no_contradictions(db_conn):
    results = find_contradictions_tier1(db_conn)
    assert results == []


def test_tier3_adds_explanation(db_conn):
    _setup_entity(db_conn, "e1", "James")
    insert_claim(
        db_conn,
        Claim(id="c1", subject_id="e1", predicate="owns", object="Project A"),
    )
    insert_claim(
        db_conn,
        Claim(id="c2", subject_id="e1", predicate="owns", object="Project B"),
    )

    llm = MockLLM()
    results = find_contradictions_tier3(db_conn, llm)
    assert len(results) == 1
    assert "explanation" in results[0]
    assert isinstance(results[0]["explanation"], str)
