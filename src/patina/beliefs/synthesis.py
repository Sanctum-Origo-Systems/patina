from __future__ import annotations

import sqlite3
import time

from patina.llm import LLMPort


def find_convergence(
    conn: sqlite3.Connection, llm: LLMPort | None = None, *, days: int = 7
) -> list[dict]:
    cutoff = time.time() - (days * 86400)

    rows = conn.execute(
        """SELECT o.text, e.name AS sender_name
           FROM observations o
           LEFT JOIN entities e ON o.sender_entity_id = e.id
           WHERE o.timestamp >= ? AND o.text IS NOT NULL""",
        (cutoff,),
    ).fetchall()

    word_senders: dict[str, set[str]] = {}
    word_messages: dict[str, list[str]] = {}

    stop_words = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "about",
        "it",
        "its",
        "this",
        "that",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "our",
        "their",
        "and",
        "or",
        "but",
        "not",
        "no",
        "if",
        "then",
        "so",
        "just",
        "get",
        "got",
    }

    for row in rows:
        sender = row["sender_name"] or "unknown"
        words = set(row["text"].lower().split()) - stop_words
        for word in words:
            if len(word) < 4:
                continue
            word_senders.setdefault(word, set()).add(sender)
            word_messages.setdefault(word, []).append(row["text"])

    results: list[dict] = []
    seen_words: set[str] = set()

    for word, senders in sorted(word_senders.items(), key=lambda x: len(x[1]), reverse=True):
        if len(senders) < 3:
            continue
        if word in seen_words:
            continue
        seen_words.add(word)

        insight = None
        if llm is not None:
            messages = word_messages[word][:10]
            insight = llm.synthesize(
                messages,
                f"What are people saying about '{word}'?",
            )

        results.append(
            {
                "topic": word,
                "entities_involved": sorted(senders),
                "message_count": len(word_messages[word]),
                "insight": insight,
            }
        )

        if len(results) >= 10:
            break

    return results
