from __future__ import annotations

import pytest

from patina.extraction import (
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
