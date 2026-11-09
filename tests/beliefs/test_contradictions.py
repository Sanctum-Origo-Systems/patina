from __future__ import annotations

from patina.beliefs.contradictions import (
    count_by_predicate,
    find_all_contradictions,
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


def test_org_parent_vs_own_unit_not_contradiction(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "org", "Example Corp (jordan@examplecorp.com)")
    _claim(db_conn, "c2", "org", "Example Corp Labs")

    assert find_contradictions_tier1(db_conn) == []


def test_org_same_company_two_ways_not_contradiction(db_conn):
    shapes = [
        ("Example Corp", "ExCo"),
        ("Example Corp", "EC"),
        ("Example Consulting LLP", "Example Consulting"),
        ("Globex", "Globex (external to organization)"),
        ("Globex", "Globex (contractor)"),
    ]
    for i, (org_1, org_2) in enumerate(shapes):
        eid = f"e{i}"
        _setup_entity(db_conn, eid, f"Person {i}")
        _claim(db_conn, f"c{i}a", "org", org_1, subject=eid)
        _claim(db_conn, f"c{i}b", "org", org_2, subject=eid)

    assert find_contradictions_tier1(db_conn) == []


def test_org_team_note_not_contradiction(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "org", "works with the Example team on a workshop")
    _claim(db_conn, "c2", "org", "Example Corp")

    assert find_contradictions_tier1(db_conn) == []


def test_org_unrelated_names_with_suffixes_contradict(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "org", "Example Corp")
    _claim(db_conn, "c2", "org", "Globex Inc")

    assert _pairs(find_contradictions_tier1(db_conn)) == {frozenset(("Example Corp", "Globex Inc"))}


def test_title_level_or_status_never_pairs(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c0", "title", "Cloud Architect")
    statuses = [
        "L6",
        "IC5",
        "promotion candidate (feedback due Sep 24)",
        "on leave",
        "recently promoted",
        "parental leave",
        "sabbatical",
    ]
    for i, obj in enumerate(statuses, start=1):
        _claim(db_conn, f"c{i}", "title", obj)

    assert find_contradictions_tier1(db_conn) == []


def test_title_same_tokens_any_order_not_contradiction(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "title", "principal delivery")
    _claim(db_conn, "c2", "title", "Delivery Principal")

    assert find_contradictions_tier1(db_conn) == []


def test_title_containment_demoted_after_all_conflicts(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _setup_entity(db_conn, "e2", "Riley")
    _claim(db_conn, "a1", "title", "Cloud Architect Leader", confidence=0.95)
    _claim(db_conn, "a2", "title", "Cloud Architect Leader, Health", confidence=0.95)
    _claim(db_conn, "a3", "title", "Cloud Architect", confidence=0.95)
    _claim(db_conn, "a4", "title", "delivery principal", subject="e2", confidence=0.95)
    _claim(db_conn, "a5", "title", "Principal Delivery Consultant", subject="e2", confidence=0.95)
    _claim(db_conn, "b1", "location", "Springfield", subject="e2", confidence=0.1)
    _claim(db_conn, "b2", "location", "Shelbyville", subject="e2", confidence=0.1)
    _claim(db_conn, "d1", "org", "Example Corp", subject="e2", confidence=0.1)
    _claim(db_conn, "d2", "org", "Globex", subject="e2", confidence=0.1)

    results = find_contradictions_tier1(db_conn)
    assert [r["predicate"] for r in results] == ["org", "location"] + ["title"] * 4
    assert _pairs(results[2:]) == {
        frozenset(("Cloud Architect Leader", "Cloud Architect Leader, Health")),
        frozenset(("Cloud Architect Leader", "Cloud Architect")),
        frozenset(("Cloud Architect Leader, Health", "Cloud Architect")),
        frozenset(("delivery principal", "Principal Delivery Consultant")),
    }


def test_title_disjoint_sorts_before_containment(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "a1", "title", "Engineer", confidence=0.9)
    _claim(db_conn, "a2", "title", "Senior Engineer", confidence=0.9)
    _claim(db_conn, "a3", "title", "Engineering Manager", confidence=0.5)

    results = find_contradictions_tier1(db_conn)
    assert [frozenset((r["object_1"], r["object_2"])) for r in results] == [
        frozenset(("Engineer", "Engineering Manager")),
        frozenset(("Senior Engineer", "Engineering Manager")),
        frozenset(("Engineer", "Senior Engineer")),
    ]


def test_cap_keeps_real_conflicts_over_restatements(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    # 15 nested titles -> 105 containment pairs, all demoted.
    words = [f"word{i}" for i in range(15)]
    for i in range(15):
        _claim(db_conn, f"a{i:02d}", "title", " ".join(words[: i + 1]), confidence=0.99)
    _setup_entity(db_conn, "e2", "Riley")
    _claim(db_conn, "z1", "location", "Springfield", subject="e2", confidence=0.1)
    _claim(db_conn, "z2", "location", "Shelbyville", subject="e2", confidence=0.1)

    results = find_contradictions_tier1(db_conn)
    assert len(results) == 100
    assert (results[0]["claim_id_1"], results[0]["claim_id_2"]) == ("z1", "z2")


def test_org_email_employer_vs_unit_is_contained_after_conflicts(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "a1", "org", "Example Corp (jordan@example.com)", confidence=0.99)
    _claim(db_conn, "a2", "org", "Widget Labs", confidence=0.99)
    _setup_entity(db_conn, "e2", "Riley")
    _claim(db_conn, "b1", "location", "Springfield", subject="e2", confidence=0.1)
    _claim(db_conn, "b2", "location", "Shelbyville", subject="e2", confidence=0.1)
    _claim(db_conn, "d1", "org", "Example Corp", subject="e2", confidence=0.1)
    _claim(db_conn, "d2", "org", "Globex", subject="e2", confidence=0.1)

    results = find_contradictions_tier1(db_conn)
    assert [r["relation"] for r in results] == ["conflict", "conflict", "contained_org"]
    assert {results[-1]["object_1"], results[-1]["object_2"]} == {
        "Example Corp (jordan@example.com)",
        "Widget Labs",
    }


def test_title_status_in_parenthetical_never_pairs(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "title", "PTO (on leave)")
    _claim(db_conn, "c2", "title", "Sr. Consultant")
    _claim(db_conn, "c3", "title", "PTO")

    assert find_contradictions_tier1(db_conn) == []


def test_org_engagement_notes_not_contradiction(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c0", "org", "Example Corp")
    notes = [
        "Works in Team Alpha, collaborating in area Beta",
        "involved in Program A / Program B",
        "has access to the customer environment",
        "works in Area Gamma",
        "has access to the shared environment",
    ]
    for i, obj in enumerate(notes, start=1):
        _claim(db_conn, f"c{i}", "org", obj)

    pairs = _pairs(find_contradictions_tier1(db_conn))
    for obj in notes:
        assert frozenset(("Example Corp", obj)) not in pairs


def test_title_containment_marked_possible_promotion(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "title", "Cloud Architect")
    _claim(db_conn, "c2", "title", "Cloud Architect Leader")
    _claim(db_conn, "c3", "title", "Engineer")

    results = find_contradictions_tier1(db_conn)
    relations = {frozenset((r["object_1"], r["object_2"])): r["relation"] for r in results}
    assert relations[frozenset(("Cloud Architect", "Cloud Architect Leader"))] == (
        "possible_promotion"
    )
    assert relations[frozenset(("Cloud Architect", "Engineer"))] == "conflict"


def test_behavioral_predicates_excluded(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "behavioral:communication_style", "terse")
    _claim(db_conn, "c2", "behavioral:communication_style", "verbose")

    assert find_contradictions_tier1(db_conn) == []


def _seed_pairs(db_conn, predicate, shapes):
    for i, (obj_1, obj_2) in enumerate(shapes):
        eid = f"e{i}"
        _setup_entity(db_conn, eid, f"Person {i}")
        _claim(db_conn, f"c{i}a", predicate, obj_1, subject=eid)
        _claim(db_conn, f"c{i}b", predicate, obj_2, subject=eid)


def test_org_unit_named_in_parent_paren_is_contained(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "org", "Example Cloud")
    _claim(db_conn, "c2", "org", "Example Corp (Example Cloud)")

    results = find_contradictions_tier1(db_conn)
    assert [r["relation"] for r in results] == ["contained_org"]


def test_org_same_pair_both_orders_not_reported(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "org", "Example Corp (Example Cloud)")
    _claim(db_conn, "c2", "org", "Example Cloud (Example Corp)")

    assert find_contradictions_tier1(db_conn) == []


def test_org_engagement_note_in_trailing_paren_not_contradiction(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "org", "Example Corp")
    _claim(db_conn, "c2", "org", "Widget Services (goal is to change how Widget Services delivers)")

    assert find_contradictions_tier1(db_conn) == []


def test_org_more_description_phrasings_not_contradiction(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c0", "org", "Example Corp")
    notes = [
        "works alongside or interfaces with Widget Services",
        "partner working on the Alpha workstream",
        "External to the organization (flagged by email security)",
    ]
    for i, obj in enumerate(notes, start=1):
        _claim(db_conn, f"c{i}", "org", obj)

    pairs = _pairs(find_contradictions_tier1(db_conn))
    for obj in notes:
        assert frozenset(("Example Corp", obj)) not in pairs


def test_org_has_email_address_resolves_to_named_org(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c1", "org", "Example Health")
    _claim(db_conn, "c2", "org", "Has an Example Health email address (jordan@example.com)")
    _setup_entity(db_conn, "e2", "Riley")
    _claim(
        db_conn,
        "d1",
        "org",
        "Has an Example Health email address (riley@example.com)",
        subject="e2",
    )
    _claim(db_conn, "d2", "org", "Widget Labs", subject="e2")

    results = find_contradictions_tier1(db_conn)
    assert [(r["subject"], r["relation"]) for r in results] == [("Riley", "contained_org")]


def test_title_descriptions_never_pair(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    _claim(db_conn, "c0", "title", "Cloud Architect")
    descriptions = [
        "blog author (jordan_123)",
        "employee with 4 years of tenure",
        "was L4 when previously a tech lead",
    ]
    for i, obj in enumerate(descriptions, start=1):
        _claim(db_conn, f"c{i}", "title", obj)

    assert find_contradictions_tier1(db_conn) == []


def test_live_org_and_title_noise_shapes_not_conflicts(db_conn):
    _seed_pairs(
        db_conn,
        "org",
        [
            ("Example Cloud", "Example Corp (Example Cloud)"),
            ("Example Corp (Example Cloud)", "Example Cloud (Example Corp)"),
            ("Example Corp", "Widget Services (goal is to change how Widget Services delivers)"),
            ("Example Corp", "works alongside or interfaces with Widget Services"),
            ("Example Corp", "partner working on the Alpha workstream"),
            ("Example Corp", "External to the organization (flagged by email security)"),
            ("Example Health", "Has an Example Health email address (jordan@example.com)"),
            ("Example Corp", "Sample Industries"),
        ],
    )
    _setup_entity(db_conn, "t1", "Taylor")
    _claim(db_conn, "t1a", "title", "Engineer", subject="t1")
    _claim(db_conn, "t1b", "title", "blog author (jordan_123)", subject="t1")

    results = find_contradictions_tier1(db_conn)
    conflicts = [r for r in results if r["relation"] == "conflict"]
    assert _pairs(conflicts) == {frozenset(("Example Corp", "Sample Industries"))}
    contained = [r for r in results if r["relation"] == "contained_org"]
    assert _pairs(contained) == {frozenset(("Example Cloud", "Example Corp (Example Cloud)"))}


def test_count_by_predicate_is_uncapped(db_conn):
    _setup_entity(db_conn, "e1", "Jordan")
    # 15 distinct home locations -> 105 location pairs.
    for i in range(15):
        _claim(db_conn, f"a{i:02d}", "location", f"Town {i}")
    _claim(db_conn, "b1", "org", "Example Corp")
    _claim(db_conn, "b2", "org", "Sample Industries")
    _claim(db_conn, "d1", "expertise", "Rust")
    _claim(db_conn, "d2", "expertise", "Go")

    all_results = find_all_contradictions(db_conn)
    assert len(find_contradictions_tier1(db_conn)) == 100
    assert len(all_results) == 107
    totals = count_by_predicate(all_results)
    assert totals == {"expertise": 1, "location": 105, "org": 1}
    assert list(totals) == ["expertise", "location", "org"]
