from __future__ import annotations

import json

from patina.priority.objectives import (
    Objective,
    add_objective,
    get_objective,
    list_objectives,
    remove_objective,
    update_objective,
)


def _format_targets(obj: Objective) -> str:
    return (
        f"  participants: {json.dumps(obj.participants)}\n"
        f"  customer_domains: {json.dumps(obj.customer_domains)}"
    )


def objective_list() -> str:
    """List current priorities and objectives."""
    objs = list_objectives()
    if not objs:
        return "No objectives set."
    lines = []
    for obj in objs:
        kw = f" (keywords: {obj.keywords})" if obj.keywords else ""
        lines.append(f"- [{obj.id[:8]}] **{obj.label}**{kw}\n{_format_targets(obj)}")
    return "\n".join(lines)


def objective_add(
    label: str,
    keywords: str = "",
    participants: list[str] | None = None,
    customer_domains: list[str] | None = None,
) -> str:
    """Add a new priority objective with optional keywords for matching.

    participants: entity IDs or email addresses engaged in the objective.
    customer_domains: customer domain names (e.g. example.com).
    """
    obj = add_objective(
        label, keywords, participants=participants, customer_domains=customer_domains
    )
    return f"Added objective [{obj.id[:8]}] {obj.label}\n{_format_targets(obj)}"


def objective_update(
    obj_id: str,
    label: str | None = None,
    keywords: str | None = None,
    participants: list[str] | None = None,
    customer_domains: list[str] | None = None,
) -> str:
    """Update an objective by ID (or ID prefix). Omitted fields are left unchanged;
    a given participants or customer_domains list replaces the stored one."""
    updated = update_objective(
        obj_id,
        label=label,
        keywords=keywords,
        participants=participants,
        customer_domains=customer_domains,
    )
    obj = get_objective(obj_id) if updated else None
    if obj is None:
        return f"No objective updated matching '{obj_id}'"
    return f"Updated objective [{obj.id[:8]}] {obj.label}\n{_format_targets(obj)}"


def objective_remove(obj_id: str) -> str:
    """Remove an objective by ID."""
    if remove_objective(obj_id):
        return f"Removed objective [{obj_id[:8]}]"
    return f"No objective found matching '{obj_id}'"


def register(mcp):
    mcp.tool()(objective_list)
    mcp.tool()(objective_add)
    mcp.tool()(objective_update)
    mcp.tool()(objective_remove)
