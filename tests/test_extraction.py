from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from patina.extraction import (
    CALENDAR_CHANNEL_PREFIX,
    _make_id,
    extract_entities_from_text,
    extract_sender_entity,
    is_non_person_sender,
    sanitize_reference_url,
    strip_slack_link_markup,
)
from patina.owner import normalize_alias


def test_single_mention():
    entities = extract_entities_from_text("Hey <@U001> check this")
    assert len(entities) == 1
    assert entities[0].type == "person"


def test_multiple_mentions():
    entities = extract_entities_from_text("<@U001> and <@U002> on it")
    people = [e for e in entities if e.type == "person"]
    assert len(people) == 2


def test_channel_reference():
    entities = extract_entities_from_text("See <#C001|general> for details")
    topics = [e for e in entities if e.type == "topic"]
    assert len(topics) == 1
    assert topics[0].name == "general"


def test_url_reference():
    entities = extract_entities_from_text("Check https://example.com/page")
    refs = [e for e in entities if e.type == "reference"]
    assert len(refs) == 1
    assert "example.com" in refs[0].name


def test_plain_text_empty():
    entities = extract_entities_from_text("Just a normal message")
    assert entities == []


def test_sender_entity_with_name():
    e = extract_sender_entity("U001", "Alice")
    assert e.type == "person"
    assert e.name == "Alice"
    assert "U001" in e.aliases


def test_sender_entity_without_name():
    e = extract_sender_entity("U001")
    assert e.name == "U001"


def test_ids_deterministic():
    e1 = extract_sender_entity("U001")
    e2 = extract_sender_entity("U001")
    assert e1.id == e2.id


def test_ids_unique():
    e1 = extract_sender_entity("U001")
    e2 = extract_sender_entity("U002")
    assert e1.id != e2.id


def test_sender_entity_last_first_normalized():
    e = extract_sender_entity("U001", "Chen, Dana")
    assert e.name == "Dana Chen"
    assert "Chen, Dana" in e.aliases
    assert "U001" in e.aliases


def test_sender_entity_includes_display_name_as_alias():
    e = extract_sender_entity("U001", "Alice Smith")
    assert e.name == "Alice Smith"
    assert "U001" in e.aliases
    assert "Alice Smith" in e.aliases


def test_sender_entity_no_duplicate_aliases():
    e = extract_sender_entity("U001", "Alice")
    assert len(e.aliases) == len(set(e.aliases))


def test_sender_entity_normalize_matches_prefixed():
    e = extract_sender_entity("U000OWNER", "srivera")
    normalized_aliases = {normalize_alias(a) for a in e.aliases}
    assert normalize_alias("slack:U000OWNER") in normalized_aliases
    assert "srivera" in normalized_aliases


def test_sender_entity_includes_slack_prefix_alias():
    e = extract_sender_entity("U000OWNER", "srivera")
    assert "slack:U000OWNER" in e.aliases
    assert "U000OWNER" in e.aliases


def test_is_non_person_sender_bot():
    assert is_non_person_sender("U001", "Build Bot") is True


def test_is_non_person_sender_normal():
    assert is_non_person_sender("U001", "Alice Chen") is False


def test_is_non_person_sender_noreply_id():
    assert is_non_person_sender("noreply@example.com") is True


def test_is_non_person_sender_none_name():
    assert is_non_person_sender("U001", None) is False


def test_slack_link_markup_stripped():
    text = "Check <https://github.com/org/repo/compare/a...b|compare diff> for details"
    entities = extract_entities_from_text(text)
    refs = [e for e in entities if e.type == "reference"]
    assert len(refs) == 0


def test_slack_link_markup_no_label():
    text = "See <https://example.com/path|>"
    entities = extract_entities_from_text(text)
    refs = [e for e in entities if e.type == "reference"]
    assert len(refs) == 1
    assert "example.com" in refs[0].name


def test_slack_link_markup_preserves_plain_urls():
    text = "Visit https://example.com/page for more"
    entities = extract_entities_from_text(text)
    refs = [e for e in entities if e.type == "reference"]
    assert len(refs) == 1
    assert "example.com" in refs[0].name


