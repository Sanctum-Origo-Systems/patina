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
    r"\b(?:works? on|engagement|account|customer|client|project)\b|\bfor the\b.*\bteam\b",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_DOMAIN = re.compile(r"^(?:[\w-]+\.)+[a-z]{2,}$", re.IGNORECASE)


def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _classify(predicate: str, obj: str) -> tuple[str, str]:
    """Return (kind, normalized value). Only claims of the same kind can conflict."""
    if predicate == "location":
        kind = "temporary" if _TEMPORARY_LOCATION.search(obj) else "home"
        return kind, _normalize(obj)
    if predicate == "org":
        if _ENGAGEMENT.search(obj):
            return "engagement", _normalize(obj)
        # Drop email addresses so "Example Corp (jordan@examplecorp.com)"
        # compares equal to "Example Corp".
        name = _EMAIL.sub("", obj).replace("()", "").strip(" ()[]<>,;-")
        if not name or _DOMAIN.match(name):
            return "email", _normalize(obj)
        return "name", _normalize(name)
    return "", obj


def _is_conflict(predicate: str, object_1: str, object_2: str) -> bool:
    kind_1, value_1 = _classify(predicate, object_1)
    kind_2, value_2 = _classify(predicate, object_2)
    return kind_1 == kind_2 and value_1 != value_2


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

    results = [
        {
            "claim_id_1": row["id1"],
            "claim_id_2": row["id2"],
            "subject": row["subject_name"] or row["subject_id"],
            "predicate": row["predicate"],
            "object_1": row["object1"],
            "object_2": row["object2"],
            "confidence_1": row["conf1"],
            "confidence_2": row["conf2"],
        }
        for row in rows
        if _is_conflict(row["predicate"], row["object1"], row["object2"])
    ]
    results.sort(
        key=lambda r: (
            _FIELD_RANK.get(r["predicate"], len(_FIELD_RANK)),
            -max(r["confidence_1"], r["confidence_2"]),
            r["claim_id_1"],
            r["claim_id_2"],
        )
    )
    return results[:MAX_CONTRADICTIONS]


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
