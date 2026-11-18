"""Shared helper for the ``metadata["source"]`` source-facts contract (see docs/app.md)."""

from __future__ import annotations

from patina.models import SourceFact, SourceFactState

# Reserved key holding ``{fact_key: state}`` for facts whose state is not
# ``present``. A fact with no entry here is ``present`` (this is also how rows
# written before states existed read back).
STATE_KEY = "_state"


def _is_empty(value) -> bool:
    return value == "" or value == []


def put_fact(facts: dict, key: str, value, *, present: bool | None = None) -> None:
    """Record ``key`` in ``facts``.

    With ``present`` unset (legacy callers), set ``facts[key]`` only when the
    source sent a value (omit-if-absent).

    With ``present`` given, the caller says whether the source payload had the
    key at all, so missing and unavailable stay apart:

    - ``present=False``: missing, nothing is stored.
    - ``None``: ``unavailable``, no value is stored.
    - ``""`` or ``[]``: ``empty``, the value is kept as given.
    - anything else: ``present``, the value is kept as given.
    """
    if present is None:
        if value is None or _is_empty(value):
            return
        facts[key] = value
        return
    if not present:
        return

    if value is None:
        state = SourceFactState.UNAVAILABLE
        facts.pop(key, None)
    else:
        state = SourceFactState.EMPTY if _is_empty(value) else SourceFactState.PRESENT
        facts[key] = value

    states = facts.get(STATE_KEY, {})
    if state is SourceFactState.PRESENT:
        states.pop(key, None)
    else:
        states[key] = state.value
    if states:
        facts[STATE_KEY] = states
    else:
        facts.pop(STATE_KEY, None)


def get_fact(facts: dict, key: str) -> SourceFact | None:
    """Read ``key`` back from ``facts``; ``None`` when the source left it out."""
    state = facts.get(STATE_KEY, {}).get(key)
    if state is not None:
        return SourceFact(state=state, value=facts.get(key))
    if key in facts:
        return SourceFact(state=SourceFactState.PRESENT, value=facts[key])
    return None
