from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from patina.style.observer import StyleObservation, observe_sent_messages
from patina.style.patterns import detect_patterns


def consolidate_profile(observations: list[StyleObservation]) -> str:
    messages = [obs.text for obs in observations]
    patterns = detect_patterns(messages)
    return json.dumps(
        {
            "avg_length": patterns.avg_length,
            "greeting": patterns.greeting,
            "sign_off": patterns.sign_off,
            "formality": round(patterns.formality, 3),
            "emoji_rate": round(patterns.emoji_rate, 3),
            "question_rate": round(patterns.question_rate, 3),
            "sample_count": patterns.sample_count,
        }
    )


def _upsert_style_profile(
    conn: sqlite3.Connection,
    entity_id: str,
    profile_json: str,
    sample_count: int,
) -> None:
    now = datetime.now(UTC).isoformat()
    conn.execute(
        """INSERT INTO style_profiles (entity_id, profile, sample_count, last_updated)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(entity_id) DO UPDATE SET
               profile = excluded.profile,
               sample_count = excluded.sample_count,
               last_updated = excluded.last_updated""",
        (entity_id, profile_json, sample_count, now),
    )
    conn.commit()


def build_all_profiles(conn: sqlite3.Connection, user_entity_id: str) -> int:
    observations = observe_sent_messages(conn, user_entity_id)
    if not observations:
        return 0

    by_recipient: dict[str | None, list[StyleObservation]] = {}
    for obs in observations:
        by_recipient.setdefault(obs.recipient_entity_id, []).append(obs)

    count = 0

    all_profile = consolidate_profile(observations)
    _upsert_style_profile(conn, user_entity_id, all_profile, len(observations))
    count += 1

    for recipient_id, obs_list in by_recipient.items():
        if recipient_id is None:
            continue
        # Guard: skip if entity no longer exists (e.g. cleaned up)
        exists = conn.execute("SELECT 1 FROM entities WHERE id=?", (recipient_id,)).fetchone()
        if not exists:
            continue
        profile = consolidate_profile(obs_list)
        _upsert_style_profile(conn, recipient_id, profile, len(obs_list))
        count += 1

    return count
