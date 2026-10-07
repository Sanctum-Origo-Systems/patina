from __future__ import annotations

from patina.extraction import (
    extract_entities_from_text,
    extract_sender_entity,
    is_non_person_sender,
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
