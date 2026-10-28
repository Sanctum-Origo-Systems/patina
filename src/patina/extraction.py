from __future__ import annotations

import hashlib
import re
import sqlite3
from urllib.parse import unquote_plus

from patina.models import Entity

_MENTION_RE = re.compile(r"<@([UW][A-Z0-9]+)>")
_CHANNEL_RE = re.compile(r"<#(C[A-Z0-9]+)\|([^>]+)>")
_SLACK_LINK_RE = re.compile(r"<(https?://[^|>]+)(?:\|([^>]*))?>")

_URL_RE = re.compile(r"https?://[^\s>]+")

_CREDENTIAL_PARAMS = frozenset(
    {
        "pwd",
        "password",
        "passcode",
        "token",
        "access_token",
        "key",
        "api_key",
        "sig",
        "signature",
    }
)
_CREDENTIAL_PARAM_PREFIX = "x-amz-"


def _make_id(entity_type: str, key: str) -> str:
    return hashlib.sha256(f"{entity_type}:{key}".encode()).hexdigest()[:16]


def _is_credential_param(param: str) -> bool:
    name = unquote_plus(param.split("=", 1)[0]).lower()
    return name in _CREDENTIAL_PARAMS or name.startswith(_CREDENTIAL_PARAM_PREFIX)


def sanitize_reference_url(url: str) -> str:
    """Strip credential-like query parameters from a URL.

    Parameters are matched case-insensitively. Remaining parameters keep their
    original order and raw encoding, and the fragment is preserved. A URL with
    no credential parameters is returned unchanged.
    """
    base, hash_sign, fragment = url.partition("#")
    path, question, query = base.partition("?")
    if not question:
        return url

    params = query.split("&")
    kept = [p for p in params if not _is_credential_param(p)]
    if len(kept) == len(params):
        return url

    sanitized = path
    if kept:
        sanitized += "?" + "&".join(kept)
    return sanitized + hash_sign + fragment


def strip_slack_link_markup(text: str) -> str:
    return _SLACK_LINK_RE.sub(lambda m: m.group(2) if m.group(2) else m.group(1), text)


def extract_entities_from_text(text: str) -> list[Entity]:
    entities: list[Entity] = []
    text = strip_slack_link_markup(text)

    for match in _MENTION_RE.finditer(text):
        user_id = match.group(1)
        entities.append(
            Entity(
                id=_make_id("person", user_id),
                type="person",
                name=user_id,
                aliases=[user_id],
            )
        )

    for match in _CHANNEL_RE.finditer(text):
        channel_id = match.group(1)
        channel_name = match.group(2)
        entities.append(
            Entity(
                id=_make_id("topic", channel_id),
                type="topic",
                name=channel_name,
                aliases=[channel_id],
            )
        )

    for match in _URL_RE.finditer(text):
        url = sanitize_reference_url(match.group(0))
        entities.append(
            Entity(
                id=_make_id("reference", url),
                type="reference",
                name=url,
            )
        )

    return entities


def is_non_person_sender(user_id: str, user_name: str | None = None) -> bool:
    from patina.maintenance import is_non_person

    if user_name and is_non_person(user_name):
        return True
    if is_non_person(user_id):
        return True
    return False


def extract_sender_entity(
    user_id: str,
    user_name: str | None = None,
    *,
    source_family: str = "slack",
    conn: sqlite3.Connection | None = None,
) -> Entity | None:
    from patina.maintenance import is_organization

    aliases = [user_id]
    if source_family == "slack":
        aliases.append(f"slack:{user_id}")

    if user_name:
        cleaned = user_name.split("(", 1)[0].strip()
        if cleaned:
            user_name = cleaned

    canonical_name = user_name or user_id

    if user_name and "," in user_name:
        parts = [p.strip() for p in user_name.split(",", 1)]
        if len(parts) == 2:
            canonical_name = f"{parts[1]} {parts[0]}"
            aliases.append(user_name)

    if user_name and user_name != user_id:
        aliases.append(user_name)

    entity_type = "organization" if is_organization(canonical_name) else "person"

    entity_id = _make_id("person", user_id)

    if conn is not None:
        from patina.graph import resolve_entity_id

        resolved = resolve_entity_id(conn, canonical_name, aliases)
        if resolved is not None:
            entity_id = resolved

    return Entity(
        id=entity_id,
        type=entity_type,
        name=canonical_name,
        aliases=list(set(aliases)),
    )
