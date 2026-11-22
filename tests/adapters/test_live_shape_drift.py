"""Live-shape drift: fixtures vs recorded key sets vs declared adapter reads (#688).

Each recorded key set in ``recorded_keysets/`` is the item-level shape a tool
returns. The drift check fails when a declared live read is missing from the
recorded set, when the fixture carries a key the recorded set lacks, or when a
recorded key is absent from the fixture. Fallback reads cover payload shapes
the live tool never sends, so the recorded set need not carry them (#707).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from patina.adapters._mcp_client import parse_json_content, parse_outlook_content
from patina.adapters.outlook_mcp import _unwrap_email_list
from tests.adapters.keyset import (
    JSON_TYPES,
    RECORDED_DIR,
    extract_items_keyset,
    extract_keyset,
    load_recorded,
)
from tests.adapters.test_outlook_mcp import LIVE_CALENDAR_VIEW_ITEM
from tests.adapters.test_slack_mcp import FIXTURES_MESSAGES_DICT, FIXTURES_MESSAGES_LIST

# Hand-written key paths each adapter reads off the live tool's items; every
# one must be in the recorded shape. Keep in step with the adapters by hand;
# never derive from adapter source.
LIVE_READS = {
    "email_inbox": [
        "conversationId",
        "topic",
        "senders",
        "recipients",
        "lastDeliveryTime",
        "preview",
        "itemIds[].id",
        "itemClasses",
    ],
    "calendar_view": [
        "meetingId",
        "subject",
        "start",
        "end",
        "organizer.email",
        "organizer.name",
    ],
    "get_messages": [
        "user",
        "text",
        "ts",
        "channel_id",
        "channel_name",
        "reactions",
    ],
}

# Key paths each adapter also reads for payload shapes the live tool never
# sends, each with why. The recorded shape need not carry these.
FALLBACK_READS = {
    "email_inbox": {
        "id": "Graph-style message id; live items key on conversationId and itemIds[].id",
        "subject": "Graph-style subject; live items carry topic",
        "from.email": "Graph-style sender; live items carry senders",
        "from.name": "Graph-style sender; live items carry senders",
        "toRecipients[].email": "Graph-style recipients; live items carry recipients",
        "toRecipients[].name": "Graph-style recipients; live items carry recipients",
        "receivedDateTime": "Graph-style timestamp; live items carry lastDeliveryTime",
        "bodyPreview": "Graph-style preview; live items carry preview",
    },
    "calendar_view": {},
    "get_messages": {
        "members": "participants, read only when present; no live get_messages row carries it",
    },
}

RECORDED_FILES = {
    "email_inbox": "email_inbox",
    "calendar_view": "calendar_view",
    "get_messages": "slack_get_messages",
}

# Fictitious repro of the live ``email_inbox`` item shape (OBS-2026-11-20-1):
# conversation-grouped, ``itemIds`` as objects with ``changeKey``, no Graph keys.
LIVE_INBOX_ITEM = {
    "conversationId": "AAQkExampleConv1=",
    "topic": "The quick brown fox — café",
    "senders": ["Example, Jordan"],
    "recipients": ["Brook, Dana", "Müller, Avery"],
    "lastDeliveryTime": "2026-11-19T11:40:14-06:00",
    "preview": "Jumps over the lazy dog.",
    "unreadCount": 1,
    "hasAttachments": False,
    "messageCount": 1,
    "itemClasses": ["IPM.Note"],
    "itemIds": [{"id": "AAkALgExampleItem1=", "changeKey": "CQAAAA=="}],
}

_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[\])*(\.[A-Za-z_][A-Za-z0-9_]*(\[\])*)*$")


def _result(text: str) -> SimpleNamespace:
    return SimpleNamespace(isError=False, content=[SimpleNamespace(text=text)])


def _outlook_inbox_items(*payloads: str) -> list:
    return [
        item
        for payload in payloads
        for item in _unwrap_email_list(parse_outlook_content(_result(payload)))
    ]


def _slack_message_items(*payloads: str) -> list:
    items: list = []
    for payload in payloads:
        raw = parse_json_content(_result(payload))
        items.extend(raw if isinstance(raw, list) else raw.get("messages", []))
    return items


def _fixture_keyset(tool: str) -> dict[str, str]:
    if tool == "email_inbox":
        items = _outlook_inbox_items(json.dumps([LIVE_INBOX_ITEM]))
    elif tool == "calendar_view":
        items = [LIVE_CALENDAR_VIEW_ITEM]
    else:
        items = _slack_message_items(FIXTURES_MESSAGES_LIST, FIXTURES_MESSAGES_DICT)
    return extract_items_keyset(items)


def assert_no_drift(
    tool: str, *, reads: list[str], recorded: dict[str, str], fixture: dict[str, str]
) -> None:
    """Fail naming ``tool`` and every drifted key path."""
    problems = [f"read missing from recorded: {p}" for p in reads if p not in recorded]
    problems += [f"fixture key missing from recorded: {p}" for p in fixture if p not in recorded]
    problems += [
        f"extra recorded key absent from fixture: {p}" for p in recorded if p not in fixture
    ]
    if problems:
        raise AssertionError("\n".join([f"{tool}: live-shape drift", *sorted(problems)]))


def _drift_lines(excinfo: pytest.ExceptionInfo) -> list[str]:
    return str(excinfo.value).splitlines()


class TestExtractKeyset:
    def test_nested_object_paths(self):
        assert extract_keyset({"a": {"b": {"c": "x"}}}) == {
            "a": "object",
            "a.b": "object",
            "a.b.c": "string",
        }

    def test_array_elements_marked(self):
        payload = {"recipients": [{"address": "jordan@example.invalid"}], "tags": ["x"]}
        assert extract_keyset(payload) == {
            "recipients": "array",
            "recipients[]": "object",
            "recipients[].address": "string",
            "tags": "array",
            "tags[]": "string",
        }

    def test_root_array_and_nested_arrays(self):
        assert extract_keyset([{"grid": [[1]]}]) == {
            "[]": "object",
            "[].grid": "array",
            "[].grid[]": "array",
            "[].grid[][]": "number",
        }

    def test_type_names(self):
        payload = {"n": None, "b": True, "i": 3, "f": 1.5, "s": "", "o": {}, "a": []}
        assert extract_keyset(payload) == {
            "n": "null",
            "b": "boolean",
            "i": "number",
            "f": "number",
            "s": "string",
            "o": "object",
            "a": "array",
        }

    def test_never_emits_values(self):
        values = [
            "AAMkADExampleId688=",
            "jordan.example@example.invalid",
            "Example, Jordan",
            "The quick brown fox — café",
            "1781900100.222222",
        ]
        payload = {
            "id": values[0],
            "from": {"email": values[1], "name": values[2]},
            "subject": values[3],
            "ts": values[4],
            "toRecipients": [{"email": values[1]}],
            "senders": [values[2]],
        }
        keyset = extract_keyset(payload)
        dumped = json.dumps(keyset, ensure_ascii=False)
        for value in values:
            assert value not in dumped
        assert set(keyset.values()) <= JSON_TYPES

    def test_scalar_root_has_no_paths(self):
        assert extract_keyset("The quick brown fox") == {}

    def test_conflicting_types_raise(self):
        with pytest.raises(ValueError, match="'a'"):
            extract_items_keyset([{"a": "x"}, {"a": 1}])

    def test_items_keyset_merges(self):
        assert extract_items_keyset([{"a": 1}, {"b": {"c": None}}]) == {
            "a": "number",
            "b": "object",
            "b.c": "null",
        }


class TestRecordedKeysets:
    @pytest.mark.parametrize("name", sorted(RECORDED_FILES.values()))
    def test_recorded_file_is_flat_path_to_type_map(self, name):
        path = RECORDED_DIR / f"{name}.json"
        assert path.is_file()
        data = json.loads(path.read_text())
        assert isinstance(data, dict) and data
        for key, value in data.items():
            assert isinstance(key, str) and _PATH_RE.match(key), key
            assert value in JSON_TYPES, (key, value)

    def test_no_unexpected_recorded_files(self):
        assert {p.stem for p in RECORDED_DIR.glob("*.json")} == set(RECORDED_FILES.values())

    def test_email_inbox_matches_707_live_item(self):
        assert load_recorded("email_inbox") == extract_keyset(LIVE_INBOX_ITEM)

    def test_calendar_view_matches_651_live_item(self):
        assert load_recorded("calendar_view") == extract_keyset(LIVE_CALENDAR_VIEW_ITEM)


class TestAdapterReads:
    def test_declared_for_all_tools(self):
        tools = {"email_inbox", "calendar_view", "get_messages"}
        assert set(LIVE_READS) == set(FALLBACK_READS) == tools
        for tool, reads in LIVE_READS.items():
            assert reads, tool
            assert all(isinstance(p, str) and _PATH_RE.match(p) for p in reads), tool

    def test_fallback_reads_have_reasons(self):
        for tool, fallbacks in FALLBACK_READS.items():
            for path, reason in fallbacks.items():
                assert isinstance(path, str) and _PATH_RE.match(path), (tool, path)
                assert isinstance(reason, str) and reason.strip(), (tool, path)
            assert not set(fallbacks) & set(LIVE_READS[tool]), tool

    @pytest.mark.parametrize("name", ["LIVE_READS", "FALLBACK_READS"])
    def test_is_a_literal_dict(self, name):
        tree = ast.parse(Path(__file__).read_text())
        (node,) = [
            n
            for n in tree.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)
        ]
        assert ast.literal_eval(node.value) == globals()[name]


class TestDriftCheck:
    @pytest.mark.parametrize("tool", sorted(LIVE_READS))
    def test_committed_shapes_have_no_drift(self, tool):
        assert_no_drift(
            tool,
            reads=LIVE_READS[tool],
            recorded=load_recorded(RECORDED_FILES[tool]),
            fixture=_fixture_keyset(tool),
        )

    @pytest.mark.parametrize(
        ("tool", "dropped"),
        [(tool, path) for tool, reads in sorted(LIVE_READS.items()) for path in reads],
    )
    def test_case_a_read_missing_from_recorded(self, tool, dropped):
        recorded = load_recorded(RECORDED_FILES[tool])
        assert dropped in recorded
        del recorded[dropped]
        with pytest.raises(AssertionError) as excinfo:
            assert_no_drift(
                tool, reads=LIVE_READS[tool], recorded=recorded, fixture=_fixture_keyset(tool)
            )
        lines = _drift_lines(excinfo)
        assert lines[0] == f"{tool}: live-shape drift"
        assert f"read missing from recorded: {dropped}" in lines

    @pytest.mark.parametrize("tool", sorted(LIVE_READS))
    def test_case_b_recorded_key_absent_from_fixture(self, tool):
        fixture = _fixture_keyset(tool)
        removed = sorted(fixture)[-1]
        del fixture[removed]
        with pytest.raises(AssertionError) as excinfo:
            assert_no_drift(
                tool,
                reads=LIVE_READS[tool],
                recorded=load_recorded(RECORDED_FILES[tool]),
                fixture=fixture,
            )
        lines = _drift_lines(excinfo)
        assert lines[0] == f"{tool}: live-shape drift"
        assert f"extra recorded key absent from fixture: {removed}" in lines

    @pytest.mark.parametrize("tool", sorted(FALLBACK_READS))
    def test_fallback_reads_absent_from_committed_shape(self, tool):
        # A fallback the live tool does send belongs in LIVE_READS.
        assert not set(FALLBACK_READS[tool]) & set(load_recorded(RECORDED_FILES[tool]))

    def test_string_item_ids_in_recorded_flag_item_id_read(self):
        recorded = extract_keyset({**LIVE_INBOX_ITEM, "itemIds": ["AAkALgExampleItem1="]})
        with pytest.raises(AssertionError) as excinfo:
            assert_no_drift(
                "email_inbox",
                reads=LIVE_READS["email_inbox"],
                recorded=recorded,
                fixture=_fixture_keyset("email_inbox"),
            )
        assert "read missing from recorded: itemIds[].id" in _drift_lines(excinfo)


# Fictitious repro of the drift shape: a Graph-style message fixture fed to a
# tool whose live items are conversation-grouped.
REPRO_FIXTURE_ITEM = {
    "id": "msg-0688",
    "toRecipients": [{"name": "Example, Jordan", "email": "jordan@example.invalid"}],
    "ccRecipients": [{"name": "Müller, Avery", "email": "avery@example.invalid"}],
    "messageClass": "IPM.Note",
    "subject": "The quick brown fox — café",
    "from": {"name": "Sample, Casey", "email": "casey@example.invalid"},
}

REPRO_RECORDED_ITEM = {
    "itemIds": [{"id": "AAMkADExampleItem688=", "changeKey": "CQAAAA=="}],
    "recipients": ["Example, Jordan"],
    "itemClasses": ["IPM.Note"],
    "topic": "The quick brown fox — café",
    "senders": ["Sample, Casey"],
    "preview": "Jumps over the lazy dog.",
}


class TestEmailInboxRepro:
    def _drift(self, recorded: dict[str, str]) -> list[str]:
        with pytest.raises(AssertionError) as excinfo:
            assert_no_drift(
                "email_inbox",
                reads=LIVE_READS["email_inbox"],
                recorded=recorded,
                fixture=extract_keyset(REPRO_FIXTURE_ITEM),
            )
        lines = _drift_lines(excinfo)
        assert lines[0] == "email_inbox: live-shape drift"
        return lines

    def test_against_live_recorded_shape(self):
        lines = self._drift(extract_keyset(REPRO_RECORDED_ITEM))
        for path in REPRO_FIXTURE_ITEM:
            assert f"fixture key missing from recorded: {path}" in lines
        for path in REPRO_RECORDED_ITEM:
            assert f"extra recorded key absent from fixture: {path}" in lines

    def test_against_committed_recorded_set(self):
        lines = self._drift(load_recorded("email_inbox"))
        for path in ("ccRecipients", "ccRecipients[].email", "messageClass"):
            assert f"fixture key missing from recorded: {path}" in lines
        for path in ("recipients", "topic", "senders", "preview"):
            assert f"extra recorded key absent from fixture: {path}" in lines


# Fictitious repros of the #699 live trigger shapes: ``email_inbox`` items list
# ``itemIds`` as objects and carry ``itemClasses`` and ``hasAttachments``;
# ``get_messages`` items may carry ``members`` (a fallback read, #707).
LIVE_INBOX_ITEM_699 = {
    "conversationId": "AAQkADExampleConv699=",
    "itemIds": [{"id": "AAMkADExampleItem699="}],
    "itemClasses": ["IPM.Note"],
    "hasAttachments": False,
    "topic": "The quick brown fox — café",
    "senders": ["Example, Jordan"],
    "recipients": ["Müller, Avery"],
    "lastDeliveryTime": "2026-11-19T09:30:00-06:00",
    "preview": "Jumps over the lazy dog.",
}

LIVE_MESSAGE_ITEM_699 = {
    "user": "U0EXAMPLE99",
    "text": "The quick brown fox — café",
    "ts": "1781900000.699001",
    "channel_id": "D0EXAMPLE99",
    "channel_name": "jordan-example",
    "reactions": [],
    "members": ["U0EXAMPLE99", "U0EXAMPLE98"],
}


class TestUndeclaredReadsRepro:
    def test_reads_declared(self):
        recorded = extract_keyset(LIVE_INBOX_ITEM_699)
        for path in ["itemIds[].id", "itemClasses"]:
            assert path in LIVE_READS["email_inbox"]
            assert path in recorded

    def test_members_declared_fallback(self):
        assert "members" in FALLBACK_READS["get_messages"]
        assert "members" not in LIVE_READS["get_messages"]

    def _missing_reads(self, tool: str, item: dict) -> list[str]:
        keyset = extract_keyset(item)
        try:
            assert_no_drift(tool, reads=LIVE_READS[tool], recorded=keyset, fixture=keyset)
        except AssertionError as exc:
            return [line for line in str(exc).splitlines() if line.startswith("read missing")]
        return []

    def test_string_item_ids_flag_item_id_read(self):
        item = {**LIVE_INBOX_ITEM_699, "itemIds": ["AAMkADExampleItem699="]}
        del item["itemClasses"]
        missing = self._missing_reads("email_inbox", item)
        assert "read missing from recorded: itemIds[].id" in missing
        assert "read missing from recorded: itemClasses" in missing

    def test_object_item_ids_cover_item_id_read(self):
        assert self._missing_reads("email_inbox", LIVE_INBOX_ITEM_699) == []

    def test_members_not_required_in_recorded(self):
        item = {k: v for k, v in LIVE_MESSAGE_ITEM_699.items() if k != "members"}
        assert self._missing_reads("get_messages", item) == []
        assert self._missing_reads("get_messages", LIVE_MESSAGE_ITEM_699) == []
