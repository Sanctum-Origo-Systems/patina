"""End-to-end identity fixture suite: ingest -> resolve -> dedup -> split -> repair (#512).

The store is built only through the real Slack (``ingest_live``), Outlook email
and Outlook calendar (``OutlookMcpAdapter`` under source ``outlook_mcp_email``)
ingest paths, on top of a legacy DN sink seeded with ``_seed_identity_entity``.
All people, IDs, DNs and message text are fictitious; no network is used.
"""

from __future__ import annotations

import json
import re
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import patina
import patina.ingest as ingest_module
from patina.adapters.outlook_mcp import OutlookMcpAdapter
from patina.cli import app
from patina.graph import _is_multi_identity, normalize_name, resolve_entity_id
from patina.ingest import ingest_live
from patina.maintenance import (
    dedup_entities,
    find_dedup_candidates,
    repair_multi_identity_names,
    split_dn_sink,
    store_snapshot_token,
)
from patina.models import ChatMessage
from patina.owner import get_owner_entity_id, get_owner_identifiers, normalize_alias
from patina.store import connect, get_db_path, init_db
from tests.conftest import _assert_identity_invariants, _seed_claim, _seed_identity_entity

# --- Fictitious identities ---

OWNER_SLACK_ID = "U0000000A0"
DANA_SLACK_ID = "U0000000A1"
RILEY_SLACK_ID = "U0000000A2"

TRUNC_DN = "/O=EXAMPLEORG/OU=ADMIN GROUP"
_GUID = "0123456789abcdef0123456789abcdef"
DN_DANA = f"{TRUNC_DN}/CN=RECIPIENTS/CN={_GUID}-DBROOK"
DN_RILEY = f"{TRUNC_DN}/CN=RECIPIENTS/CN={_GUID}-RSTONE"
DN_CASEY = f"{TRUNC_DN}/CN=RECIPIENTS/CN={_GUID}-CVALE"

# Exchange DNs with the "(FYDIBOHF23SPDLT)" suffix: ingest names their senders
# after the truncated DN before the "(", so unrelated people share that name.
PAREN_TRUNC_DN = "/O=EXAMPLEORG/OU=EXCHANGE ADMINISTRATIVE GROUP"
_PAREN_PREFIX = f"{PAREN_TRUNC_DN} (FYDIBOHF23SPDLT)/CN=RECIPIENTS/CN={_GUID}"
PAREN_DN_DANA = f"{_PAREN_PREFIX}-DBROOK"
PAREN_DN_RILEY = f"{_PAREN_PREFIX}-RSTONE"

SINK_ID = "legacy-dn-sink"
# Legacy DN sink: three members' full DNs, two former colleagues' Slack IDs and
# a member email (Riley's) that it absorbed before identity precedence landed.
SINK_ALIASES = [
    TRUNC_DN,
    DN_DANA,
    DN_RILEY,
    DN_CASEY,
    "U0000000B1",
    "slack:U0000000B1",
    "U0000000B2",
    "slack:U0000000B2",
    "riley.stone@example.com",
]

_OWNER_CONFIG = (
    "owner:\n"
    f"  user_ids: [{OWNER_SLACK_ID}]\n"
    "  display_names: [Sam Ortiz]\n"
    "  emails: [sam.ortiz@example.com]\n"
)

_T0 = 1_790_000_000.0
_LOOKBACK_DAYS = 36500


def _iso(offset: int) -> str:
    return datetime.fromtimestamp(_T0 + offset, UTC).isoformat()


def _slack(offset: int, user_id: str, user_name: str, text: str, channel: str) -> ChatMessage:
    return ChatMessage(
        user_id=user_id,
        user_name=user_name,
        text=text,
        timestamp=_T0 + offset,
        channel_id=channel,
    )


def _email(offset: int, from_email: str, from_name: str = "", senders=()) -> dict:
    return {
        "senders": list(senders),
        "from": {"email": from_email, "name": from_name},
        "receivedDateTime": _iso(offset),
        "subject": "Status",
        "bodyPreview": "The quick brown fox",
        "conversationId": f"conv-{offset}",
    }


