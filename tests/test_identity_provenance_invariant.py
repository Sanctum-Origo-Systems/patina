"""Alias-subset-of-net-added invariant over the e2e identity scenarios (#510).

Every string in ``entities.aliases`` must have a net 'added' row in
``entity_alias_provenance`` for that entity, and an alias whose latest row is
'removed' must not be in ``entities.aliases``. The store is built through the
same ingest paths as ``tests/test_identity_e2e.py``; all names are fictitious
and every store lives under ``tmp_path``.
"""

from __future__ import annotations

import json

from patina.ingest import ingest_live
from patina.maintenance import (
    dedup_entities,
    repair_multi_identity_names,
    split_dn_sink,
    store_snapshot_token,
)
from patina.store import connect, get_db_path, init_db, record_alias_provenance
from tests.conftest import _seed_identity_entity
from tests.test_identity_e2e import (
    _GUID,
    _LOOKBACK_DAYS,
    _OWNER_CONFIG,
    DANA_SLACK_ID,
    DN_CASEY,
    SINK_ALIASES,
    SINK_ID,
    TRUNC_DN,
    FakeSlackPort,
    _build_store,
    _holder,
    _slack,
)

# --- Invariant helpers ---


def _net_state(conn) -> dict[tuple[str, str], str]:
    """(entity_id, alias) -> 'added' if net added, else 'removed'.

    Net added: the latest row by created_at is 'added', or 'added' rows
    outnumber 'removed' rows.
    """
    rows = conn.execute(
        "SELECT entity_id, alias, action FROM entity_alias_provenance ORDER BY created_at, rowid"
    ).fetchall()
    latest: dict[tuple[str, str], str] = {}
    balance: dict[tuple[str, str], int] = {}
    for r in rows:
        key = (r["entity_id"], r["alias"])
        latest[key] = r["action"]
        balance[key] = balance.get(key, 0) + (1 if r["action"] == "added" else -1)
    return {
        key: "added" if latest[key] == "added" or balance[key] > 0 else "removed" for key in latest
    }


def _alias_provenance_violations(conn) -> list[tuple[str, str]]:
    """(entity_id, alias) pairs in entities.aliases without a net 'added' provenance row."""
    net = _net_state(conn)
    violations = []
    for r in conn.execute("SELECT id, aliases FROM entities ORDER BY id").fetchall():
        for alias in json.loads(r["aliases"] or "[]"):
            if net.get((r["id"], alias)) != "added":
                violations.append((r["id"], alias))
    return violations


def _stripped_but_present(conn) -> list[tuple[str, str]]:
    """(entity_id, alias) pairs whose latest provenance row is 'removed' yet still held."""
    latest: dict[tuple[str, str], str] = {}
    for r in conn.execute(
        "SELECT entity_id, alias, action FROM entity_alias_provenance ORDER BY created_at, rowid"
    ).fetchall():
        latest[(r["entity_id"], r["alias"])] = r["action"]
    held = {
        (r["id"], a)
        for r in conn.execute("SELECT id, aliases FROM entities").fetchall()
        for a in json.loads(r["aliases"] or "[]")
    }
    return sorted(k for k, action in latest.items() if action == "removed" and k in held)


def _check(conn) -> None:
    assert _alias_provenance_violations(conn) == []
    assert _stripped_but_present(conn) == []


def _aliases(conn, entity_id: str) -> list[str]:
    row = conn.execute("SELECT aliases FROM entities WHERE id = ?", (entity_id,)).fetchone()
    return json.loads(row["aliases"] or "[]")


def _actions(conn, entity_id: str, alias: str) -> list[str]:
    return [
        r["action"]
        for r in conn.execute(
            "SELECT action FROM entity_alias_provenance"
            " WHERE entity_id = ? AND alias = ? ORDER BY created_at, rowid",
            (entity_id, alias),
        ).fetchall()
    ]


def _provenance_rows(conn) -> list[tuple]:
    return [
        tuple(r)
        for r in conn.execute("SELECT * FROM entity_alias_provenance ORDER BY rowid").fetchall()
    ]


def _all_aliases(conn) -> dict[str, list[str]]:
    return {
        r["id"]: json.loads(r["aliases"] or "[]")
        for r in conn.execute("SELECT id, aliases FROM entities ORDER BY id").fetchall()
    }


def _seed_with_provenance(conn, eid: str, name: str, aliases: list[str]) -> None:
    """Seed a legacy entity plus the 'unknown' rows the provenance backfill gives it."""
    _seed_identity_entity(conn, eid, name, aliases=aliases)
    for alias in aliases:
        record_alias_provenance(conn, eid, alias, adapter="unknown", action="added")


# --- Scenarios ---


def test_ingest_of_single_slack_message_holds_invariant(tmp_path):
    """A Slack message from Dana Brook leaves every alias with a net 'added' row."""
    (tmp_path / "config.yaml").write_text(_OWNER_CONFIG)
    db_path = get_db_path(tmp_path)
    init_db(db_path)

    ingest_live(
        port=FakeSlackPort(
            [_slack(1, DANA_SLACK_ID, "Dana Brook", "The quick brown fox", "D0000000001")]
        ),
        source="slack_mcp",
        home=tmp_path,
        lookback_days=_LOOKBACK_DAYS,
    )

    conn = connect(db_path)
    try:
        dana = _holder(conn, DANA_SLACK_ID)
        assert _aliases(conn, dana)
        assert _alias_provenance_violations(conn) == []
        _check(conn)
    finally:
        conn.close()


