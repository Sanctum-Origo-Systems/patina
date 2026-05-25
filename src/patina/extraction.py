from __future__ import annotations

import hashlib
import re

from patina.models import Entity

_MENTION_RE = re.compile(r"<@([UW][A-Z0-9]+)>")
_CHANNEL_RE = re.compile(r"<#(C[A-Z0-9]+)\|([^>]+)>")
_URL_RE = re.compile(r"https?://[^\s>]+")


def _make_id(entity_type: str, key: str) -> str:
    return hashlib.sha256(f"{entity_type}:{key}".encode()).hexdigest()[:16]


def extract_entities_from_text(text: str) -> list[Entity]:
    entities: list[Entity] = []

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
        url = match.group(0)
        entities.append(
            Entity(
                id=_make_id("reference", url),
                type="reference",
                name=url,
            )
        )

    return entities


def extract_sender_entity(user_id: str, user_name: str | None = None) -> Entity:
    return Entity(
        id=_make_id("person", user_id),
        type="person",
        name=user_name or user_id,
        aliases=[user_id],
    )