def _event(offset: int, organizer) -> dict:
    return {
        "meetingId": f"M{offset}",
        "subject": "Planning",
        "start": _iso(offset),
        "end": _iso(offset + 1800),
        "organizer": organizer,
        "attendees": [{"email": "sam.ortiz@example.com"}],
    }


SLACK_MESSAGES = [
    _slack(1, OWNER_SLACK_ID, "Sam Ortiz", f"Morning <@{DANA_SLACK_ID}>", "D0000000001"),
    _slack(2, DANA_SLACK_ID, "Dana Brook", f"Hi <@{OWNER_SLACK_ID}>", "D0000000001"),
    _slack(3, DANA_SLACK_ID, "@dbrook", "The quick brown fox", "D0000000001"),
    _slack(4, RILEY_SLACK_ID, "Riley Stone", "The lazy dog", "D0000000002"),
    _slack(5, RILEY_SLACK_ID, "rstone", f"Looping in <@{DANA_SLACK_ID}>", "D0000000002"),
]

OUTLOOK_EMAILS = [
    # DN-only senders: resolve to the legacy sink through its full-DN aliases
    _email(10, DN_DANA, senders=[DN_DANA]),
    _email(11, DN_RILEY, senders=[DN_RILEY]),
    _email(12, DN_CASEY, senders=[DN_CASEY]),
    # DN-only senders with the "(...)" suffix: one entity per DN, both named
    # after the same truncated DN (#459/#468)
    _email(13, PAREN_DN_DANA, senders=[PAREN_DN_DANA]),
    _email(14, PAREN_DN_RILEY, senders=[PAREN_DN_RILEY]),
    _email(30, "riley.stone@example.com", "Riley Stone"),
    _email(31, "dana.brook@example.com", "Dana Brook"),
    _email(33, "sam.ortiz@example.com", "Sam Ortiz"),
]

OUTLOOK_EVENTS = [
    # Riley's email is held only by the sink at this point: lands on the sink (#485)
    _event(20, "riley.stone@example.com"),
    # Bare handle while Dana holds "@dbrook" (#496)
    _event(21, "dbrook"),
    # Before Dana's email is known: creates an email-named duplicate for dedup
    _event(22, {"email": "dana.brook@example.com"}),
    _event(24, {"email": "sam.ortiz@example.com"}),
]


# --- Fake transports: the adapters and ingest code under them are real ---


class FakeSlackPort:
    """ChatPort returning canned Slack messages."""

    def __init__(self, messages: list[ChatMessage]) -> None:
        self._messages = messages

    @property
    def platform(self) -> str:
        return "slack_mcp"

    def list_dm_messages(self, since: float) -> list[ChatMessage]:
        return list(self._messages)

    def list_mentions(self, since: float) -> list[ChatMessage]:
        return []

    def list_channel_messages(self, channel_id: str, since: float) -> list[ChatMessage]:
        return []

    def get_thread(self, channel_id: str, thread_id: str) -> list[ChatMessage]:
        return []


class FakeOutlookBridge:
    """McpSyncBridge stand-in serving raw Outlook MCP payloads to OutlookMcpAdapter."""

    def __init__(self, emails: list[dict], events: list[dict]) -> None:
        self._payloads = {"email_inbox": {"emails": emails}, "calendar_view": events}

    def call_tool(self, name: str, arguments: dict | None = None, **kwargs):
        text = json.dumps(self._payloads[name])
        return SimpleNamespace(isError=False, content=[SimpleNamespace(text=text)])

    def close(self) -> None:
        pass


# --- Entity-write provenance guard ---

_ENTITY_WRITE_RE = re.compile(
    r"^\s*(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)\s+entities\b",
    re.IGNORECASE,
)
_PATINA_SRC = Path(patina.__file__).resolve().parent


class EntityWriteRecorder:
    """Flags writes to the entities table that bypass ingest.

    Allowed writers are code inside the ``patina`` package (ingest and the
    graph/owner helpers it calls) and ``_seed_identity_entity``.
    """

    def __init__(self) -> None:
        self.allowed = 0
        self.violations: list[str] = []

    def attach(self, conn):
        conn.set_trace_callback(self._trace)
        return conn

    def _trace(self, sql: str) -> None:
        if not _ENTITY_WRITE_RE.match(sql):
            return
        caller = sys._getframe(1)
        path = Path(caller.f_code.co_filename).resolve()
        if path.is_relative_to(_PATINA_SRC) or caller.f_code.co_name == "_seed_identity_entity":
            self.allowed += 1
        else:
            self.violations.append(f"{path.name}:{caller.f_code.co_name}: {sql.split()[0]}")