def test_e2e_ingest_holds_invariant(tmp_path, monkeypatch):
    """The full e2e Slack + Outlook ingest over a legacy DN sink holds the invariant."""
    store = _build_store(tmp_path, monkeypatch, sink_aliases=SINK_ALIASES)
    try:
        _check(store.conn)
    finally:
        store.conn.close()


def test_dedup_merge_moves_provenance_to_surviving_entity(tmp_path, monkeypatch):
    store = _build_store(tmp_path, monkeypatch, sink_aliases=SINK_ALIASES)
    conn = store.conn
    try:
        before = _all_aliases(conn)
        report = dedup_entities(conn, dry_run=False, snapshot_token=store_snapshot_token(conn))
        assert report["merges"], "fixture must produce a dedup merge"

        _check(conn)
        net = _net_state(conn)
        for merge in report["merges"]:
            keep, drop = merge["keep_id"], merge["drop_id"]
            assert conn.execute("SELECT 1 FROM entities WHERE id = ?", (drop,)).fetchone() is None
            kept = set(_aliases(conn, keep))
            for alias in before[drop]:
                assert alias in kept
                assert net.get((keep, alias)) == "added", (keep, alias)
    finally:
        conn.close()


def test_split_dn_sink_holds_invariant(tmp_path, monkeypatch):
    store = _build_store(tmp_path, monkeypatch, sink_aliases=SINK_ALIASES)
    conn = store.conn
    try:
        dedup_entities(conn, dry_run=False, snapshot_token=store_snapshot_token(conn))
        report = split_dn_sink(conn, SINK_ID, dry_run=False)
        assert any(r["target_id"] for r in report["routes"]), "fixture must route a DN to a person"

        _check(conn)
        sink_aliases = set(_aliases(conn, SINK_ID))
        net = _net_state(conn)
        for route in report["routes"]:
            dn = route["dn"]
            assert dn not in sink_aliases
            assert _actions(conn, SINK_ID, dn)[-1] == "removed"
            # Unmatched DNs become the name of a new reference entity, not an alias
            if route["target_id"]:
                assert dn in _aliases(conn, route["target_id"])
                assert net.get((route["target_id"], dn)) == "added", (route["target_id"], dn)
    finally:
        conn.close()


def test_repair_multi_identity_names_holds_invariant(tmp_path, monkeypatch):
    store = _build_store(tmp_path, monkeypatch, sink_aliases=SINK_ALIASES)
    conn = store.conn
    try:
        dn_other = f"{TRUNC_DN}/CN=RECIPIENTS/CN={_GUID}-QHALE"
        _seed_with_provenance(conn, "legacy-named-sink", "cvale", ["cvale", DN_CASEY, dn_other])
        _seed_with_provenance(
            conn, "legacy-named-sink-2", "U0000000B4", ["U0000000B4", "U0000000B5"]
        )
        conn.commit()
        _check(conn)

        dedup_entities(conn, dry_run=False, snapshot_token=store_snapshot_token(conn))
        split_dn_sink(conn, SINK_ID, dry_run=False)
        _check(conn)

        # dry-run: no alias or provenance writes
        aliases_before = _all_aliases(conn)
        rows_before = _provenance_rows(conn)
        preview = repair_multi_identity_names(conn, dry_run=True)
        assert _all_aliases(conn) == aliases_before
        assert _provenance_rows(conn) == rows_before

        report = repair_multi_identity_names(conn, dry_run=False)
        assert report == preview
        assert report["entities"], "fixture must leave entities to repair"

        _check(conn)
        stripped_any = False
        for item in report["entities"]:
            eid = item["id"]
            after = set(_aliases(conn, eid))
            for alias in set(aliases_before[eid]) - set(item["aliases"]):
                stripped_any = True
                assert alias not in after
                assert _actions(conn, eid, alias)[-1] == "removed", (eid, alias)
        assert stripped_any, "repair must strip at least one alias"
    finally:
        conn.close()


# --- Negative control ---


def test_alias_without_provenance_is_reported(tmp_path, monkeypatch):
    """An alias written straight into entities.aliases is a violation naming entity and alias."""
    store = _build_store(tmp_path, monkeypatch, sink_aliases=SINK_ALIASES)
    conn = store.conn
    try:
        dana = _holder(conn, DANA_SLACK_ID)
        conn.execute(
            "UPDATE entities SET aliases = json_insert(aliases, '$[#]', 'dana.b@example.net')"
            " WHERE id = ?",
            (dana,),
        )
        conn.commit()

        assert (dana, "dana.b@example.net") in _alias_provenance_violations(conn)
    finally:
        conn.close()


def test_stripped_alias_still_held_is_reported(db_conn):
    """An alias whose latest row is 'removed' but is still in entities.aliases is reported."""
    _seed_with_provenance(db_conn, "ent-river", "River Lane", ["rlane"])
    record_alias_provenance(db_conn, "ent-river", "rlane", adapter="repair", action="removed")
    db_conn.commit()

    assert _alias_provenance_violations(db_conn) == [("ent-river", "rlane")]
    assert _stripped_but_present(db_conn) == [("ent-river", "rlane")]
