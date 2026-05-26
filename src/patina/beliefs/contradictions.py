from __future__ import annotations

import sqlite3

from patina.llm import LLMPort


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
           LEFT JOIN entities e ON c1.subject_id = e.id"""
    ).fetchall()

    return [
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
    ]


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