def _no_network(*args, **kwargs):
    raise AssertionError("identity e2e suite attempted a network connection")


def _build_store(home: Path, monkeypatch, *, sink_aliases: list[str]) -> SimpleNamespace:
    monkeypatch.setattr(socket.socket, "connect", _no_network)

    recorder = EntityWriteRecorder()
    real_connect = ingest_module.connect
    monkeypatch.setattr(ingest_module, "connect", lambda p: recorder.attach(real_connect(p)))

    (home / "config.yaml").write_text(_OWNER_CONFIG)
    db_path = get_db_path(home)
    assert db_path == home / "store.db"
    init_db(db_path)
    conn = recorder.attach(connect(db_path))

    _seed_identity_entity(conn, SINK_ID, TRUNC_DN, aliases=sink_aliases)
    conn.commit()

    ingest_live(
        port=FakeSlackPort(SLACK_MESSAGES),
        source="slack_mcp",
        home=home,
        lookback_days=_LOOKBACK_DAYS,
    )
    ingest_live(
        port=OutlookMcpAdapter(FakeOutlookBridge(OUTLOOK_EMAILS, OUTLOOK_EVENTS)),
        source="outlook_mcp_email",
        home=home,
        lookback_days=_LOOKBACK_DAYS,
    )
    conn.set_trace_callback(None)

    return SimpleNamespace(
        conn=conn,
        home=home,
        recorder=recorder,
        owner_identifiers=get_owner_identifiers(home),
    )


@pytest.fixture
def identity_store(tmp_path, monkeypatch):
    store = _build_store(tmp_path, monkeypatch, sink_aliases=SINK_ALIASES)
    store.owner_id = get_owner_entity_id(store.conn)
    store.dana_id = _holder(store.conn, DANA_SLACK_ID)
    store.riley_id = _holder(store.conn, RILEY_SLACK_ID)
    yield store
    store.conn.close()


# --- Helpers ---


def _aliases(conn, entity_id: str) -> list[str]:
    row = conn.execute("SELECT aliases FROM entities WHERE id = ?", (entity_id,)).fetchone()
    return json.loads(row["aliases"] or "[]")


def _holder(conn, token: str) -> str:
    """The single entity holding *token* as an alias."""
    holders = [
        r["id"]
        for r in conn.execute("SELECT id, aliases FROM entities").fetchall()
        if token in json.loads(r["aliases"] or "[]")
    ]
    assert len(holders) == 1, f"{token!r} held by {holders}"
    return holders[0]


def _check(store) -> None:
    _assert_identity_invariants(store.conn, store.owner_identifiers)


def _entity_state(conn) -> dict[str, tuple]:
    return {
        r["id"]: (r["type"], r["name"], frozenset(json.loads(r["aliases"] or "[]")), r["is_owner"])
        for r in conn.execute("SELECT id, type, name, aliases, is_owner FROM entities")
    }


def _obs_senders(conn) -> dict[str, str | None]:
    return {
        r["id"]: r["sender_entity_id"]
        for r in conn.execute("SELECT id, sender_entity_id FROM observations")
    }


def _full_snapshot(conn) -> dict:
    """Every row the maintenance operations can touch, for no-write checks."""
    return {
        "entities": [
            tuple(r) for r in conn.execute("SELECT * FROM entities ORDER BY id").fetchall()
        ],
        "observations": [
            tuple(r)
            for r in conn.execute(
                "SELECT id, sender_entity_id, metadata, processed FROM observations ORDER BY id"
            ).fetchall()
        ],
        "claims": [tuple(r) for r in conn.execute("SELECT * FROM claims ORDER BY id").fetchall()],
    }


