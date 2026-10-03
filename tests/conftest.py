from __future__ import annotations

import json

import pytest

import patina.store as store_module
from patina.store import connect, get_db_path, init_db


@pytest.fixture
def db_path(tmp_path):
    path = get_db_path(tmp_path)
    init_db(path)
    return path


@pytest.fixture
def db_conn(db_path):
    conn = connect(db_path)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "DEFAULT_HOME", tmp_path)
    monkeypatch.setenv("PATINA_DEDUP_ALLOW_LIVE", "1")


def _seed_entity(conn, eid, etype, name, aliases=None, is_owner=0):
    now = "2025-01-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO entities"
        " (id, type, name, aliases, metadata, first_seen, last_seen, decay_rate, is_owner)"
        " VALUES (?, ?, ?, ?, '{}', ?, ?, 0.02, ?)",
        (eid, etype, name, json.dumps(aliases or []), now, now, is_owner),
    )


def _seed_claim(conn, cid, subject_id, predicate="role", obj="engineer"):
    now = "2025-01-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO claims"
        " (id, subject_id, predicate, object, confidence,"
        "  first_asserted, last_confirmed, decay_rate)"
        " VALUES (?, ?, ?, ?, 0.5, ?, ?, 0.02)",
        (cid, subject_id, predicate, obj, now, now),
    )


@pytest.fixture
def seeded_store(tmp_path):
    """In-memory-like store seeded with 8 edge-case entity shapes.

    Each shape is annotated with the issue number it covers.
    Returns a sqlite3.Connection with the full schema initialized.
    """
    path = get_db_path(tmp_path)
    init_db(path)
    conn = connect(path)

    # --- Shape 1: handle-named sender (#358) ---
    _seed_entity(conn, "handle-sender-358", "person", "jdoe_42")

    # --- Shape 2: W-prefixed Slack IDs (#363) ---
    _seed_entity(
        conn,
        "w-prefix-363",
        "person",
        "Kai Nakamura",
        aliases=["W0EXAMPLE1", "slack:W0EXAMPLE1"],
    )

    # --- Shape 3: overlapping aliases with distinct Slack IDs (#364) ---
    _seed_entity(
        conn,
        "alias-overlap-364-a",
        "person",
        "Ren Oshiro",
        aliases=["slack:U100", "ren.oshiro"],
    )
    _seed_entity(
        conn,
        "alias-overlap-364-b",
        "person",
        "Lina Petrova",
        aliases=["slack:U200", "ren.oshiro"],
    )

    # --- Shape 4: correct-merge full-name/handle/email triple (#359) ---
    _seed_entity(
        conn,
        "merge-name-359",
        "person",
        "Dana Kowalski",
        aliases=["slack:U300"],
    )
    _seed_entity(
        conn,
        "merge-handle-359",
        "person",
        "dkowalski",
        aliases=["slack:U300"],
    )
    _seed_entity(
        conn,
        "merge-email-359",
        "person",
        "dana.kowalski@example.com",
        aliases=["slack:U300"],
    )

    # --- Shape 5: description-saved-as-name (#346/#349) ---
    _seed_entity(
        conn,
        "desc-name-346",
        "person",
        "Head of Engineering at Acme Corp",
    )

    # --- Shape 6: owner duplicate under Slack ID (#332) ---
    _seed_entity(
        conn,
        "owner-332",
        "person",
        "Mika Tanaka",
        aliases=["U_OWNER332", "slack:U_OWNER332"],
        is_owner=1,
    )
    _seed_entity(
        conn,
        "owner-dup-332",
        "person",
        "U_OWNER332",
        aliases=["U_OWNER332"],
    )

    # --- Shape 7: Slack link markup saved as entity (#334) ---
    _seed_entity(
        conn,
        "link-markup-334",
        "reference",
        "https://github.com/org/repo|repo link",
    )

    # --- Shape 8: dangling claims (#333) ---
    _seed_entity(conn, "valid-entity-333", "person", "Yuki Arai")
    _seed_claim(conn, "claim-valid-333", "valid-entity-333")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")
    _seed_claim(conn, "claim-dangling-333", "nonexistent-entity-333")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")
    yield conn
    conn.close()