def test_slack_link_markup_mixed_content():
    text = (
        "<@U001> shared <https://github.com/org/repo|repo link> "
        "and https://docs.example.com in <#C001|general>"
    )
    entities = extract_entities_from_text(text)
    people = [e for e in entities if e.type == "person"]
    topics = [e for e in entities if e.type == "topic"]
    refs = [e for e in entities if e.type == "reference"]
    assert len(people) == 1
    assert len(topics) == 1
    assert len(refs) == 1
    assert "docs.example.com" in refs[0].name


def test_strip_slack_link_markup():
    text = "Link: <https://example.com/path|click here> end"
    assert strip_slack_link_markup(text) == "Link: click here end"


def test_strip_slack_link_markup_multiple():
    text = "<https://a.com|A> and <https://b.com|B>"
    assert strip_slack_link_markup(text) == "A and B"


def test_strip_slack_link_markup_no_label():
    text = "See <https://example.com>"
    assert strip_slack_link_markup(text) == "See https://example.com"


def test_strip_slack_link_markup_mixed():
    text = "Check <https://github.com/org/repo|this PR> and <https://example.com>"
    assert strip_slack_link_markup(text) == "Check this PR and https://example.com"


def test_sender_entity_strips_parenthetical():
    e = extract_sender_entity("U001", "Dana Brook (Marketing)")
    assert e.name == "Dana Brook"
    assert "U001" in e.aliases


def test_sender_entity_strips_truncated_bracket():
    e = extract_sender_entity("U001", "Dana Brook (")
    assert e.name == "Dana Brook"


def test_sender_entity_parenthetical_with_comma_format():
    e = extract_sender_entity("U001", "Brook, Dana (Ext)")
    assert e.name == "Dana Brook"


def test_sender_entity_no_parenthetical_unchanged():
    e = extract_sender_entity("U001", "Dana Brook")
    assert e.name == "Dana Brook"


def test_sender_entity_email_as_user_id_no_name():
    e = extract_sender_entity("dbrook@example.com", None)
    assert e.name == "dbrook@example.com"
    assert "dbrook@example.com" in e.aliases


def test_sender_entity_organization_type():
    e = extract_sender_entity("U001", "Acme Field Research")
    assert e.type == "organization"
    assert e.name == "Acme Field Research"


def test_sender_entity_organization_events():
    e = extract_sender_entity("U001", "Acme Events")
    assert e.type == "organization"


def test_sender_entity_person_stays_person():
    e = extract_sender_entity("U001", "Dana Brook")
    assert e.type == "person"


def test_sender_entity_org_id_stable():
    e_org = extract_sender_entity("U001", "Acme Events")
    e_person = extract_sender_entity("U001", "Alice Chen")
    assert e_org.id == e_person.id


def test_sender_entity_outlook_bot_not_person():
    e = extract_sender_entity("Acme Security Bot", "Acme Security Bot", source_family="outlook")
    assert e.type == "organization"


def test_sender_entity_outlook_service_not_person():
    e = extract_sender_entity(
        "Example Notify Service", "Example Notify Service", source_family="outlook"
    )
    assert e.type == "organization"


def test_sender_entity_outlook_hyphenated_commenter_not_person():
    assert is_non_person_sender("ci-merge-request-commenter") is True


def test_sender_entity_outlook_real_person_stays_person():
    assert is_non_person_sender("Dana Brook", "Brook, Dana") is False


def test_sender_entity_outlook_person_stays_person():
    e = extract_sender_entity("Dana Brook", "Dana Brook", source_family="outlook")
    assert e.type == "person"


def test_sender_entity_outlook_no_slack_alias():
    e = extract_sender_entity("Dana Brook", "Dana Brook", source_family="outlook")
    assert e.name == "Dana Brook"
    assert "Dana Brook" in e.aliases
    assert not any(a.startswith("slack:") for a in e.aliases)


def test_sender_entity_slack_gets_slack_alias():
    e = extract_sender_entity("U0EXAMPLE1", "Dana Brook", source_family="slack")
    assert "slack:U0EXAMPLE1" in e.aliases
    assert "U0EXAMPLE1" in e.aliases


def test_sender_entity_default_source_is_slack():
    e = extract_sender_entity("U0EXAMPLE1", "Dana Brook")
    assert "slack:U0EXAMPLE1" in e.aliases