def _expected_after_dedup(entities: dict, senders: dict, report: dict) -> tuple[dict, dict]:
    """Apply a dedup report's merges to a snapshot the way merge_entities does."""
    ents = {k: list(v) for k, v in entities.items()}
    senders = dict(senders)
    for merge in report["merges"]:
        keep, drop = merge["keep_id"], merge["drop_id"]
        dropped = ents.pop(drop)
        ents[keep][2] = frozenset(ents[keep][2] | dropped[2] | {dropped[1]})
        senders = {o: keep if s == drop else s for o, s in senders.items()}
    return {k: tuple(v) for k, v in ents.items()}, senders


def _expected_entities_after_split(entities: dict, report: dict) -> tuple[dict, set]:
    """Apply a split report's routes; returns (existing entities, added (type, name) set)."""
    ents = {k: list(v) for k, v in entities.items()}
    sink = report["entity_id"]
    added = set()
    for route in report["routes"]:
        ents[sink][2] = ents[sink][2] - {route["dn"]}
        if route["target_id"]:
            ents[route["target_id"]][2] = ents[route["target_id"]][2] | {route["dn"]}
        else:
            added.add(("reference", route["dn"]))
    return {k: tuple(v) for k, v in ents.items()}, added


def _expected_after_repair(entities: dict, report: dict) -> dict:
    ents = {k: list(v) for k, v in entities.items()}
    for item in report["entities"]:
        ents[item["id"]][1] = item["new_name"]
        ents[item["id"]][2] = frozenset(item["aliases"])
    return {k: tuple(v) for k, v in ents.items()}


def _merge_pairs(report: dict) -> list[tuple]:
    return [(m["keep_id"], m["drop_id"], m["observations_moved"]) for m in report["merges"]]


# --- Fixture provenance ---


def test_store_built_only_through_ingest(identity_store):
    """Every entity write while building the main scenario came from ingest or the seed helper."""
    assert identity_store.recorder.violations == []
    assert identity_store.recorder.allowed > 0
    sources = {
        r["source"] for r in identity_store.conn.execute("SELECT DISTINCT source FROM observations")
    }
    assert sources == {"slack_mcp", "outlook_mcp_email"}
    channels = [
        r["channel_id"] for r in identity_store.conn.execute("SELECT channel_id FROM observations")
    ]
    assert any(c.startswith("email:") for c in channels)
    assert any(c.startswith("calendar:") for c in channels)


def test_entity_write_recorder_flags_direct_inserts(db_conn):
    """The provenance guard catches rows inserted directly into the entities table."""
    recorder = EntityWriteRecorder()
    recorder.attach(db_conn)

    _seed_identity_entity(db_conn, "seeded", "Dana Brook")
    assert recorder.violations == []

    db_conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen)"
        " VALUES ('direct', 'person', 'Riley Stone', '[]', '{}', '', '')"
    )
    db_conn.execute("UPDATE entities SET aliases = '[\"rstone\"]' WHERE id = 'seeded'")
    assert len(recorder.violations) == 2
    assert all("test_identity_e2e.py" in v for v in recorder.violations)


# --- Invariants ---


def test_pipeline_holds_invariants_after_every_step(identity_store):
    """ingest -> resolve -> dedup preview -> split dry-run -> repair dry-run -> commit."""
    store, conn = identity_store, identity_store.conn
    home = str(store.home)
    runner = CliRunner()

    _check(store)

    # resolve
    assert resolve_entity_id(conn, "Dana Brook", [DANA_SLACK_ID]) == store.dana_id
    assert resolve_entity_id(conn, "rstone", [f"slack:{RILEY_SLACK_ID}"]) == store.riley_id
    assert resolve_entity_id(conn, "riley.stone@example.com") == store.riley_id
    assert resolve_entity_id(conn, TRUNC_DN) is None
    _check(store)

    dedup_entities(conn, dry_run=True)
    _check(store)

    split_dn_sink(conn, SINK_ID, dry_run=True)
    _check(store)

    repair_multi_identity_names(conn, dry_run=True)
    _check(store)

    # commit
    result = runner.invoke(app, ["entity", "dedup", "--confirm", "--home", home])
    assert result.exit_code == 0, result.output
    assert "Dedup: 1 group(s), 1 merge(s)" in result.output
    _check(store)

    split = split_dn_sink(conn, SINK_ID, dry_run=False)
    assert split["observations_routed"] > 0
    _check(store)

    result = runner.invoke(app, ["entity", "repair-multi-identity", "--confirm", "--home", home])
    assert result.exit_code == 0, result.output
    _check(store)


