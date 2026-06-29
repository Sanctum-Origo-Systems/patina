from __future__ import annotations

from patina.priority.objectives import (
    add_objective,
    list_objectives,
    remove_objective,
)


def objective_list() -> str:
    """List current priorities and objectives."""
    objs = list_objectives()
    if not objs:
        return "No objectives set."
    lines = []
    for obj in objs:
        kw = f" (keywords: {obj.keywords})" if obj.keywords else ""
        lines.append(f"- [{obj.id[:8]}] **{obj.label}**{kw}")
    return "\n".join(lines)


def objective_add(label: str, keywords: str = "") -> str:
    """Add a new priority objective with optional keywords for matching."""
    obj = add_objective(label, keywords)
    return f"Added objective [{obj.id[:8]}] {obj.label}"


def objective_remove(obj_id: str) -> str:
    """Remove an objective by ID."""
    if remove_objective(obj_id):
        return f"Removed objective [{obj_id[:8]}]"
    return f"No objective found matching '{obj_id}'"


def register(mcp):
    mcp.tool()(objective_list)
    mcp.tool()(objective_add)
    mcp.tool()(objective_remove)
