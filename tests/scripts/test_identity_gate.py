"""Tests for scripts/identity_gate.py — fixtures, loader and scratch copy (#584)."""

from __future__ import annotations

import json
import re

import pytest
import scripts.identity_gate as gate
from scripts.identity_gate import (
    FIXTURES_DIR,
    build_seed_store,
    load_fixtures,
    scratch_copy,
    sha256_file,
)

from patina.graph import _is_multi_identity, identifier_type
from patina.owner import normalize_alias
from patina.store import connect, init_db, run_pending_migrations

_VALID_SLACK_ID = re.compile(r"^[UW](?=[A-Z0-9]*\d)[A-Z0-9]{8,10}$")
# Any token shaped like a Slack user ID, valid or not.
_SLACK_ID_LIKE = re.compile(r"(?<![A-Za-z0-9])[UW][A-Z0-9]{4,}(?![A-Za-z0-9])")

_FICTITIOUS_NAMES = {"Jordan Example", "Casey Sample", "Riley Placeholder"}
_FICTITIOUS_HANDLES = {"jordan.example"}
_ADAPTERS = {"slack_live", "slack_mcp", "outlook_mcp", "imap"}


@pytest.fixture
def fixtures():
    return load_fixtures()


@pytest.fixture
def seed_store(tmp_path):
    return build_seed_store(tmp_path / "seed.db")


def _fixture_texts() -> list[str]:
    return [p.read_text() for p in sorted(FIXTURES_DIR.glob("*.json"))]


def _schema(db_path):
    conn = connect(db_path)
    try:
        rows = conn.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [tuple(r) for r in rows]
    finally:
        conn.close()


def _dump(db_path) -> list[str]:
    conn = connect(db_path)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


class TestLoader:
    def test_builds_real_schema(self, tmp_path, seed_store):
        ref = tmp_path / "ref.db"
        init_db(ref)
        conn = connect(ref)
        try:
            run_pending_migrations(conn)
        finally:
            conn.close()

        assert _schema(seed_store) == _schema(ref)

    def test_migrations_applied(self, tmp_path, seed_store):
        ref = tmp_path / "ref.db"
        init_db(ref)
        conn = connect(ref)
        try:
            run_pending_migrations(conn)
            expected = {r["name"] for r in conn.execute("SELECT name FROM migrations")}
        finally:
            conn.close()

        conn = connect(seed_store)
        try:
            applied = {r["name"] for r in conn.execute("SELECT name FROM migrations")}
        finally:
            conn.close()
        assert expected
        assert applied == expected

    def test_entity_and_alias_counts_match_seed(self, fixtures, seed_store):
        conn = connect(seed_store)
        try:
            rows = conn.execute("SELECT id, aliases FROM entities").fetchall()
        finally:
            conn.close()

        seed = fixtures["entities"]
        assert len(rows) == len(seed)
        assert {r["id"] for r in rows} == {e["id"] for e in seed}
        stored_aliases = sum(len(json.loads(r["aliases"])) for r in rows)
        assert stored_aliases == sum(len(e["aliases"]) for e in seed)

    def test_aliases_round_trip(self, fixtures, seed_store):
        conn = connect(seed_store)
        try:
            stored = {
                r["id"]: (r["name"], json.loads(r["aliases"]))
                for r in conn.execute("SELECT id, name, aliases FROM entities")
            }
        finally:
            conn.close()
        for ent in fixtures["entities"]:
            assert stored[ent["id"]] == (ent["name"], ent["aliases"])