@pytest.mark.parametrize(
    "corruption,match",
    [
        ("UPDATE entities SET is_owner = 0", "exactly 1 owner"),
        ("UPDATE entities SET is_owner = 1 WHERE id = :dana", "exactly 1 owner"),
        (
            "UPDATE entities SET aliases = json_insert(aliases, '$[#]', 'sam.ortiz@example.com')"
            " WHERE id = :dana",
            "owner identifier",
        ),
        ("dangling", "dangling claim"),
        (
            "UPDATE entities SET aliases = json_insert(aliases, '$[#]', 'slack:U0000000A1')"
            " WHERE id = :riley",
            "Slack ID",
        ),
        ("UPDATE entities SET name = 'dbrook' WHERE id = :sink", "named after member identifier"),
    ],
    ids=[
        "no-owner",
        "two-owners",
        "owner-identifier-leak",
        "dangling-claim",
        "shared-slack-id",
        "member-named-sink",
    ],
)
def test_invariant_helper_detects_corruption(identity_store, corruption, match):
    """Each invariant check fires on a deliberately corrupted copy of the store."""
    conn = identity_store.conn
    _check(identity_store)

    if corruption == "dangling":
        conn.execute("PRAGMA foreign_keys=OFF")
        _seed_claim(conn, "claim-dangling", "no-such-entity")
        conn.commit()
        conn.execute("PRAGMA foreign_keys=ON")
    else:
        params = {"dana": identity_store.dana_id, "riley": identity_store.riley_id, "sink": SINK_ID}
        conn.execute(corruption, {k: v for k, v in params.items() if f":{k}" in corruption})
        conn.commit()

    with pytest.raises(AssertionError, match=match):
        _check(identity_store)


# --- Preview equals commit ---


def test_dry_runs_preview_exactly_what_commit_writes(identity_store):
    conn = identity_store.conn

    # dedup_entities
    before = _full_snapshot(conn)
    ents, senders = _entity_state(conn), _obs_senders(conn)
    preview = dedup_entities(conn, dry_run=True)
    assert _full_snapshot(conn) == before
    assert preview["entities_merged"] == 1

    committed = dedup_entities(conn, dry_run=False, snapshot_token=store_snapshot_token(conn))
    assert _merge_pairs(committed) == _merge_pairs(preview)
    expected_ents, expected_senders = _expected_after_dedup(ents, senders, preview)
    assert _entity_state(conn) == expected_ents
    assert _obs_senders(conn) == expected_senders

    # split_dn_sink
    before = _full_snapshot(conn)
    ents, senders = _entity_state(conn), _obs_senders(conn)
    preview = split_dn_sink(conn, SINK_ID, dry_run=True)
    assert _full_snapshot(conn) == before
    assert preview["routable_observations"] > 0

    committed = split_dn_sink(conn, SINK_ID, dry_run=False)
    assert committed["routes"] == preview["routes"]
    after = _entity_state(conn)
    expected_ents, expected_added = _expected_entities_after_split(ents, preview)
    assert {k: v for k, v in after.items() if k in ents} == expected_ents
    assert {(v[0], v[1]) for k, v in after.items() if k not in ents} == expected_added

    moved = {o: s for o, s in _obs_senders(conn).items() if s != senders[o]}
    assert len(moved) == committed["observations_routed"] == preview["routable_observations"]
    assert all(senders[o] == SINK_ID for o in moved)
    left_on_sink = sum(1 for s in _obs_senders(conn).values() if s == SINK_ID)
    assert left_on_sink == sum(preview["unroutable_by_source"].values())

    # repair_multi_identity_names
    before = _full_snapshot(conn)
    ents = _entity_state(conn)
    preview = repair_multi_identity_names(conn, dry_run=True)
    assert _full_snapshot(conn) == before

    committed = repair_multi_identity_names(conn, dry_run=False)
    assert committed == preview
    assert _entity_state(conn) == _expected_after_repair(ents, preview)


