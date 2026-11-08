"""Shared helper for the ``metadata["source"]`` source-facts contract (see docs/app.md)."""

from __future__ import annotations


def put_fact(facts: dict, key: str, value) -> None:
    """Set ``facts[key]`` only when the source sent a value (omit-if-absent)."""
    if value is None or value == "" or value == []:
        return
    facts[key] = value
