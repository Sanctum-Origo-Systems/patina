"""Data invariants: verify that data commands preserve key properties.

Process rule: every live catch adds its anonymized shape to the
seeded_store fixture (conftest.py) in the same PR as the fix.
"""

from __future__ import annotations

import pytest

from patina.beliefs.extractor import extract_beliefs
from patina.maintenance import (
    dedup_entities,
    is_plausible_person_name,
    merge_entities,
    prune_non_person_entities,
    prune_slack_link_entities,
)
from patina.store import delete_dangling_references, find_dangling_references


def _seed_observation(conn, oid, sender_id):
    conn.execute(
        "INSERT INTO observations"
        " (id, source, channel_id, timestamp, sender_entity_id, text,"
        "  metadata, ingested_at, processed)"
        " VALUES (?, 'slack_export', 'C001', 1000.0, ?, 'The quick brown fox',"
        "  '{}', '2025-01-01T00:00:00+00:00', 1)",
        (oid, sender_id),
    )


@pytest.fixture
def invariant_store(seeded_store):
    """Store with all edge-case shapes, prepared for invariant testing.

    Process rule: every live catch adds its anonymized shape to the
    seeded_store fixture (conftest.py) in the same PR as the fix.

    Shapes present (via conftest.seeded_store):
      #358  — handle-named sender (jdoe_42)
      #363  — W-prefixed Slack IDs (W0EXAMPLE1)
      #364  — alias-overlap with distinct Slack IDs (U100 vs U200)
      #359  — correct-merge full-name/handle/email triple (slack:U300)
      #346/#349 — description-as-name ("Head of Engineering at Acme Corp")
      #332  — owner duplicate under Slack ID (U_OWNER332)
      #334  — Slack link markup entity (pipe character)
      #333  — dangling claim (nonexistent subject)
    """
    conn = seeded_store

    # Protect sender entities from prune by adding processed observations.
    _seed_observation(conn, "obs-sender-358", "handle-sender-358")  # #358
    _seed_observation(conn, "obs-handle-359", "merge-handle-359")  # #359
    _seed_observation(conn, "obs-email-359", "merge-email-359")  # #359
    _seed_observation(conn, "obs-owner-dup", "owner-dup-332")  # #332

    # Clean pre-existing dangling refs so invariant checks start clean.  #333
    delete_dangling_references(conn)
    conn.commit()
    yield conn


def _entity_ids(conn):
    return {r["id"] for r in conn.execute("SELECT id FROM entities").fetchall()}


def _assert_invariants(conn, *, after, pre_ids=None, check_merge_triple=False):
    """Assert all six data invariants hold after a command."""

    # 1) Exactly one owner entity
    owners = conn.execute("SELECT COUNT(*) AS c FROM entities WHERE is_owner = 1").fetchone()["c"]
    assert owners == 1, f"after {after}: expected 1 owner, got {owners}"

    # 2) No orphan sender references (observation → deleted entity)
    orphans = conn.execute(
        "SELECT COUNT(*) AS c FROM observations"
        " WHERE sender_entity_id IS NOT NULL"
        "   AND sender_entity_id NOT IN (SELECT id FROM entities)"
    ).fetchone()["c"]
    assert orphans == 0, f"after {after}: {orphans} orphan sender refs"

    # 3) No merge across conflicting Slack IDs or emails
    a = conn.execute("SELECT 1 FROM entities WHERE id = 'alias-overlap-364-a'").fetchone()
    b = conn.execute("SELECT 1 FROM entities WHERE id = 'alias-overlap-364-b'").fetchone()
    assert a is not None and b is not None, (
        f"after {after}: conflicting-Slack-ID entities were incorrectly merged"
    )

    # 4) Zero dangling claims
    dangling = find_dangling_references(conn)
    assert dangling.get("claims", 0) == 0, (
        f"after {after}: {dangling.get('claims', 0)} dangling claims"
    )

    # 5) Newly created persons pass strict name check
    if pre_ids is not None:
        for eid in _entity_ids(conn) - pre_ids:
            row = conn.execute("SELECT name, type FROM entities WHERE id = ?", (eid,)).fetchone()
            if row and row["type"] == "person":
                assert is_plausible_person_name(row["name"]), (
                    f"after {after}: new person {eid!r} has implausible name {row['name']!r}"
                )

    # 6) Correct-merge triple resolves to single entity (after dedup/merge)
    triple = conn.execute(
        "SELECT id FROM entities"
        " WHERE id IN ('merge-name-359', 'merge-handle-359', 'merge-email-359')"
    ).fetchall()
    if check_merge_triple:
        assert len(triple) == 1, (
            f"after {after}: merge triple should be 1 entity, got {len(triple)}"
        )
    else:
        assert len(triple) >= 1, f"after {after}: merge triple entities were all deleted"


def test_invariants_pipeline(invariant_store, tmp_path, monkeypatch):
    """Run extract -> prune -> dedup -> merge; assert invariants after each."""
    conn = invariant_store

    import patina.beliefs.extractor as _ext

    monkeypatch.setattr(_ext, "_call_claude", lambda *a, **kw: "")

    # --- extract (stubbed LLM, no unprocessed observations) ---
    pre = _entity_ids(conn)
    extract_beliefs(home=tmp_path)
    _assert_invariants(conn, after="extract", pre_ids=pre)

    # --- prune ---
    pre = _entity_ids(conn)
    prune_non_person_entities(conn)
    prune_slack_link_entities(conn)
    _assert_invariants(conn, after="prune", pre_ids=pre)

    # --- dedup ---
    pre = _entity_ids(conn)
    dedup_entities(conn)
    _assert_invariants(conn, after="dedup", pre_ids=pre, check_merge_triple=True)

    # --- merge (owner duplicate into owner) ---
    assert conn.execute("SELECT 1 FROM entities WHERE id = 'owner-dup-332'").fetchone(), (
        "owner-dup-332 should survive prune and dedup for the merge step"
    )
    pre = _entity_ids(conn)
    merge_entities(conn, "owner-332", "owner-dup-332")
    _assert_invariants(conn, after="merge", pre_ids=pre, check_merge_triple=True)