def test_repair_preview_equals_commit_on_member_named_sink(tmp_path, monkeypatch):
    """Legacy sinks named after a member: the repair preview is exactly what commit writes."""
    store = _build_store(tmp_path, monkeypatch, sink_aliases=SINK_ALIASES)
    conn = store.conn
    dn_other = f"{TRUNC_DN}/CN=RECIPIENTS/CN={_GUID}-QHALE"
    _seed_identity_entity(conn, "legacy-named-sink", "cvale", aliases=[DN_CASEY, dn_other])
    _seed_identity_entity(conn, "legacy-named-sink-2", "U0000000B4", aliases=["U0000000B5"])
    conn.commit()

    before = _full_snapshot(conn)
    ents = _entity_state(conn)
    preview = repair_multi_identity_names(conn, dry_run=True)
    assert _full_snapshot(conn) == before
    assert {e["id"] for e in preview["entities"]} == {"legacy-named-sink", "legacy-named-sink-2"}

    committed = repair_multi_identity_names(conn, dry_run=False)
    assert committed == preview
    assert _entity_state(conn) == _expected_after_repair(ents, preview)
    conn.close()


def test_repair_skips_person_carrying_stale_foreign_slack_id_522(tmp_path, monkeypatch):
    """#522: a single person holding one stale foreign Slack ID is not renamed to a sink label."""
    store = _build_store(tmp_path, monkeypatch, sink_aliases=SINK_ALIASES)
    conn = store.conn
    # user_b's own ID is U0000000C2; U0000000C1 is user_c's and reached A via a misroute.
    _seed_identity_entity(conn, "stale-a", "user_b", aliases=["user_b", "U0000000C2", "U0000000C1"])
    _seed_identity_entity(conn, "stale-c", "user_c", aliases=["user_c", "U0000000C1"])
    conn.commit()
    assert _is_multi_identity("user_b", _aliases(conn, "stale-a"))

    before = _full_snapshot(conn)
    preview = repair_multi_identity_names(conn, dry_run=True)
    assert _full_snapshot(conn) == before
    assert not {"stale-a", "stale-c"} & {e["id"] for e in preview["entities"]}
    assert [(s["id"], s["reason"]) for s in preview["skipped"]] == [("stale-a", "stale_foreign_id")]
    assert all("stripped_aliases" in e for e in preview["entities"])

    state = _entity_state(conn)
    committed = repair_multi_identity_names(conn, dry_run=False)
    assert committed == preview
    after = _entity_state(conn)
    assert after["stale-a"] == state["stale-a"]
    assert after["stale-c"] == state["stale-c"]
    assert resolve_entity_id(conn, "user_b") == "stale-a"
    conn.close()


# --- Named cases ---


def test_at_handle_and_bare_handle_resolve_to_one_entity_496(identity_store):
    """#496: "@dbrook" (Slack) and "dbrook" (calendar organizer) are one entity."""
    conn, dana = identity_store.conn, identity_store.dana_id

    assert resolve_entity_id(conn, "@dbrook") == dana
    assert resolve_entity_id(conn, "dbrook") == dana
    assert {"@dbrook", "dbrook"} <= set(_aliases(conn, dana))

    holders = [
        r["id"]
        for r in conn.execute("SELECT id, name, aliases FROM entities").fetchall()
        if any(
            normalize_name(normalize_alias(t)) == "dbrook"
            for t in [r["name"], *json.loads(r["aliases"] or "[]")]
        )
    ]
    assert holders == [dana]

    calendar_row = conn.execute(
        "SELECT sender_entity_id FROM observations WHERE channel_id = 'calendar:M21'"
    ).fetchone()
    assert calendar_row["sender_entity_id"] == dana