class TestFixtures:
    def test_every_slack_id_is_valid(self):
        found = set()
        for text in _fixture_texts():
            found.update(_SLACK_ID_LIKE.findall(text))
        assert {"U0JORDAN01", "U0CASEY001", "W0SINK0001"} <= found
        invalid = sorted(t for t in found if not _VALID_SLACK_ID.match(t))
        assert invalid == []

    def test_slack_id_fields_are_valid(self, fixtures):
        ids = []
        for ent in fixtures["entities"]:
            ids += [
                normalize_alias(a)
                for a in ent["aliases"]
                if identifier_type(normalize_alias(a)) == "slack_id" or a.startswith("slack:")
            ]
        for msg in fixtures["messages"]:
            if msg["adapter"].startswith("slack"):
                ids.append(msg["user_id"])
            if "sender_slack_id" in msg["metadata"]:
                ids.append(msg["metadata"]["sender_slack_id"])
        assert ids
        assert all(_VALID_SLACK_ID.match(i) for i in ids), ids

    def test_one_message_per_adapter(self, fixtures):
        assert {m["adapter"] for m in fixtures["messages"]} == _ADAPTERS

    def test_production_shaped_metadata(self, fixtures):
        for msg in fixtures["messages"]:
            meta = msg["metadata"]
            assert {"channel_name", "reactions"} <= set(meta), msg["case"]
            if msg["adapter"].startswith("slack"):
                assert meta["sender_slack_id"] == msg["user_id"], msg["case"]
            else:
                assert "sender_slack_id" not in meta, msg["case"]
                assert msg["channel_id"].startswith("email:"), msg["case"]

    def test_expected_entities_exist(self, fixtures):
        ids = {e["id"] for e in fixtures["entities"]}
        for msg in fixtures["messages"]:
            assert msg["expected_entity_id"] in ids, msg["case"]

    def test_sink_is_multi_identity_and_alone_holds_its_slack_id(self, fixtures):
        ents = {e["id"]: e for e in fixtures["entities"]}
        sink = ents["ent-sink"]
        assert _is_multi_identity(sink["name"], sink["aliases"])
        dns = {a for a in sink["aliases"] if identifier_type(a) == "dn"}
        assert len(dns) == 2
        sink_ids = {
            normalize_alias(a)
            for a in sink["aliases"]
            if identifier_type(normalize_alias(a)) == "slack_id"
        }
        assert sink_ids == {"W0SINK0001"}
        others = [e for eid, e in ents.items() if eid != "ent-sink"]
        for e in others:
            assert not sink_ids & {normalize_alias(a) for a in e["aliases"]}

    def test_single_people_hold_handle_or_email(self, fixtures):
        kinds = set()
        for e in fixtures["entities"]:
            if e["id"] == "ent-sink":
                continue
            assert not _is_multi_identity(e["name"], e["aliases"])
            kinds.update(identifier_type(normalize_alias(a)) for a in e["aliases"])
        assert {"handle", "email"} <= kinds

    def test_sink_slack_id_carries_member_handle(self, fixtures):
        ents = {e["id"]: e for e in fixtures["entities"]}
        (msg,) = [
            m for m in fixtures["messages"] if m["case"] == "sink_slack_id_with_member_handle"
        ]
        assert msg["user_id"] == "W0SINK0001"
        handle = msg["user_name"]
        assert identifier_type(handle) == "handle"
        holders = [
            eid
            for eid, e in ents.items()
            if handle in {normalize_alias(a).lstrip("@") for a in e["aliases"]}
        ]
        assert holders == ["ent-jordan"]

    def test_name_only_competes_with_identifier(self, fixtures):
        ents = {e["id"]: e for e in fixtures["entities"]}
        (msg,) = [m for m in fixtures["messages"] if m["case"] == "name_only_vs_identifier"]
        name_holders = [eid for eid, e in ents.items() if e["name"] == msg["user_name"]]
        id_holders = [eid for eid, e in ents.items() if msg["user_id"] in e["aliases"]]
        assert identifier_type(msg["user_id"]) == "email"
        assert len(name_holders) == 1 and len(id_holders) == 1
        assert name_holders != id_holders
        name_only = ents[name_holders[0]]
        assert all(identifier_type(a) == "display_name" for a in name_only["aliases"])
        assert msg["expected_entity_id"] == id_holders[0]

    def test_only_fictitious_identities(self, fixtures):
        for e in fixtures["entities"]:
            for token in [e["name"], *e["aliases"]]:
                clean = normalize_alias(token)
                kind = identifier_type(clean)
                if kind == "handle" or clean.startswith("@"):
                    assert clean.lstrip("@") in _FICTITIOUS_HANDLES, token
                elif kind == "display_name":
                    assert clean in _FICTITIOUS_NAMES, token
                elif kind == "email":
                    assert clean.endswith("@example.com"), token
                elif kind == "dn" or clean.startswith("/O="):
                    assert clean.startswith("/O=EXAMPLEORG/"), token
                else:
                    assert kind == "slack_id", token
        for msg in fixtures["messages"]:
            name = msg["user_name"]
            if name and "," in name:
                last, first = (p.strip() for p in name.split(",", 1))
                name = f"{first} {last}"
            assert name is None or name in _FICTITIOUS_NAMES | _FICTITIOUS_HANDLES, msg["case"]
        for text in _fixture_texts():
            for email in re.findall(r"[\w.+-]+@[\w.-]+", text):
                domain = email.split("@", 1)[1]
                assert domain == "example.com" or domain.endswith(".example.com"), email


class TestScratchCopy:
    def test_copy_has_same_rows_and_source_unchanged(self, tmp_path, seed_store):
        before = sha256_file(seed_store)
        dest_dir = tmp_path / "scratch"
        dest_dir.mkdir()

        copy = scratch_copy(seed_store, dest_dir)

        assert copy == dest_dir / "store.db"
        assert sha256_file(seed_store) == before
        assert _dump(copy) == _dump(seed_store)

    def test_default_dest_is_temp_path(self, seed_store):
        copy = scratch_copy(seed_store)
        assert copy != seed_store
        assert copy.parent.name.startswith("patina-identity-gate-")
        assert _dump(copy) == _dump(seed_store)

    def test_default_source_is_home_store(self, tmp_path):
        # conftest points DEFAULT_HOME at tmp_path.
        source = build_seed_store(tmp_path / "store.db")
        copy = scratch_copy()
        assert _dump(copy) == _dump(source)

    def test_source_opened_read_only(self, seed_store):
        before = sha256_file(seed_store)
        seed_store.chmod(0o444)
        try:
            copy = scratch_copy(seed_store)
        finally:
            seed_store.chmod(0o644)
        assert sha256_file(seed_store) == before
        assert _dump(copy) == _dump(seed_store)

    def test_scratch_writes_do_not_touch_source(self, seed_store):
        before = sha256_file(seed_store)
        copy = scratch_copy(seed_store)
        conn = connect(copy)
        try:
            conn.execute("DELETE FROM entities")
            conn.commit()
        finally:
            conn.close()
        assert sha256_file(seed_store) == before

    def test_fails_when_source_hash_changes(self, seed_store, monkeypatch):
        digests = iter(["aaa", "bbb"])
        monkeypatch.setattr(gate, "sha256_file", lambda _path: next(digests))
        with pytest.raises(RuntimeError, match="changed"):
            scratch_copy(seed_store)

    def test_missing_source_raises_and_is_not_created(self, tmp_path):
        missing = tmp_path / "nope" / "store.db"
        with pytest.raises(FileNotFoundError):
            scratch_copy(missing)
        assert not missing.exists()
