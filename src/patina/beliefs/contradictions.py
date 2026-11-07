from __future__ import annotations

import re
import sqlite3

from patina.llm import LLMPort

MAX_CONTRADICTIONS = 100

# Fields where a conflict is most likely real sort first; anything else sorts last.
_FIELD_RANK = {"title": 0, "org": 1, "location": 2}

_TEMPORARY_LOCATION = re.compile(
    r"\b(?:hotel|trip|airport|gate|currently|travell?ing|this week|"
    r"meeting room|conference room|staying at|visiting)\b",
    re.IGNORECASE,
)
_ENGAGEMENT = re.compile(
    r"\b(?:works? (?:on|with)|engagement|account|customer|client|project|teams?|workshop)\b"
    r"|\bon (?:a|the)\b.*\b(?:program(?:me)?|initiative|pilot|rollout|migration|launch|deal)\b",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DOMAIN = re.compile(r"^(?:[\w-]+\.)+[a-z]{2,}$", re.IGNORECASE)
_TRAILING_PAREN = re.compile(r"\s*\([^()]*\)\s*$")
_PUNCTUATION = re.compile(r"[\W_]+")
_LEGAL_SUFFIXES = frozenset(
    {"llp", "llc", "inc", "ltd", "corp", "corporation", "co", "gmbh", "plc"}
)
# A level code or employment status is not a title and never pairs with one.
_LEVEL_CODE = re.compile(r"^[a-z]{1,2}\d{1,2}$")
_STATUS = re.compile(
    r"\b(?:on leave|parental leave|promoted|promotion candidate|feedback due|sabbatical)\b",
    re.IGNORECASE,
)

# Relations between two claims that are reported. A containment ("Cloud
# Architect" vs "Cloud Architect Leader") is usually a restatement but may be a
# promotion, so it is kept and ranked after every real conflict.
_CONFLICT = "conflict"
_CONTAINED = "contained"


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _strip_extras(text: str) -> str:
    """Drop email addresses and a trailing parenthetical such as "(contractor)"."""
    text = _TRAILING_PAREN.sub("", _EMAIL.sub("", text))
    return text.strip(" ()[]<>,;-")


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(_PUNCTUATION.sub(" ", text.casefold()).split())


def _strip_legal(tokens: tuple[str, ...]) -> tuple[str, ...]:
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIXES:
        tokens = tokens[:-1]
    return tokens


def _spells(abbr: str, tokens: tuple[str, ...]) -> bool:
    """True if ``abbr`` is a leading slice of every token in order ("exco", "ec")."""
    if not tokens:
        return not abbr
    head = tokens[0]
    return any(
        abbr[:i] == head[:i] and _spells(abbr[i:], tokens[1:])
        for i in range(1, min(len(abbr), len(head)) + 1)
    )


def _same_org(tokens_1: tuple[str, ...], tokens_2: tuple[str, ...]) -> bool:
    """Same company named two ways, or a parent and its own unit."""
    base_1, base_2 = _strip_legal(tokens_1), _strip_legal(tokens_2)
    shorter, longer = sorted((base_1, base_2), key=len)
    if longer[: len(shorter)] == shorter:
        return True
    for short, full in ((base_1, tokens_2), (base_2, tokens_1)):
        if len(short) == 1 and any(
            len(long) > 1 and _spells(short[0], long) for long in (full, _strip_legal(full))
        ):
            return True
    return False


def _classify(predicate: str, obj: str) -> tuple[str, str | tuple[str, ...]]:
    """Return (kind, normalized value). Only claims of the same kind can conflict."""
    if predicate == "location":
        kind = "temporary" if _TEMPORARY_LOCATION.search(obj) else "home"
        return kind, _normalize(obj)
    if predicate == "org":
        if _ENGAGEMENT.search(obj):
            return "engagement", _normalize(obj)
        # Drop email addresses so "Example Corp (jordan@examplecorp.com)"
        # compares equal to "Example Corp".
        name = _strip_extras(obj)
        if not name or _DOMAIN.match(name):
            return "email", _normalize(obj)
        return "name", _tokens(name)
    if predicate == "title":
        text = _strip_extras(obj) or obj
        tokens = _tokens(text)
        if _STATUS.search(text) or (len(tokens) == 1 and _LEVEL_CODE.match(tokens[0])):
            return "status", tokens
        return "title", tokens
    return "", obj


def _relation(predicate: str, object_1: str, object_2: str) -> str | None:
    """Return _CONFLICT, _CONTAINED, or None when the two claims agree."""
    kind_1, value_1 = _classify(predicate, object_1)
    kind_2, value_2 = _classify(predicate, object_2)
    if kind_1 != kind_2 or kind_1 == "status" or value_1 == value_2:
        return None
    if predicate == "org" and kind_1 == "name":
        return None if _same_org(value_1, value_2) else _CONFLICT
    if predicate == "title":
        # Whole tokens, order-insensitive, no stemming.
        set_1, set_2 = set(value_1), set(value_2)
        if set_1 == set_2:
            return None
        return _CONTAINED if set_1 <= set_2 or set_2 <= set_1 else _CONFLICT
    return _CONFLICT


def find_contradictions_tier1(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """SELECT c1.id AS id1, c2.id AS id2,
                  c1.subject_id, c1.predicate,
                  c1.object AS object1, c2.object AS object2,
                  c1.confidence AS conf1, c2.confidence AS conf2,
                  e.name AS subject_name
           FROM claims c1
           JOIN claims c2 ON c1.subject_id = c2.subject_id
               AND c1.predicate = c2.predicate
               AND c1.object != c2.object
               AND c1.id < c2.id
           LEFT JOIN entities e ON c1.subject_id = e.id
           WHERE c1.predicate NOT LIKE 'behavioral:%'"""
    ).fetchall()

    ranked = []
    for row in rows:
        relation = _relation(row["predicate"], row["object1"], row["object2"])
        if relation is None:
            continue
        result = {
            "claim_id_1": row["id1"],
            "claim_id_2": row["id2"],
            "subject": row["subject_name"] or row["subject_id"],
            "predicate": row["predicate"],
            "object_1": row["object1"],
            "object_2": row["object2"],
            "confidence_1": row["conf1"],
            "confidence_2": row["conf2"],
        }
        key = (
            relation == _CONTAINED,
            _FIELD_RANK.get(row["predicate"], len(_FIELD_RANK)),
            -max(row["conf1"], row["conf2"]),
            row["id1"],
            row["id2"],
        )
        ranked.append((key, result))
    ranked.sort(key=lambda item: item[0])
    return [result for _, result in ranked[:MAX_CONTRADICTIONS]]


def find_contradictions_tier3(conn: sqlite3.Connection, llm: LLMPort) -> list[dict]:
    tier1 = find_contradictions_tier1(conn)

    for item in tier1:
        prompt = (
            f"Do these two claims contradict each other?\n"
            f"1. {item['subject']} {item['predicate']} {item['object_1']}\n"
            f"2. {item['subject']} {item['predicate']} {item['object_2']}\n"
            f"Explain briefly."
        )
        item["explanation"] = llm.complete(prompt)

    return tier1
