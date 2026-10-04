"""Tests that verify each edge-case shape in the seeded_store fixture."""

from __future__ import annotations

import json


def test_handle_named_sender_358(seeded_store):
    row = seeded_store.execute("SELECT * FROM entities WHERE id = 'handle-sender-358'").fetchone()
    assert row is not None
    assert row["name"] == "jdoe_42"
    assert row["type"] == "person"


def test_w_prefix_slack_id_363(seeded_store):
    row = seeded_store.execute("SELECT * FROM entities WHERE id = 'w-prefix-363'").fetchone()
    assert row is not None
    aliases = json.loads(row["aliases"])
    w_aliases = [a for a in aliases if a.startswith("W")]
    assert len(w_aliases) >= 1


def test_overlapping_aliases_distinct_slack_ids_364(seeded_store):
    a = seeded_store.execute("SELECT * FROM entities WHERE id = 'alias-overlap-364-a'").fetchone()
    b = seeded_store.execute("SELECT * FROM entities WHERE id = 'alias-overlap-364-b'").fetchone()
    assert a is not None and b is not None

    a_aliases = json.loads(a["aliases"])
    b_aliases = json.loads(b["aliases"])
    shared = set(a_aliases) & set(b_aliases)
    assert len(shared) >= 1

    a_slack = {x for x in a_aliases if x.startswith("slack:")}
    b_slack = {x for x in b_aliases if x.startswith("slack:")}
    assert a_slack != b_slack


def test_correct_merge_triple_359(seeded_store):
    rows = seeded_store.execute("SELECT * FROM entities WHERE id LIKE 'merge-%-359'").fetchall()
    assert len(rows) == 3

    names = {r["name"] for r in rows}
    assert any(" " in n for n in names), "should have a full name"
    assert any("@" in n for n in names), "should have an email"
    assert any(" " not in n and "@" not in n for n in names), "should have a handle"

    slack_ids = set()
    for r in rows:
        for alias in json.loads(r["aliases"]):
            if alias.startswith("slack:"):
                slack_ids.add(alias)
    assert len(slack_ids) == 1, "all three should share the same Slack ID"


def test_description_as_name_346(seeded_store):
    row = seeded_store.execute("SELECT * FROM entities WHERE id = 'desc-name-346'").fetchone()
    assert row is not None
    name = row["name"]
    assert len(name.split()) > 4 or "of" in name.lower()


def test_owner_duplicate_slack_id_332(seeded_store):
    owner = seeded_store.execute("SELECT * FROM entities WHERE id = 'owner-332'").fetchone()
    dup = seeded_store.execute("SELECT * FROM entities WHERE id = 'owner-dup-332'").fetchone()
    assert owner is not None and dup is not None
    assert owner["is_owner"] == 1
    assert dup["is_owner"] == 0
    owner_aliases = json.loads(owner["aliases"])
    assert dup["name"] in owner_aliases


def test_slack_link_markup_334(seeded_store):
    row = seeded_store.execute("SELECT * FROM entities WHERE id = 'link-markup-334'").fetchone()
    assert row is not None
    assert "|" in row["name"]


def test_contaminated_bare_slack_id_372(seeded_store):
    """Shape 9: entity with slack:-prefixed ID and a different bare Slack ID."""
    a = seeded_store.execute("SELECT * FROM entities WHERE id = 'contaminated-372-a'").fetchone()
    b = seeded_store.execute("SELECT * FROM entities WHERE id = 'contaminated-372-b'").fetchone()
    assert a is not None and b is not None

    a_aliases = json.loads(a["aliases"])
    assert "slack:U0SOREN" in a_aliases, "should have a prefixed Slack ID"
    assert "U0LIANA" in a_aliases, "should have a bare Slack ID from another entity"
    assert b["name"] == "U0LIANA"


def test_handle_alias_no_id_373(seeded_store):
    """Shape 10: full-name entity holds handle as alias, no Slack ID."""
    name_ent = seeded_store.execute(
        "SELECT * FROM entities WHERE id = 'handle-alias-noid-373-name'"
    ).fetchone()
    handle_ent = seeded_store.execute(
        "SELECT * FROM entities WHERE id = 'handle-alias-noid-373-handle'"
    ).fetchone()
    assert name_ent is not None and handle_ent is not None
    assert " " in name_ent["name"]
    aliases = json.loads(name_ent["aliases"])
    assert handle_ent["name"] in aliases


def test_bare_contaminated_slack_id_373(seeded_store):
    """Shape 11: entity with two bare (non-slack:-prefixed) Slack IDs."""
    a = seeded_store.execute("SELECT * FROM entities WHERE id = 'bare-contam-373-a'").fetchone()
    b = seeded_store.execute("SELECT * FROM entities WHERE id = 'bare-contam-373-b'").fetchone()
    assert a is not None and b is not None

    a_aliases = json.loads(a["aliases"])
    assert "U0TESSA" in a_aliases
    assert "U0MAXIM" in a_aliases
    assert all(not alias.startswith("slack:") for alias in a_aliases)
    assert b["name"] == "U0MAXIM"


def test_bare_contaminated_excluded_from_dedup_373(seeded_store):
    """Shape 11: bare contaminated entity is excluded and flagged as needs review."""
    from patina.maintenance import find_dedup_candidates

    result = find_dedup_candidates(seeded_store)

    review_names = {r["name"] for r in result["needs_review"]}
    assert "Tessa Lindgren" in review_names

    for c in result["candidates"]:
        all_ids = {c["keep"]["id"]} | {d["id"] for d in c["drop"]}
        assert "bare-contam-373-a" not in all_ids


def test_contaminated_entity_excluded_from_dedup_372(seeded_store):
    """Contaminated entity is excluded from merge pool and flagged as needs review."""
    from patina.maintenance import find_dedup_candidates

    result = find_dedup_candidates(seeded_store)

    review_names = {r["name"] for r in result["needs_review"]}
    assert "Soren Voss" in review_names

    for c in result["candidates"]:
        all_ids = {c["keep"]["id"]} | {d["id"] for d in c["drop"]}
        assert "contaminated-372-a" not in all_ids


def test_correct_merge_keeps_full_name_359(seeded_store):
    """Dedup of the correct-merge triple keeps the full name as canonical."""
    from patina.maintenance import find_dedup_candidates

    result = find_dedup_candidates(seeded_store)
    candidates = result["candidates"]

    merge_group = None
    for c in candidates:
        ids = {c["keep"]["id"]} | {d["id"] for d in c["drop"]}
        if "merge-name-359" in ids:
            merge_group = c
            break

    assert merge_group is not None, "Should find a merge group for the triple"
    assert merge_group["keep"]["name"] == "Dana Kowalski"


def test_dangling_claims_333(seeded_store):
    valid = seeded_store.execute("SELECT * FROM claims WHERE id = 'claim-valid-333'").fetchone()
    dangling = seeded_store.execute(
        "SELECT * FROM claims WHERE id = 'claim-dangling-333'"
    ).fetchone()
    assert valid is not None
    assert dangling is not None

    entity_ids = {r["id"] for r in seeded_store.execute("SELECT id FROM entities").fetchall()}
    assert valid["subject_id"] in entity_ids
    assert dangling["subject_id"] not in entity_ids