def test_truncated_dn_shared_by_unrelated_people_never_merges_459_468(identity_store):
    """#459/#468: a truncated DN (no CN=) is never an identifier."""
    conn = identity_store.conn
    paren_dana = _holder(conn, PAREN_DN_DANA)
    paren_riley = _holder(conn, PAREN_DN_RILEY)
    unrelated = {paren_dana, paren_riley}

    # Two people's DN-only emails left two entities sharing the truncated DN
    rows = conn.execute(
        "SELECT id, name, aliases FROM entities WHERE id IN (?, ?)", (paren_dana, paren_riley)
    ).fetchall()
    assert len(rows) == 2
    for r in rows:
        assert r["name"] == PAREN_TRUNC_DN
        assert PAREN_TRUNC_DN in json.loads(r["aliases"])

    assert resolve_entity_id(conn, PAREN_TRUNC_DN) is None
    assert resolve_entity_id(conn, PAREN_TRUNC_DN, [PAREN_TRUNC_DN]) is None
    assert resolve_entity_id(conn, TRUNC_DN, [TRUNC_DN]) is None

    for group in find_dedup_candidates(conn)["candidates"]:
        members = {group["keep"]["id"]} | {d["id"] for d in group["drop"]}
        assert not unrelated <= members, group
        assert not group["match_identifier"].upper().startswith("/O=")

    preview = dedup_entities(conn, dry_run=True)
    committed = dedup_entities(conn, dry_run=False, snapshot_token=store_snapshot_token(conn))
    for report in (preview, committed):
        dropped = {m["drop_id"] for m in report["merges"]}
        assert not dropped & unrelated
    remaining = {r["id"] for r in conn.execute("SELECT id FROM entities")}
    assert unrelated <= remaining


def test_calendar_rows_from_outlook_mcp_email_route_in_split_485(identity_store):
    """#485: calendar rows ingested under source outlook_mcp_email route off the sink."""
    conn, riley = identity_store.conn, identity_store.riley_id
    calendar_sql = (
        "SELECT id, sender_entity_id FROM observations"
        " WHERE source = 'outlook_mcp_email' AND channel_id LIKE 'calendar:%'"
    )
    before = {r["id"]: r["sender_entity_id"] for r in conn.execute(calendar_sql)}
    on_sink = {o for o, s in before.items() if s == SINK_ID}
    assert on_sink, "fixture must leave a calendar row on the sink"

    preview = split_dn_sink(conn, SINK_ID, dry_run=True)
    assert preview["routable_observations"] >= len(on_sink)

    split_dn_sink(conn, SINK_ID, dry_run=False)
    after = {r["id"]: r["sender_entity_id"] for r in conn.execute(calendar_sql)}
    assert after.keys() == before.keys()
    assert {after[o] for o in on_sink} == {riley}
    assert SINK_ID not in after.values()


def test_handle_named_person_aliased_by_full_name_merges_obs_2026_10_27_2(identity_store):
    """OBS-2026-10-27-2 (#527): one person split across a handle- and a full-name entity.

    Shape A ("jdoe" sends on Slack while "Jane Doe" holds "@jdoe") merges into the
    full name; Shape B ("Quinn" vs "Quinn Hale", no shared ID) is review only.
    """
    store, conn = identity_store, identity_store.conn
    jdoe_slack_id = "U0000000C1"
    ingest_live(
        port=FakeSlackPort(
            [_slack(40, jdoe_slack_id, "jdoe", "The quick brown fox", "D0000000003")]
        ),
        source="slack_mcp",
        home=store.home,
        lookback_days=_LOOKBACK_DAYS,
    )
    jdoe = _holder(conn, f"slack:{jdoe_slack_id}")
    assert conn.execute("SELECT name FROM entities WHERE id = ?", (jdoe,)).fetchone()[0] == "jdoe"
    _seed_identity_entity(conn, "jane-doe", "Jane Doe", aliases=["@jdoe", "Doe, Jane"])
    _seed_claim(conn, "claim-jdoe", jdoe)
    _seed_identity_entity(conn, "quinn", "Quinn")
    _seed_identity_entity(conn, "quinn-hale", "Quinn Hale")
    conn.commit()
    _check(store)

    before = _full_snapshot(conn)
    ents, senders = _entity_state(conn), _obs_senders(conn)
    preview = dedup_entities(conn, dry_run=True)
    assert _full_snapshot(conn) == before

    shape_a = [m for m in preview["merges"] if m["drop_id"] == jdoe]
    assert len(shape_a) == 1
    assert shape_a[0]["keep_id"] == "jane-doe"
    assert shape_a[0]["shape"] == "handle_alias_of_person"
    review = {r["id"]: r for r in preview["needs_review"]}
    assert review["quinn"]["reason"] == "first_name_only"
    assert review["quinn"]["shape"] == "first_name_only"
    assert not [
        m for m in preview["merges"] if {"quinn", "quinn-hale"} & {m["keep_id"], m["drop_id"]}
    ]

    committed = dedup_entities(conn, dry_run=False, snapshot_token=store_snapshot_token(conn))
    assert _merge_pairs(committed) == _merge_pairs(preview)
    expected_ents, expected_senders = _expected_after_dedup(ents, senders, preview)
    assert _entity_state(conn) == expected_ents
    assert _obs_senders(conn) == expected_senders
    _check(store)

    assert jdoe not in _entity_state(conn)
    assert jdoe not in _obs_senders(conn).values()
    claim = conn.execute("SELECT subject_id FROM claims WHERE id = 'claim-jdoe'").fetchone()
    assert claim["subject_id"] == "jane-doe"
    assert resolve_entity_id(conn, "jdoe") == "jane-doe"
    assert {"quinn", "quinn-hale"} <= set(_entity_state(conn))


