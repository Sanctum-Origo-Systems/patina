from __future__ import annotations

from patina.priority.objectives import (
    add_objective,
    get_objective,
    list_objectives,
    normalize_customer_domains,
    normalize_participants,
    remove_objective,
    update_objective,
)
from patina.store import connect, get_db_path


def test_add_and_list(tmp_path):
    obj = add_objective("Ship v2", "release, deploy, ship", home=tmp_path)
    assert obj.label == "Ship v2"
    assert obj.active is True

    objs = list_objectives(home=tmp_path)
    assert len(objs) == 1
    assert objs[0].id == obj.id


def test_remove_sets_inactive(tmp_path):
    obj = add_objective("Temp", "temp", home=tmp_path)
    assert remove_objective(obj.id, home=tmp_path) is True

    active = list_objectives(active_only=True, home=tmp_path)
    assert len(active) == 0

    all_objs = list_objectives(active_only=False, home=tmp_path)
    assert len(all_objs) == 1
    assert all_objs[0].active is False


def test_update_changes_fields(tmp_path):
    obj = add_objective("Original", "a, b", home=tmp_path)
    update_objective(obj.id, label="Updated", keywords="x, y", home=tmp_path)

    objs = list_objectives(home=tmp_path)
    assert objs[0].label == "Updated"
    assert objs[0].keywords == "x, y"


def test_list_active_only_filters(tmp_path):
    add_objective("Active", "a", home=tmp_path)
    obj2 = add_objective("Inactive", "b", home=tmp_path)
    remove_objective(obj2.id, home=tmp_path)

    active = list_objectives(active_only=True, home=tmp_path)
    assert len(active) == 1
    assert active[0].label == "Active"


def test_new_objective_reads_back_target_lists(tmp_path):
    add_objective(
        "Renew pilot deal",
        "renewal",
        participants=["Jordan.Example@Example.com", "e1"],
        customer_domains=["Example.com"],
        home=tmp_path,
    )

    [obj] = list_objectives(home=tmp_path)
    assert obj.participants == ["jordan.example@example.com", "e1"]
    assert obj.customer_domains == ["example.com"]
    assert all(isinstance(v, str) for v in obj.participants + obj.customer_domains)


def test_migrated_objective_reads_back_empty_lists(tmp_path):
    conn = connect(get_db_path(tmp_path))
    conn.executescript(
        """CREATE TABLE objectives (
               id TEXT PRIMARY KEY,
               label TEXT NOT NULL,
               keywords TEXT NOT NULL DEFAULT '',
               active INTEGER NOT NULL DEFAULT 1,
               created_at TEXT NOT NULL,
               updated_at TEXT NOT NULL
           );
           INSERT INTO objectives VALUES
               ('bbbb000000000001', 'Legacy goal', 'legacy', 1, '', '');"""
    )
    conn.close()

    [obj] = list_objectives(home=tmp_path)
    assert obj.label == "Legacy goal"
    assert obj.keywords == "legacy"
    assert obj.participants == []
    assert obj.customer_domains == []


def test_normalize_target_values():
    assert normalize_participants(
        [" Jordan.Example@Example.com ", "jordan.example@example.com"]
    ) == ["jordan.example@example.com"]
    assert normalize_participants([" EntityId1 ", "", "  "]) == ["EntityId1"]
    assert normalize_customer_domains(["Example.com", "", " example.COM ", "example.org"]) == [
        "example.com",
        "example.org",
    ]


def test_update_targets_by_prefix_leaves_other_fields(tmp_path):
    obj = add_objective(
        "Pilot", "pilot", participants=["jordan.example@example.com"], home=tmp_path
    )

    assert update_objective(obj.id[:8], customer_domains=["Example.org"], home=tmp_path)

    got = get_objective(obj.id, home=tmp_path)
    assert got.label == "Pilot"
    assert got.keywords == "pilot"
    assert got.participants == ["jordan.example@example.com"]
    assert got.customer_domains == ["example.org"]


def test_update_unknown_id_returns_false(tmp_path):
    add_objective("Pilot", "pilot", home=tmp_path)
    assert update_objective("ffffffff", participants=["e1"], home=tmp_path) is False
