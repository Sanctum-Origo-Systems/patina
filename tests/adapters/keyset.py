"""Key-set extraction for live-shape drift checks (#688).

A key set maps each dotted key path in a JSON payload to its JSON type name.
Nested object keys are joined with ``.`` and array elements are marked with
``[]``, so ``{"recipients": [{"address": "a@example.invalid"}]}`` becomes::

    {"recipients": "array", "recipients[]": "object", "recipients[].address": "string"}

Only key names and type names are emitted, never values.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

RECORDED_DIR = Path(__file__).parent / "recorded_keysets"

JSON_TYPES = frozenset({"null", "boolean", "number", "string", "object", "array"})


def json_type(value: Any) -> str:
    """The JSON type name of a decoded JSON value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def _put(keyset: dict[str, str], path: str, type_name: str) -> None:
    existing = keyset.setdefault(path, type_name)
    if existing != type_name:
        raise ValueError(f"conflicting JSON types at {path!r}: {existing} vs {type_name}")


def _walk(value: Any, path: str, keyset: dict[str, str]) -> None:
    if path:
        _put(keyset, path, json_type(value))
    if isinstance(value, dict):
        for key, child in value.items():
            _walk(child, f"{path}.{key}" if path else key, keyset)
    elif isinstance(value, list):
        for child in value:
            _walk(child, f"{path}[]", keyset)


def extract_keyset(payload: Any) -> dict[str, str]:
    """Map every dotted key path in ``payload`` to its JSON type name.

    The root itself has no path: a root object yields bare keys and a root
    array yields ``[]``-prefixed paths. Raises ``ValueError`` when one path
    carries two different types.
    """
    keyset: dict[str, str] = {}
    _walk(payload, "", keyset)
    return keyset


def extract_items_keyset(items: Iterable[Any]) -> dict[str, str]:
    """Merge the key sets of each item, as an adapter sees one item at a time."""
    keyset: dict[str, str] = {}
    for item in items:
        for path, type_name in extract_keyset(item).items():
            _put(keyset, path, type_name)
    return keyset


def load_recorded(name: str) -> dict[str, str]:
    """Load ``recorded_keysets/<name>.json``."""
    return json.loads((RECORDED_DIR / f"{name}.json").read_text())
