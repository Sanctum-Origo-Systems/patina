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


# Keys rendered together as one "Recipients", "Participants" or "Attendees" line.
RECIPIENT_KEYS = ("to", "cc", "recipients")
PARTICIPANT_KEYS = ("participants",)
ATTENDEE_KEYS = ("attendees",)


def _display(value) -> str:
    if isinstance(value, dict):
        return str(value.get("email") or value.get("name") or value)
    return str(value)


def render_facts(facts: dict | None, keys: tuple[str, ...]) -> str:
    """Display text for the facts at ``keys`` taken together.

    Present values are joined with ``", "``. With none present, any
    ``unavailable`` key gives ``"unknown"``, else any ``empty`` key gives
    ``"none"``. Missing keys (or no ``facts`` at all) give ``"unknown"``, so
    ``"none"`` is shown only when the source sent an empty value.
    """
    found = [f for f in (get_fact(facts or {}, k) for k in keys) if f is not None]
    values: list[str] = []
    for fact in found:
        if fact.state is SourceFactState.PRESENT:
            items = fact.value if isinstance(fact.value, list) else [fact.value]
            values.extend(_display(v) for v in items)
    if values:
        return ", ".join(values)
    states = {f.state for f in found}
    if SourceFactState.EMPTY in states and SourceFactState.UNAVAILABLE not in states:
        return "none"
    return "unknown"
