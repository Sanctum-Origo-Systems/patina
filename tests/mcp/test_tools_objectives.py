from __future__ import annotations

from patina.mcp.tools_objectives import (
    objective_add,
    objective_list,
    objective_update,
)
from patina.priority.objectives import list_objectives


def test_objective_add_normalizes_targets(db_path):
    result = objective_add(
        "Ship Atlas",
        "atlas",
        participants=["Jordan.Example@Example.com ", "jordan.example@example.com"],
        customer_domains=["Example.com", ""],
    )

    [obj] = list_objectives()
    assert obj.participants == ["jordan.example@example.com"]
    assert obj.customer_domains == ["example.com"]
    assert 'participants: ["jordan.example@example.com"]' in result
    assert 'customer_domains: ["example.com"]' in result


def test_objective_add_without_targets_returns_empty_lists(db_path):
    result = objective_add("Ship Atlas", "atlas")

    [obj] = list_objectives()
    assert obj.participants == []
    assert obj.customer_domains == []
    assert "participants: []" in result
    assert "customer_domains: []" in result


def test_objective_update_only_customer_domains(db_path):
    objective_add(
        "Ship Atlas",
        "atlas, launch",
        participants=["jordan.example@example.com"],
        customer_domains=["example.com"],
    )
    [before] = list_objectives()

    result = objective_update(before.id, customer_domains=["Example.org"])

    [after] = list_objectives()
    assert after.label == "Ship Atlas"
    assert after.keywords == "atlas, launch"
    assert after.participants == ["jordan.example@example.com"]
    assert after.customer_domains == ["example.org"]
    assert 'customer_domains: ["example.org"]' in result
    assert 'participants: ["jordan.example@example.com"]' in result


def test_objective_update_unknown_id(db_path):
    result = objective_update("ffffffff", participants=["e1"])
    assert "No objective updated" in result


def test_objective_list_includes_targets(db_path):
    objective_add("Ship Atlas", "atlas", customer_domains=["example.com"])

    result = objective_list()
    assert "**Ship Atlas**" in result
    assert "participants: []" in result
    assert 'customer_domains: ["example.com"]' in result
