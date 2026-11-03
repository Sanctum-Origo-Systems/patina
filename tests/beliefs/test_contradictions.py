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


def _claim(db_conn, cid, predicate, obj, subject="e1", confidence=0.5):
    insert_claim(
        db_conn,
        Claim(
            id=cid,
            subject_id=subject,
            predicate=predicate,
            object=obj,
            confidence=confidence,
        ),
    )


def _pairs(results):
    return {frozenset((r["object_1"], r["object_2"])) for r in results}


def test_temporary_location_not_contradiction(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c0", "location", "Springfield")
    temporary = [
        "staying at a hotel in Shelbyville",
        "at the airport gate",
        "in the Room 4B meeting room",
        "currently in Ogdenville",
    ]
    for i, obj in enumerate(temporary, start=1):
        _claim(db_conn, f"c{i}", "location", obj)

    pairs = _pairs(find_contradictions_tier1(db_conn))
    for obj in temporary:
        assert frozenset(("Springfield", obj)) not in pairs


def test_two_home_locations_contradict(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "location", "Springfield")
    _claim(db_conn, "c2", "location", "Shelbyville")

    assert _pairs(find_contradictions_tier1(db_conn)) == {frozenset(("Springfield", "Shelbyville"))}


def test_org_with_same_org_email_not_contradiction(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "org", "Example Corp")
    _claim(db_conn, "c2", "org", "Example Corp (jordan@examplecorp.com)")

    assert find_contradictions_tier1(db_conn) == []


def test_org_email_or_domain_only_not_contradiction(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "org", "Example Corp")
    _claim(db_conn, "c2", "org", "jordan@examplecorp.com")
    _claim(db_conn, "c3", "org", "examplecorp.com")

    pairs = _pairs(find_contradictions_tier1(db_conn))
    assert frozenset(("Example Corp", "jordan@examplecorp.com")) not in pairs
    assert frozenset(("Example Corp", "examplecorp.com")) not in pairs


def test_org_engagement_not_contradiction(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "org", "Example Corp")
    _claim(db_conn, "c2", "org", "works on the Acme Widgets engagement")

    assert find_contradictions_tier1(db_conn) == []


def test_two_org_names_contradict(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "org", "Example Corp")
    _claim(db_conn, "c2", "org", "Globex")

    assert _pairs(find_contradictions_tier1(db_conn)) == {frozenset(("Example Corp", "Globex"))}


def test_title_sorts_before_org_and_location(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "a1", "location", "Springfield", confidence=0.95)
    _claim(db_conn, "a2", "location", "Shelbyville", confidence=0.95)
    _claim(db_conn, "b1", "org", "Example Corp", confidence=0.9)
    _claim(db_conn, "b2", "org", "Globex", confidence=0.9)
    _claim(db_conn, "z1", "title", "Engineer", confidence=0.6)
    _claim(db_conn, "z2", "title", "Engineering Manager", confidence=0.6)

    results = find_contradictions_tier1(db_conn)
    assert [r["predicate"] for r in results] == ["title", "org", "location"]
    assert {results[0]["object_1"], results[0]["object_2"]} == {
        "Engineer",
        "Engineering Manager",
    }


def test_sorts_by_higher_confidence_within_field(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _setup_entity(db_conn, "e2", "Riley")
    _claim(db_conn, "a1", "org", "Example Corp", confidence=0.5)
    _claim(db_conn, "a2", "org", "Globex", confidence=0.6)
    _claim(db_conn, "b1", "org", "Initech", subject="e2", confidence=0.5)
    _claim(db_conn, "b2", "org", "Umbrella", subject="e2", confidence=0.9)

    results = find_contradictions_tier1(db_conn)
    assert [r["subject"] for r in results] == ["Riley", "Jordan"]


def test_cap_applied_after_sort_keeps_all_titles(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    # 15 distinct home locations -> 105 location pairs, all real conflicts.
    for i in range(15):
        _claim(db_conn, f"a{i:02d}", "location", f"Town {i}", confidence=0.9)
    titles = []
    for i in range(3):
        eid = f"t{i}"
        _setup_entity(db_conn, eid, f"Person {i}")
        _claim(db_conn, f"z{i}a", "title", "Engineer", subject=eid)
        _claim(db_conn, f"z{i}b", "title", "Engineering Manager", subject=eid)
        titles.append((f"z{i}a", f"z{i}b"))

    results = find_contradictions_tier1(db_conn)
    assert len(results) == 100
    returned = {(r["claim_id_1"], r["claim_id_2"]) for r in results}
    for pair in titles:
        assert pair in returned


def test_behavioral_predicates_excluded(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "behavioral:communication_style", "terse")
    _claim(db_conn, "c2", "behavioral:communication_style", "verbose")

    assert find_contradictions_tier1(db_conn) == []