class TestExtractSenderSlackIdPrecedence:
    """#448: extract_sender_entity delegates to resolve_entity_id for Slack ID precedence."""

    def test_slack_id_wins_over_display_name(self, slack_id_wins):
        conn = slack_id_wins["conn"]
        e = extract_sender_entity(
            slack_id_wins["slack_id"],
            slack_id_wins["shared_name"],
            conn=conn,
        )
        assert e.id == slack_id_wins["entity_with_slack"]
        assert e.id != slack_id_wins["entity_with_name"]
        assert slack_id_wins["slack_id"] in e.aliases

    def test_ambiguous_name_returns_new_entity(self, ambiguous_name):
        conn = ambiguous_name["conn"]
        e = extract_sender_entity("U0NEWID001", "Riku Endo", conn=conn)
        assert e is not None
        assert e.id != ambiguous_name["entity_a"]
        assert e.id != ambiguous_name["entity_b"]

    def test_clean_match_resolves(self, clean_merge):
        conn = clean_merge["conn"]
        e = extract_sender_entity("U0NEWID002", "Hana Kimura", conn=conn)
        assert e.id == clean_merge["entity_id"]

    def test_no_conn_uses_hash_id(self):
        e = extract_sender_entity("U0KAITANA", "Kai Tanaka")
        assert e is not None
        assert e.name == "Kai Tanaka"
        assert "U0KAITANA" in e.aliases


class TestSanitizeReferenceUrl:
    def test_strips_meeting_pwd(self):
        assert (
            sanitize_reference_url("https://meet.example.com/j/123?pwd=AbC123")
            == "https://meet.example.com/j/123"
        )

    def test_strips_amz_params(self):
        url = "https://files.example.com/a.pdf?X-Amz-Signature=abc&X-Amz-Credential=xyz&v=2"
        assert sanitize_reference_url(url) == "https://files.example.com/a.pdf?v=2"

    def test_strips_amz_security_token(self):
        url = "https://files.example.com/a.pdf?v=2&X-Amz-Security-Token=tok123"
        assert sanitize_reference_url(url) == "https://files.example.com/a.pdf?v=2"

    @pytest.mark.parametrize(
        "name",
        [
            "pwd",
            "password",
            "passcode",
            "token",
            "access_token",
            "key",
            "api_key",
            "sig",
            "signature",
        ],
    )
    @pytest.mark.parametrize("case", [str.lower, str.upper, str.title])
    def test_strips_each_credential_param(self, name, case):
        param = case(name)
        url = f"https://example.com/p?a=1&{param}=s3cret&b=2"
        result = sanitize_reference_url(url)
        assert result == "https://example.com/p?a=1&b=2"
        assert "s3cret" not in result

    def test_no_credentials_unchanged(self):
        url = "https://example.com/p?b=2&a=1#frag"
        assert sanitize_reference_url(url) == url

    def test_mixed_params_keep_order_and_fragment(self):
        url = "https://example.com/p?z=9&token=abc&a=1&Sig=def&m=5#section-2"
        assert sanitize_reference_url(url) == "https://example.com/p?z=9&a=1&m=5#section-2"

    def test_all_credentials_no_trailing_question_mark(self):
        url = "https://example.com/p?pwd=a&token=b&X-Amz-Date=c"
        assert sanitize_reference_url(url) == "https://example.com/p"

    def test_all_credentials_with_fragment(self):
        url = "https://example.com/p?pwd=a#frag"
        assert sanitize_reference_url(url) == "https://example.com/p#frag"

    def test_no_query_unchanged(self):
        url = "https://example.com/p#frag"
        assert sanitize_reference_url(url) == url

    def test_similar_param_names_kept(self):
        url = "https://example.com/p?keyword=x&monkey=y&tokens=z"
        assert sanitize_reference_url(url) == url


