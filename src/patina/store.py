from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DEFAULT_HOME = Path.home() / ".patina"

_SCHEMA_VERSION = 3

_TABLES = """
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    aliases TEXT,
    metadata TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    decay_rate REAL DEFAULT 0.02,
    is_owner INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL REFERENCES entities(id),
    predicate TEXT NOT NULL,
    object_id TEXT NOT NULL REFERENCES entities(id),
    confidence REAL DEFAULT 0.5,
    first_seen TEXT NOT NULL,
    last_confirmed TEXT NOT NULL,
    source_ids TEXT
);

CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL REFERENCES entities(id),
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    first_asserted TEXT NOT NULL,
    last_confirmed TEXT NOT NULL,
    decay_rate REAL DEFAULT 0.02,
    source_ids TEXT
);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    channel_id TEXT,
    thread_id TEXT,
    timestamp REAL NOT NULL,
    sender_entity_id TEXT REFERENCES entities(id),
    text TEXT,
    metadata TEXT,
    ingested_at TEXT NOT NULL,
    processed INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    observation_id TEXT REFERENCES observations(id),
    action TEXT NOT NULL,
    acted_at TEXT NOT NULL,
    latency_seconds REAL,
    context TEXT
);

CREATE TABLE IF NOT EXISTS objectives (
    id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    keywords TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS predictions (
    id TEXT PRIMARY KEY,
    entity_id TEXT REFERENCES entities(id),
    prediction_type TEXT NOT NULL,
    prediction TEXT NOT NULL,
    confidence REAL NOT NULL,
    outcome TEXT DEFAULT 'pending',
    outcome_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS style_exemplars (
    id TEXT PRIMARY KEY,
    sender_entity_id TEXT REFERENCES entities(id),
    recipient_entity_id TEXT REFERENCES entities(id),
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    timestamp REAL NOT NULL,
    metadata TEXT
);

CREATE TABLE IF NOT EXISTS style_profiles (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id),
    profile TEXT NOT NULL,
    sample_count INTEGER DEFAULT 0,
    last_updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_queue (
    id TEXT PRIMARY KEY,
    action_type TEXT NOT NULL,
    target_observation_id TEXT REFERENCES observations(id),
    target_entity_id TEXT REFERENCES entities(id),
    payload TEXT,
    confidence REAL NOT NULL,
    status TEXT DEFAULT 'proposed',
    autonomy_level INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS journal (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    body TEXT NOT NULL,
    entry_type TEXT DEFAULT 'note',
    processed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS anti_patterns (
    id TEXT PRIMARY KEY,
    from_level INTEGER NOT NULL,
    pattern_type TEXT NOT NULL,
    text_keywords TEXT,
    sender_tier TEXT,
    context TEXT,
    wrong_action TEXT NOT NULL,
    correct_action TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autonomy_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    level INTEGER NOT NULL DEFAULT 0,
    frozen_until TEXT,
    last_advanced TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    timestamp REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS watched_senders (
    user_id TEXT PRIMARY KEY,
    alias TEXT NOT NULL,
    display_name TEXT,
    reason TEXT,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watched_channels (
    channel_id TEXT PRIMARY KEY,
    channel_name TEXT NOT NULL,
    reason TEXT,
    priority TEXT DEFAULT 'normal',
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS migrations (
    name TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""

_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts
    USING fts5(text, content=observations, content_rowid=rowid);

CREATE VIRTUAL TABLE IF NOT EXISTS journal_fts
    USING fts5(body, content=journal, content_rowid=rowid);

CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts
    USING fts5(predicate, object, content=claims, content_rowid=rowid);
"""

_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS observations_ai AFTER INSERT ON observations BEGIN
    INSERT INTO observations_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS observations_ad AFTER DELETE ON observations BEGIN
    INSERT INTO observations_fts(observations_fts, rowid, text)
        VALUES ('delete', old.rowid, old.text);
