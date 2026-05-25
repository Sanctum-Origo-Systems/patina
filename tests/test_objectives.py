from __future__ import annotations

from patina.priority.objectives import (
    add_objective,
    list_objectives,
    remove_objective,
    update_objective,
)


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