class TestReferenceEntitySanitization:
    def test_reference_name_has_no_credential(self):
        entities = extract_entities_from_text(
            "Join here: https://meet.example.com/j/123?pwd=AbC123"
        )
        refs = [e for e in entities if e.type == "reference"]
        assert len(refs) == 1
        assert refs[0].name == "https://meet.example.com/j/123"
        assert "AbC123" not in refs[0].name
        assert "pwd=" not in refs[0].name

    def test_same_link_different_pwd_same_entity(self):
        a = extract_entities_from_text("Call: https://meet.example.com/j/123?pwd=AbC123")
        b = extract_entities_from_text("Call: https://meet.example.com/j/123?pwd=ZyX987")
        ref_a = next(e for e in a if e.type == "reference")
        ref_b = next(e for e in b if e.type == "reference")
        assert ref_a.id == ref_b.id
        assert ref_a.name == ref_b.name
        assert ref_a.id == _make_id("reference", "https://meet.example.com/j/123")

    def test_clean_url_reference_unchanged(self):
        url = "https://example.com/p?b=2&a=1#frag"
        entities = extract_entities_from_text(f"See {url}")
        refs = [e for e in entities if e.type == "reference"]
        assert len(refs) == 1
        assert refs[0].name == url
        assert refs[0].id == _make_id("reference", url)


class _CalendarPort:
    @property
    def platform(self) -> str:
        return "outlook_mcp"

    def list_events(self, start, end):
        from patina.models import CalendarEvent

        return [
            CalendarEvent(
                id="AAMkCAL619",
                subject="Quick Brown Fox Sync",
                start=1781600000.0,
                end=1781601800.0,
                organizer="Jordan Example",
            ),
        ]


class TestCalendarObservationsQueryable:
    """#619: calendar rows skip belief extraction but stay queryable."""

    def test_events_to_chat_messages_uses_calendar_prefix(self):
        from patina.ingest import _events_to_chat_messages

        msgs = _events_to_chat_messages(_CalendarPort().list_events(None, None))
        assert len(msgs) == 1
        assert msgs[0].channel_id.startswith(CALENDAR_CHANNEL_PREFIX)
        # No attendees -> no ``Attendees:`` part (#651).
        assert msgs[0].text == "[Meeting: Quick Brown Fox Sync] Organizer: Jordan Example"

    def test_ingested_calendar_event_searchable_after_extraction(self, tmp_path):
        from unittest.mock import patch

        from patina.beliefs.extractor import extract_beliefs
        from patina.ingest import ingest_live
        from patina.mcp.tools_catch_up import store_search
        from patina.store import connect, get_db_path

        result = ingest_live(port=_CalendarPort(), source="outlook_mcp_calendar", home=tmp_path)
        assert result["messages_inserted"] == 1

        with patch("patina.beliefs.extractor._call_claude") as stub:
            stats = extract_beliefs(home=tmp_path, batch_size=5)
        stub.assert_not_called()
        assert stats["observations_processed"] == 0

        conn = connect(get_db_path(tmp_path))
        try:
            row = conn.execute(
                "SELECT id, channel_id, text, processed FROM observations"
                " WHERE channel_id LIKE 'calendar:%'"
            ).fetchone()
            assert row["channel_id"] == "calendar:AAMkCAL619"
            assert "Quick Brown Fox Sync" in row["text"]
            assert row["processed"] == 0

            fts = conn.execute(
                "SELECT o.id FROM observations_fts f"
                " JOIN observations o ON f.rowid = o.rowid"
                " WHERE observations_fts MATCH ?",
                ('"Fox"',),
            ).fetchall()
            assert [r["id"] for r in fts] == [row["id"]]
        finally:
            conn.close()

        out = store_search("Quick Brown Fox Sync")
        assert "Quick Brown Fox Sync" in out
        assert "outlook_mcp_calendar" in out


# --- outcome gate (#670) ---

_SYNC_SUBJECT = "Accepted: Weekly sync with Dana Brook"
_SYNC_TEXT = f"[Meeting: {_SYNC_SUBJECT}] Organizer: Dana Brook"
_SYNC_TS = 1781600000.0
_SYNC_INGESTED_AT = "2026-11-02T08:00:00+00:00"