END;
CREATE TRIGGER IF NOT EXISTS observations_au AFTER UPDATE ON observations BEGIN
    INSERT INTO observations_fts(observations_fts, rowid, text)
        VALUES ('delete', old.rowid, old.text);
    INSERT INTO observations_fts(rowid, text) VALUES (new.rowid, new.text);
END;

CREATE TRIGGER IF NOT EXISTS journal_ai AFTER INSERT ON journal BEGIN
    INSERT INTO journal_fts(rowid, body) VALUES (new.rowid, new.body);
END;
CREATE TRIGGER IF NOT EXISTS journal_ad AFTER DELETE ON journal BEGIN
    INSERT INTO journal_fts(journal_fts, rowid, body)
        VALUES ('delete', old.rowid, old.body);
END;
CREATE TRIGGER IF NOT EXISTS journal_au AFTER UPDATE ON journal BEGIN
    INSERT INTO journal_fts(journal_fts, rowid, body)
        VALUES ('delete', old.rowid, old.body);
    INSERT INTO journal_fts(rowid, body) VALUES (new.rowid, new.body);
END;
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_entities_type_name ON entities(type, name);
CREATE INDEX IF NOT EXISTS idx_rel_subject ON relationships(subject_id);
CREATE INDEX IF NOT EXISTS idx_rel_object ON relationships(object_id);
CREATE INDEX IF NOT EXISTS idx_rel_predicate ON relationships(predicate);
CREATE INDEX IF NOT EXISTS idx_claims_subject ON claims(subject_id);
CREATE INDEX IF NOT EXISTS idx_claims_predicate ON claims(predicate);
CREATE INDEX IF NOT EXISTS idx_obs_source ON observations(source);
CREATE INDEX IF NOT EXISTS idx_obs_timestamp ON observations(timestamp);
CREATE INDEX IF NOT EXISTS idx_obs_sender ON observations(sender_entity_id);
CREATE INDEX IF NOT EXISTS idx_obs_processed ON observations(processed);
CREATE INDEX IF NOT EXISTS idx_decisions_obs ON decisions(observation_id);
CREATE INDEX IF NOT EXISTS idx_decisions_action ON decisions(action);
CREATE INDEX IF NOT EXISTS idx_action_queue_status ON action_queue(status);
CREATE INDEX IF NOT EXISTS idx_conversations_channel_ts ON conversations(channel, timestamp DESC);
"""


def get_db_path(home: Path | None = None) -> Path:
    home = home or DEFAULT_HOME
    home.mkdir(parents=True, exist_ok=True)
    return home / "store.db"


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path) -> None:
    conn = connect(db_path)
    try:
        conn.executescript(_TABLES)
        conn.executescript(_FTS)
        conn.executescript(_FTS_TRIGGERS)
        conn.executescript(_INDEXES)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
            (_SCHEMA_VERSION,),
        )
        conn.commit()
    finally:
        conn.close()


def run_pending_migrations(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT 1 FROM migrations WHERE name = 'fix_datamark_whitespace_v1'"
    ).fetchone()
    if not row:
        cursor = conn.execute(
            "UPDATE observations SET text = REPLACE(text, CHAR(57344), ' ') "
            "WHERE text LIKE '%' || CHAR(57344) || '%'"
        )
        affected = cursor.rowcount

        conn.execute("INSERT INTO observations_fts(observations_fts) VALUES('rebuild')")

        conn.execute(
            "INSERT INTO migrations (name, applied_at) "
            "VALUES ('fix_datamark_whitespace_v1', datetime('now'))"
        )
        conn.commit()

        if affected > 0:
            print(f"Migration fix_datamark_whitespace_v1: fixed {affected} observations")

    row = conn.execute("SELECT 1 FROM migrations WHERE name = 'rebuild_journal_fts_v1'").fetchone()
    if not row:
        conn.execute("INSERT INTO journal_fts(journal_fts) VALUES('rebuild')")
        conn.execute(
            "INSERT INTO migrations (name, applied_at) "
            "VALUES ('rebuild_journal_fts_v1', datetime('now'))"
        )
        conn.commit()

    row = conn.execute("SELECT 1 FROM migrations WHERE name = 'add_kv_table_v1'").fetchone()
    if not row:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS kv (    key TEXT PRIMARY KEY,    value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO migrations (name, applied_at) VALUES ('add_kv_table_v1', datetime('now'))"
        )
        conn.commit()

    row = conn.execute(
        "SELECT 1 FROM migrations WHERE name = 'deduplicate_observations_v1'"
    ).fetchone()
    if not row:
        score = (
            "(CASE WHEN channel_id IS NOT NULL AND channel_id != ''"
            " THEN 1 ELSE 0 END"
            " + CASE WHEN thread_id IS NOT NULL AND thread_id != ''"
            " THEN 1 ELSE 0 END)"
        )
        win = (
            f"PARTITION BY source, timestamp, sender_entity_id, text"
            f" ORDER BY {score} DESC, rowid ASC"
        )
        victims = conn.execute(
            f"""SELECT id AS victim_id, survivor_id FROM (
                SELECT id,
                    ROW_NUMBER() OVER ({win}) AS rn,
                    FIRST_VALUE(id) OVER ({win}) AS survivor_id
                FROM observations
            ) WHERE rn > 1"""
        ).fetchall()

        deleted = 0
        if victims:
            id_map = {r["victim_id"]: r["survivor_id"] for r in victims}

            conn.execute(
                "CREATE TEMP TABLE _dedup_map "
                "(victim_id TEXT PRIMARY KEY, survivor_id TEXT NOT NULL)"
            )
            conn.executemany(
                "INSERT INTO _dedup_map VALUES (?, ?)",
                list(id_map.items()),
            )

            conn.execute(
                """UPDATE decisions SET observation_id = (
                    SELECT survivor_id FROM _dedup_map
                    WHERE victim_id = decisions.observation_id
                ) WHERE observation_id IN (SELECT victim_id FROM _dedup_map)"""
            )

            conn.execute(
                """UPDATE action_queue SET target_observation_id = (
                    SELECT survivor_id FROM _dedup_map
                    WHERE victim_id = action_queue.target_observation_id
                ) WHERE target_observation_id IN (SELECT victim_id FROM _dedup_map)"""
            )

            for cr in conn.execute(
                "SELECT id, source_ids FROM claims WHERE source_ids IS NOT NULL"
            ).fetchall():
                sids = json.loads(cr["source_ids"])
                updated = list(dict.fromkeys(id_map.get(s, s) for s in sids))
                if updated != sids:
                    conn.execute(
                        "UPDATE claims SET source_ids = ? WHERE id = ?",
                        (json.dumps(updated), cr["id"]),
                    )

            for rr in conn.execute(
                "SELECT id, source_ids FROM relationships WHERE source_ids IS NOT NULL"
            ).fetchall():
                sids = json.loads(rr["source_ids"])
                updated = list(dict.fromkeys(id_map.get(s, s) for s in sids))
                if updated != sids:
                    conn.execute(
                        "UPDATE relationships SET source_ids = ? WHERE id = ?",
                        (json.dumps(updated), rr["id"]),
                    )

            conn.execute("DELETE FROM observations WHERE id IN (SELECT victim_id FROM _dedup_map)")
            deleted = len(id_map)

            conn.execute("DROP TABLE _dedup_map")

            conn.execute("INSERT INTO observations_fts(observations_fts) VALUES('rebuild')")

        conn.execute(
            "INSERT INTO migrations (name, applied_at) "
            "VALUES ('deduplicate_observations_v1', datetime('now'))"
        )
        conn.commit()

        if deleted > 0:
            print(
                f"Migration deduplicate_observations_v1: removed {deleted} duplicate observations"
            )


def kv_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def kv_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO kv (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