@pytest.mark.parametrize(
    "shared",
    ["U0000000C2", "avery.lund@example.com", f"{TRUNC_DN}/CN=RECIPIENTS/CN={_GUID}-ALUND"],
    ids=["slack-id", "email", "full-dn"],
)
def test_capitalized_first_name_with_shared_id_still_merges_542(identity_store, shared):
    """#542: the first_name_only label guard leaves the shared-identifier merge intact.

    "Avery" and "Avery Lund" share a Slack ID, email or DN and merge; the product
    name "Slack" and the handle "alund" go to review without the label.
    """
    store, conn = identity_store, identity_store.conn
    _seed_identity_entity(conn, "avery", "Avery", aliases=[shared])
    _seed_identity_entity(conn, "avery-lund", "Avery Lund", aliases=[shared])
    _seed_identity_entity(conn, "slack-bot", "Slack")
    _seed_identity_entity(conn, "slack-hale", "Slack Hale")
    _seed_identity_entity(conn, "alund", "alund")
    _seed_identity_entity(conn, "alund-hale", "Alund Hale")
    conn.commit()

    preview = dedup_entities(conn, dry_run=True)
    avery = [m for m in preview["merges"] if m["drop_id"] == "avery"]
    assert len(avery) == 1
    assert avery[0]["keep_id"] == "avery-lund"
    assert avery[0]["shape"] == "first_name_only"
    review = {r["id"]: r for r in preview["needs_review"]}
    assert "avery" not in review
    for eid in ("slack-bot", "alund"):
        assert review[eid]["reason"] == "name match"
        assert "shape" not in review[eid]

    committed = dedup_entities(conn, dry_run=False, snapshot_token=store_snapshot_token(conn))
    assert _merge_pairs(committed) == _merge_pairs(preview)
    _check(store)
    remaining = set(_entity_state(conn))
    assert "avery" not in remaining
    assert {"avery-lund", "slack-bot", "alund"} <= remaining


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "OBS-2026-10-26-1: a DN sink still holding a member handle captures that member "
        "at ingest and keeps the handle through dedup, split and repair"
    ),
)
def test_dn_sink_holding_member_handle_releases_it_obs_2026_10_26_1(tmp_path, monkeypatch):
    store = _build_store(tmp_path, monkeypatch, sink_aliases=[*SINK_ALIASES, "rstone"])
    conn = store.conn

    dedup_entities(conn, dry_run=False, snapshot_token=store_snapshot_token(conn))
    split_dn_sink(conn, SINK_ID, dry_run=False)
    repair_multi_identity_names(conn, dry_run=False)

    riley = _holder(conn, RILEY_SLACK_ID)
    sink_aliases = _aliases(conn, SINK_ID)
    try:
        assert riley != SINK_ID, "Riley's Slack identity was absorbed by the DN sink"
        assert not _is_multi_identity(TRUNC_DN, _aliases(conn, riley))
        assert not [a for a in sink_aliases if normalize_name(normalize_alias(a)) == "rstone"]
        assert resolve_entity_id(conn, "rstone") == riley
    finally:
        conn.close()