# A response that would create entities, a claim and a relationship if any
# batch reached the model.
_DANA_RESPONSE = json.dumps(
    {
        "entities": [
            {"name": "Dana Brook", "aliases": [], "type": "person"},
            {"name": "Jordan Example", "aliases": [], "type": "person"},
        ],
        "claims": [
            {
                "subject": "Dana Brook",
                "predicate": "role",
                "object": "sync organizer",
                "confidence": 0.9,
            }
        ],
        "relationships": [
            {
                "subject": "Dana Brook",
                "predicate": "works_with",
                "object": "Jordan Example",
                "confidence": 0.8,
            }
        ],
        "behavioral": [],
    }
)
_EMPTY_RESPONSE = json.dumps({"entities": [], "claims": [], "relationships": [], "behavioral": []})


def _insert(conn, obs_id, text, outcome, *, channel_id, ts=_SYNC_TS, metadata=None):
    from patina.graph import insert_observation
    from patina.models import Observation

    is_calendar = channel_id.startswith(CALENDAR_CHANNEL_PREFIX)
    insert_observation(
        conn,
        Observation(
            id=obs_id,
            source="outlook_mcp_calendar" if is_calendar else "slack_live",
            channel_id=channel_id,
            thread_id=None,
            timestamp=ts,
            sender_entity_id=None,
            text=text,
            metadata=metadata or {},
            ingested_at=_SYNC_INGESTED_AT,
            outcome=outcome,
        ),
    )


def _insert_sync_row(conn):
    _insert(
        conn,
        "obs-sync",
        _SYNC_TEXT,
        "RETAIN_ONLY",
        channel_id="calendar:AAMkSYNC1",
        metadata={"subject": _SYNC_SUBJECT, "body": ""},
    )


def _run_extraction(home, response=_DANA_RESPONSE):
    from unittest.mock import patch

    from patina.beliefs.extractor import extract_beliefs

    with (
        patch("patina.beliefs.extractor._call_claude", return_value=response) as stub,
        patch("patina.beliefs.extractor.time.sleep"),
    ):
        stats = extract_beliefs(home=home, batch_size=5)
    return stats, stub


def _belief_counts(conn):
    return tuple(
        conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("entities", "claims", "relationships")
    )


class TestOutcomeGate:
    """#670: extraction itself skips RETAIN_ONLY rows; RETAIN_AND_EXTRACT rows run as before."""

    def test_retain_only_row_yields_no_beliefs_and_stays_readable(self, db_conn, tmp_path):
        _insert_sync_row(db_conn)

        stats, stub = _run_extraction(tmp_path)

        stub.assert_not_called()
        assert stats["observations_processed"] == 0
        assert _belief_counts(db_conn) == (0, 0, 0)

        row = db_conn.execute("SELECT * FROM observations WHERE id = 'obs-sync'").fetchone()
        assert row["source"] == "outlook_mcp_calendar"
        assert row["channel_id"] == "calendar:AAMkSYNC1"
        assert row["text"] == _SYNC_TEXT
        assert json.loads(row["metadata"]) == {"subject": _SYNC_SUBJECT, "body": ""}
        assert row["timestamp"] == _SYNC_TS
        assert row["ingested_at"] == _SYNC_INGESTED_AT
        assert row["outcome"] == "RETAIN_ONLY"
        assert row["processed"] == 0

    def test_empty_retain_only_row_is_not_marked_processed(self, db_conn):
        from patina.extraction import mark_empty_observations_processed

        _insert(db_conn, "obs-empty-ro", "", "RETAIN_ONLY", channel_id="calendar:AAMkSYNC2")
        _insert(db_conn, "obs-empty-rae", "", "RETAIN_AND_EXTRACT", channel_id="D0EXAMPLE01")

        assert mark_empty_observations_processed(db_conn) == 1

        processed = dict(db_conn.execute("SELECT id, processed FROM observations").fetchall())
        assert processed == {"obs-empty-ro": 0, "obs-empty-rae": 1}

    def test_mixed_batch_only_retain_and_extract_rows_processed(self, db_conn, tmp_path):
        from patina.extraction import extractable_observations

        # The gate is the outcome, not the channel: a RETAIN_ONLY chat row is
        # skipped and a RETAIN_AND_EXTRACT calendar row is read.
        _insert(db_conn, "ro-cal", _SYNC_TEXT, "RETAIN_ONLY", channel_id="calendar:AAMkSYNC1")
        _insert(db_conn, "ro-chat", "Jordan Example: très bien", "RETAIN_ONLY", channel_id="D0EX02")
        _insert(
            db_conn,
            "rae-chat",
            "The quick brown fox",
            "RETAIN_AND_EXTRACT",
            channel_id="D0EX01",
            ts=_SYNC_TS + 1,
        )
        _insert(
            db_conn,
            "rae-cal",
            "[Meeting: Lazy dog review] Organizer: Jordan Example",
            "RETAIN_AND_EXTRACT",
            channel_id="calendar:AAMkSYNC3",
            ts=_SYNC_TS + 2,
        )

        rows = extractable_observations(db_conn, limit=10)
        assert [r["id"] for r in rows] == ["rae-chat", "rae-cal"]

        stats, stub = _run_extraction(tmp_path, response=_EMPTY_RESPONSE)

        assert stub.call_count == 1
        prompt = stub.call_args.args[0]
        assert "The quick brown fox" in prompt
        assert "Lazy dog review" in prompt
        assert _SYNC_SUBJECT not in prompt
        assert "très bien" not in prompt
        assert stats["observations_processed"] == 2
        processed = dict(db_conn.execute("SELECT id, processed FROM observations").fetchall())
        assert processed == {"ro-cal": 0, "ro-chat": 0, "rae-chat": 1, "rae-cal": 1}

    def test_promoted_row_is_extracted_with_its_observation_id(self, db_conn, tmp_path):
        _insert_sync_row(db_conn)
        _, stub = _run_extraction(tmp_path)
        stub.assert_not_called()

        db_conn.execute(
            "UPDATE observations SET outcome = 'RETAIN_AND_EXTRACT' WHERE id = 'obs-sync'"
        )
        db_conn.commit()

        stats, stub = _run_extraction(tmp_path)

        assert stub.call_count == 1
        assert _SYNC_SUBJECT in stub.call_args.args[0]
        assert stats["observations_processed"] == 1
        claims = db_conn.execute("SELECT predicate, source_ids FROM claims").fetchall()
        assert [c["predicate"] for c in claims] == ["role"]
        assert json.loads(claims[0]["source_ids"]) == ["obs-sync"]


