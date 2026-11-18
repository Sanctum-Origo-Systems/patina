from __future__ import annotations

import json

import pytest

from patina.adapters._source_facts import (
    PARTICIPANT_KEYS,
    RECIPIENT_KEYS,
    STATE_KEY,
    get_fact,
    put_fact,
    render_facts,
)
from patina.graph import insert_observation
from patina.models import Observation, SourceFact, SourceFactState
from patina.store import connect

# Anonymized live shape: an Outlook item with an empty Cc list, a null To and
# no recipients key at all.
PAYLOAD = {
    "id": "AAMkExample01",
    "senders": ["Example, Jordan <jordan@example.invalid>"],
    "toRecipients": None,
    "ccRecipients": [],
    "subject": "",
    "preview": "The quick brown fox",
}


def _put(facts: dict, key: str, payload: dict, payload_key: str) -> None:
    put_fact(facts, key, payload.get(payload_key), present=payload_key in payload)


def test_empty_list_stores_empty_state_and_keeps_list():
    facts: dict = {}
    _put(facts, "cc", PAYLOAD, "ccRecipients")
    fact = get_fact(facts, "cc")
    assert fact == SourceFact(state=SourceFactState.EMPTY, value=[])
    assert isinstance(fact.value, list)
    assert facts["cc"] == []


def test_empty_string_stores_empty_state_and_keeps_string():
    facts: dict = {}
    _put(facts, "subject", PAYLOAD, "subject")
    fact = get_fact(facts, "subject")
    assert fact == SourceFact(state=SourceFactState.EMPTY, value="")
    assert isinstance(fact.value, str)
    assert facts["subject"] == ""


def test_none_stores_unavailable_with_no_value():
    facts: dict = {}
    _put(facts, "to", PAYLOAD, "toRecipients")
    fact = get_fact(facts, "to")
    assert fact == SourceFact(state=SourceFactState.UNAVAILABLE, value=None)
    assert "to" not in facts
    assert facts[STATE_KEY] == {"to": "unavailable"}


def test_absent_key_stores_nothing():
    facts: dict = {}
    _put(facts, "recipients", PAYLOAD, "recipients")
    assert facts == {}
    assert get_fact(facts, "recipients") is None


@pytest.mark.parametrize(
    "value",
    [["jordan@example.invalid"], "The quick brown fox", "Example, Jordan <jordan@example.invalid>"],
)
def test_non_empty_value_stores_present_unchanged(value):
    facts: dict = {}
    put_fact(facts, "sender_key", value, present=True)
    assert facts == {"sender_key": value}
    assert get_fact(facts, "sender_key") == SourceFact(state=SourceFactState.PRESENT, value=value)


def test_missing_and_unavailable_are_distinct():
    omitted: dict = {}
    put_fact(omitted, "to", None, present=False)
    explicit: dict = {}
    put_fact(explicit, "to", None, present=True)

    assert omitted == {}
    assert get_fact(omitted, "to") is None
    assert get_fact(explicit, "to").state is SourceFactState.UNAVAILABLE
    assert omitted != explicit


def test_later_value_replaces_earlier_state():
    facts: dict = {}
    put_fact(facts, "to", None, present=True)
    put_fact(facts, "to", [], present=True)
    assert get_fact(facts, "to") == SourceFact(state=SourceFactState.EMPTY, value=[])
    put_fact(facts, "to", ["jordan@example.invalid"], present=True)
    assert facts == {"to": ["jordan@example.invalid"]}


def test_legacy_call_still_omits_absent_values():
    facts: dict = {}
    for key, value in [("a", None), ("b", ""), ("c", []), ("d", "The quick brown fox")]:
        put_fact(facts, key, value)
    assert facts == {"d": "The quick brown fox"}


@pytest.mark.parametrize(
    ("sent", "rendered"),
    [
        ({}, "unknown"),  # nothing sent
        ({"to": None}, "unknown"),
        ({"cc": []}, "none"),  # empty Cc with To missing: an empty value was sent
        ({"to": None, "cc": []}, "unknown"),  # an unavailable To outweighs an empty Cc
        ({"to": [], "cc": ""}, "none"),
        ({"to": ["jordan@example.invalid"], "cc": None}, "jordan@example.invalid"),
    ],
)
def test_render_recipients_combines_states(sent, rendered):
    facts: dict = {}
    for key, value in sent.items():
        put_fact(facts, key, value, present=True)
    assert render_facts(facts, RECIPIENT_KEYS) == rendered


def test_render_facts_without_facts_is_unknown():
    assert render_facts(None, RECIPIENT_KEYS) == "unknown"
    assert render_facts({}, PARTICIPANT_KEYS) == "unknown"


def test_render_facts_shows_dict_entries_by_email_then_name():
    facts: dict = {}
    value = [{"email": "jordan@example.invalid", "name": "Jordan Example"}, {"name": "Café Team"}]
    put_fact(facts, "to", value, present=True)
    assert render_facts(facts, RECIPIENT_KEYS) == "jordan@example.invalid, Café Team"


def test_state_enum_has_exactly_three_values():
    assert {s.value for s in SourceFactState} == {"present", "unavailable", "empty"}


@pytest.mark.parametrize("bad", ["missing", "", "PRESENT", None])
def test_state_rejects_other_values(bad):
    with pytest.raises(ValueError):
        SourceFactState(bad)
    with pytest.raises(ValueError):
        SourceFact(state=bad, value="The quick brown fox")


def test_old_format_metadata_reads_back_as_present():
    old = {
        "message_id": "AAMkExample01",
        "sender_key": "Example, Jordan <jordan@example.invalid>",
        "to": ["jordan@example.invalid"],
    }
    stored = json.loads(json.dumps(old))
    for key, value in old.items():
        assert get_fact(stored, key) == SourceFact(state=SourceFactState.PRESENT, value=value)
    assert get_fact(stored, "cc") is None


def test_state_bearing_facts_round_trip_through_store(db_path):
    facts: dict = {}
    _put(facts, "message_id", PAYLOAD, "id")
    _put(facts, "sender_key", PAYLOAD, "senders")
    _put(facts, "to", PAYLOAD, "toRecipients")
    _put(facts, "cc", PAYLOAD, "ccRecipients")
    _put(facts, "subject", PAYLOAD, "subject")
    _put(facts, "recipients", PAYLOAD, "recipients")

    conn = connect(db_path)
    obs = Observation(
        id="obs-example-01",
        source="outlook_mcp_email",
        channel_id="email:conv-example-01",
        thread_id="conv-example-01",
        timestamp=1700000000.0,
        sender_entity_id=None,
        text="The quick brown fox",
        metadata={"source": facts},
    )
    insert_observation(conn, obs)
    row = conn.execute("SELECT metadata FROM observations WHERE id = ?", (obs.id,)).fetchone()
    stored = json.loads(row["metadata"])["source"]
    conn.close()

    assert get_fact(stored, "message_id") == SourceFact(SourceFactState.PRESENT, "AAMkExample01")
    assert get_fact(stored, "sender_key") == SourceFact(
        SourceFactState.PRESENT, ["Example, Jordan <jordan@example.invalid>"]
    )
    assert get_fact(stored, "to") == SourceFact(SourceFactState.UNAVAILABLE, None)
    assert get_fact(stored, "cc") == SourceFact(SourceFactState.EMPTY, [])
    assert get_fact(stored, "subject") == SourceFact(SourceFactState.EMPTY, "")
    assert get_fact(stored, "recipients") is None
    assert stored == facts
