"""Live-shape drift: fixtures vs recorded key sets vs declared adapter reads (#688).

Each recorded key set in ``recorded_keysets/`` is the item-level shape a tool
returns. The drift check fails when a declared adapter read is missing from
the recorded set, when the fixture carries a key the recorded set lacks, or
when a recorded key is absent from the fixture.
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
from tests.adapters.test_outlook_mcp import (
    FIXTURE_INBOX_CONVERSATION_GROUPED,
    FIXTURE_INBOX_RAW,
    LIVE_CALENDAR_VIEW_ITEM,
)
from tests.adapters.test_slack_mcp import FIXTURES_MESSAGES_DICT, FIXTURES_MESSAGES_LIST

# Hand-written key paths each adapter reads that the recorded shape covers.
# Keep in step with the adapters by hand; never derive from adapter source.
ADAPTER_READS = {
    "email_inbox": [
        "id",
        "conversationId",
        "subject",
        "topic",
        "from.email",
        "from.name",
        "senders",
        "recipients",
        "toRecipients[].email",
        "toRecipients[].name",
        "receivedDateTime",
        "lastDeliveryTime",
        "preview",
        "bodyPreview",
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

RECORDED_FILES = {
    "email_inbox": "email_inbox",
    "calendar_view": "calendar_view",
    "get_messages": "slack_get_messages",
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
        items = _outlook_inbox_items(FIXTURE_INBOX_RAW, FIXTURE_INBOX_CONVERSATION_GROUPED)
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

    def test_email_inbox_matches_664_live_shape_fixtures(self):
        items = _outlook_inbox_items(FIXTURE_INBOX_RAW, FIXTURE_INBOX_CONVERSATION_GROUPED)
        assert load_recorded("email_inbox") == extract_items_keyset(items)

    def test_calendar_view_matches_651_live_item(self):
        assert load_recorded("calendar_view") == extract_keyset(LIVE_CALENDAR_VIEW_ITEM)


class TestAdapterReads:
    def test_declared_for_all_tools(self):
        assert set(ADAPTER_READS) == {"email_inbox", "calendar_view", "get_messages"}
        for tool, reads in ADAPTER_READS.items():
            assert reads, tool
            assert all(isinstance(p, str) and _PATH_RE.match(p) for p in reads), tool

    def test_is_a_literal_dict(self):
        tree = ast.parse(Path(__file__).read_text())
        (node,) = [
            n
            for n in tree.body
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "ADAPTER_READS" for t in n.targets)
        ]
        assert ast.literal_eval(node.value) == ADAPTER_READS


class TestDriftCheck:
    @pytest.mark.parametrize("tool", sorted(ADAPTER_READS))
    def test_committed_shapes_have_no_drift(self, tool):
        assert_no_drift(
            tool,
            reads=ADAPTER_READS[tool],
            recorded=load_recorded(RECORDED_FILES[tool]),
            fixture=_fixture_keyset(tool),
        )

    @pytest.mark.parametrize("tool", sorted(ADAPTER_READS))
    def test_case_a_read_missing_from_recorded(self, tool):
        dropped = ADAPTER_READS[tool][0]
        recorded = load_recorded(RECORDED_FILES[tool])
        del recorded[dropped]
        with pytest.raises(AssertionError) as excinfo:
            assert_no_drift(
                tool, reads=ADAPTER_READS[tool], recorded=recorded, fixture=_fixture_keyset(tool)
            )
        lines = _drift_lines(excinfo)
        assert lines[0] == f"{tool}: live-shape drift"
        assert f"read missing from recorded: {dropped}" in lines

    @pytest.mark.parametrize("tool", sorted(ADAPTER_READS))
    def test_case_b_recorded_key_absent_from_fixture(self, tool):
        fixture = _fixture_keyset(tool)
        removed = sorted(fixture)[-1]
        del fixture[removed]
        with pytest.raises(AssertionError) as excinfo:
            assert_no_drift(
                tool,
                reads=ADAPTER_READS[tool],
                recorded=load_recorded(RECORDED_FILES[tool]),
                fixture=fixture,
            )
        lines = _drift_lines(excinfo)
        assert lines[0] == f"{tool}: live-shape drift"
        assert f"extra recorded key absent from fixture: {removed}" in lines


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
    "itemIds": ["AAMkADExampleItem688="],
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
                reads=ADAPTER_READS["email_inbox"],
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