def _src_files():
    import patina

    return sorted(Path(patina.__file__).parent.rglob("*.py"))


def test_only_extraction_module_filters_on_outcome():
    """#670: no caller in src/ re-checks the outcome; extraction.py is the only gate.

    store.py holds the column's CHECK constraint and the #669 backfill (a writer).
    """
    predicate = re.compile(
        r"\boutcome\s*(?:=|!=|<>|IN)\s*[?(']|\.outcome\s*(?:==|!=|in\b)"
        r"|(?:==|!=)\s*IngestionOutcome\.|IngestionOutcome\.\w+\s*(?:==|!=)"
    )
    filtering = {p.name for p in _src_files() if predicate.search(p.read_text())}
    assert filtering == {"extraction.py", "store.py"}

    from patina.beliefs import extractor

    source = Path(extractor.__file__).read_text()
    assert "extractable_observations(conn" in source
    assert "FROM observations o" not in source
    assert "CALENDAR_CHANNEL_PREFIX" not in source


def test_no_deletion_ttl_or_redaction_touches_retain_only_rows():
    """#670 adds no retention, expiry or privacy behaviour for RETAIN_ONLY rows."""
    import ast

    forbidden = re.compile(
        r"\bDELETE\b|\bttl\b|expir|redact|purge|retention|SET\s+(?:text|metadata)\b", re.I
    )
    named = re.compile(r"delete|purge|expir|redact|ttl|retention|cleanup", re.I)
    for path in _src_files():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for stmt in node.value.split(";"):
                    if re.search(r"\boutcome\b|RETAIN_ONLY", stmt):
                        assert not forbidden.search(stmt), f"{path.name}: {stmt.strip()[:80]}"
            if isinstance(node, ast.FunctionDef) and named.search(node.name):
                refs = {
                    n.attr
                    for n in ast.walk(node)
                    if isinstance(n, ast.Attribute) and n.attr.startswith("RETAIN_")
                }
                assert not refs, f"{path.name}:{node.name} references {refs}"
