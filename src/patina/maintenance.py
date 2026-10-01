"""Entity and data maintenance: merge, dedup, prune, reprocess."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from patina.graph import normalize_name as _graph_normalize

_NON_PERSON_RE = re.compile(
    r"\b("
    r"bot|Bot|BOT"
    r"|room|Room"
    r"|calendar|Calendar"
    r"|conference|Conference"
    r"|sync|Sync"
    r"|standup|Standup"
    r"|noreply|no-reply|no\.reply"
    r"|automated|Automated"
    r"|service|Service"
    r"|system|System"
    r"|notification|Notification"
    r"|webhook|Webhook"
    r"|alert|Alert"
    r")\b"
)

_NON_PERSON_SUFFIXES = (
    " bot",
    " Bot",
    " BOT",
    " Room",
    " room",
    " Calendar",
    " calendar",
    " (bot)",
    " (Bot)",
)

_NON_PERSON_PREFIXES = (
    "Bot ",
    "bot ",
    "noreply",
    "no-reply",
)


def is_non_person(name: str) -> bool:
    if not name or len(name) < 2:
        return False
    if any(name.endswith(s) for s in _NON_PERSON_SUFFIXES):
        return True
    if any(name.startswith(s) for s in _NON_PERSON_PREFIXES):
        return True
    if "@" in name and not any(c == " " for c in name):
        local = name.split("@")[0]
        if _NON_PERSON_RE.search(local):
            return True
    return False


def _normalize_for_dedup(name: str) -> str:
    norm = _graph_normalize(name)
    norm = re.sub(r"[._\-]", " ", norm)
    return " ".join(norm.split())


def backup_store(db_path: Path) -> Path:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    backup_path = db_path.with_suffix(f".db.bak.{ts}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def rewire_entity_references(
    conn: sqlite3.Connection,
    keep_id: str,
    drop_id: str,
) -> dict:
    counts = {
        "observations": 0,
        "claims": 0,
        "relationships": 0,
        "predictions": 0,
        "style_exemplars": 0,
        "action_queue": 0,
    }

    cur = conn.execute(
        "UPDATE observations SET sender_entity_id = ? WHERE sender_entity_id = ?",
        (keep_id, drop_id),
    )
    counts["observations"] = cur.rowcount

    cur = conn.execute(
        "UPDATE claims SET subject_id = ? WHERE subject_id = ?",
        (keep_id, drop_id),
    )
    counts["claims"] = cur.rowcount

    cur = conn.execute(
        "UPDATE relationships SET subject_id = ? WHERE subject_id = ?",
        (keep_id, drop_id),
    )
    r_subj = cur.rowcount
    cur = conn.execute(
        "UPDATE relationships SET object_id = ? WHERE object_id = ?",
        (keep_id, drop_id),
    )
    counts["relationships"] = r_subj + cur.rowcount

    conn.execute(
        "DELETE FROM relationships WHERE subject_id = ? AND object_id = ?",
        (keep_id, keep_id),
    )

    cur = conn.execute(
        "UPDATE predictions SET entity_id = ? WHERE entity_id = ?",
        (keep_id, drop_id),
    )
    counts["predictions"] = cur.rowcount

    cur = conn.execute(
        "UPDATE style_exemplars SET sender_entity_id = ? WHERE sender_entity_id = ?",
        (keep_id, drop_id),
    )
    se = cur.rowcount
    cur = conn.execute(
        "UPDATE style_exemplars SET recipient_entity_id = ? WHERE recipient_entity_id = ?",
        (keep_id, drop_id),
    )
    counts["style_exemplars"] = se + cur.rowcount

    existing_profile = conn.execute(
        "SELECT 1 FROM style_profiles WHERE entity_id = ?", (keep_id,)
    ).fetchone()
    if existing_profile:
        conn.execute("DELETE FROM style_profiles WHERE entity_id = ?", (drop_id,))
    else:
        conn.execute(
            "UPDATE style_profiles SET entity_id = ? WHERE entity_id = ?",
            (keep_id, drop_id),
        )

    cur = conn.execute(
        "UPDATE action_queue SET target_entity_id = ? WHERE target_entity_id = ?",
        (keep_id, drop_id),
    )
    counts["action_queue"] = cur.rowcount

    return counts


def merge_entities(
    conn: sqlite3.Connection,
    keep_id: str,
    drop_id: str,
    *,
    dry_run: bool = False,
) -> dict:
    keep = conn.execute("SELECT * FROM entities WHERE id = ?", (keep_id,)).fetchone()
    drop = conn.execute("SELECT * FROM entities WHERE id = ?", (drop_id,)).fetchone()

    if not keep:
        raise ValueError(f"Entity '{keep_id}' not found")
    if not drop:
        raise ValueError(f"Entity '{drop_id}' not found")

    keep_aliases = json.loads(keep["aliases"] or "[]")
    drop_aliases = json.loads(drop["aliases"] or "[]")
    merged_aliases = list(set(keep_aliases + drop_aliases + [drop["name"]]))

    obs_count = conn.execute(
        "SELECT COUNT(*) AS c FROM observations WHERE sender_entity_id = ?",
        (drop_id,),
    ).fetchone()["c"]
    claim_count = conn.execute(
        "SELECT COUNT(*) AS c FROM claims WHERE subject_id = ?",
        (drop_id,),
    ).fetchone()["c"]
    rel_count = conn.execute(
        "SELECT COUNT(*) AS c FROM relationships WHERE subject_id = ? OR object_id = ?",
        (drop_id, drop_id),
    ).fetchone()["c"]

    result = {
        "keep_id": keep_id,
        "keep_name": keep["name"],
        "drop_id": drop_id,
        "drop_name": drop["name"],
        "observations_moved": obs_count,
        "claims_moved": claim_count,
        "relationships_moved": rel_count,
    }

    if dry_run:
        return result

    rewire_entity_references(conn, keep_id, drop_id)

    conn.execute(
        "UPDATE entities SET aliases = ? WHERE id = ?",
        (json.dumps(merged_aliases), keep_id),
    )

    first_seen_keep = keep["first_seen"] or ""
    first_seen_drop = drop["first_seen"] or ""
    if first_seen_drop and (not first_seen_keep or first_seen_drop < first_seen_keep):
        conn.execute(
            "UPDATE entities SET first_seen = ? WHERE id = ?",
            (first_seen_drop, keep_id),
        )

    last_seen_keep = keep["last_seen"] or ""
    last_seen_drop = drop["last_seen"] or ""
    if last_seen_drop and last_seen_drop > last_seen_keep:
        conn.execute(
            "UPDATE entities SET last_seen = ? WHERE id = ?",
            (last_seen_drop, keep_id),
        )

    conn.execute("DELETE FROM entities WHERE id = ?", (drop_id,))
    conn.commit()

    return result


def find_dedup_candidates(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT id, name, aliases FROM entities WHERE is_owner = 0").fetchall()

    groups: dict[str, list[dict]] = {}
    for r in rows:
        norm = _normalize_for_dedup(r["name"])
        if not norm or len(norm) < 2:
            continue
        groups.setdefault(norm, []).append(
            {
                "id": r["id"],
                "name": r["name"],
                "aliases": json.loads(r["aliases"] or "[]"),
            }
        )

    alias_map: dict[str, str] = {}
    for r in rows:
        aliases = json.loads(r["aliases"] or "[]")
        for alias in aliases:
            norm_alias = _normalize_for_dedup(alias)
            if norm_alias and len(norm_alias) > 2:
                existing = alias_map.get(norm_alias)
                if existing and existing != r["id"]:
                    for key, group in groups.items():
                        ids = {e["id"] for e in group}
                        if existing in ids and r["id"] not in ids:
                            group.append(
                                {
                                    "id": r["id"],
                                    "name": r["name"],
                                    "aliases": aliases,
                                }
                            )
                            break
                else:
                    alias_map[norm_alias] = r["id"]

    candidates = []
    for norm, group in groups.items():
        if len(group) < 2:
            continue
        obs_counts = {}
        for ent in group:
            obs_counts[ent["id"]] = conn.execute(
                "SELECT COUNT(*) AS c FROM observations WHERE sender_entity_id = ?",
                (ent["id"],),
            ).fetchone()["c"]

        sorted_group = sorted(group, key=lambda e: obs_counts[e["id"]], reverse=True)
        keep = sorted_group[0]
        candidates.append(
            {
                "keep": keep,
                "drop": sorted_group[1:],
                "normalized_name": norm,
            }
        )

    return candidates


def dedup_entities(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
) -> dict:
    candidates = find_dedup_candidates(conn)

    result = {
        "groups": len(candidates),
        "entities_merged": 0,
        "merges": [],
    }

    for group in candidates:
        keep = group["keep"]
        for drop in group["drop"]:
            merge_result = merge_entities(conn, keep["id"], drop["id"], dry_run=dry_run)
            result["merges"].append(merge_result)
            result["entities_merged"] += 1

    return result


def prune_non_person_entities(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
) -> dict:
    rows = conn.execute("SELECT id, name FROM entities WHERE is_owner = 0").fetchall()

    to_prune = []
    for r in rows:
        if is_non_person(r["name"]):
            to_prune.append({"id": r["id"], "name": r["name"]})

    result = {
        "pruned": len(to_prune),
        "entities": to_prune,
    }

    if dry_run or not to_prune:
        return result

    for ent in to_prune:
        eid = ent["id"]
        conn.execute("DELETE FROM claims WHERE subject_id = ?", (eid,))
        conn.execute(
            "DELETE FROM relationships WHERE subject_id = ? OR object_id = ?",
            (eid, eid),
        )
        conn.execute(
            "UPDATE observations SET sender_entity_id = NULL WHERE sender_entity_id = ?",
            (eid,),
        )
        conn.execute("DELETE FROM predictions WHERE entity_id = ?", (eid,))
        conn.execute(
            "DELETE FROM style_exemplars WHERE sender_entity_id = ? OR recipient_entity_id = ?",
            (eid, eid),
        )
        conn.execute("DELETE FROM style_profiles WHERE entity_id = ?", (eid,))
        conn.execute(
            "UPDATE action_queue SET target_entity_id = NULL WHERE target_entity_id = ?",
            (eid,),
        )
        conn.execute("DELETE FROM entities WHERE id = ?", (eid,))

    conn.commit()
    return result


def prune_slack_link_entities(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
) -> dict:
    rows = conn.execute("SELECT id, name FROM entities WHERE type = 'reference'").fetchall()

    pipe_re = re.compile(r"\|")
    to_prune = [{"id": r["id"], "name": r["name"]} for r in rows if pipe_re.search(r["name"])]

    result = {
        "pruned": len(to_prune),
        "entities": to_prune,
    }

    if dry_run or not to_prune:
        return result

    for ent in to_prune:
        eid = ent["id"]
        conn.execute("DELETE FROM claims WHERE subject_id = ?", (eid,))
        conn.execute(
            "DELETE FROM relationships WHERE subject_id = ? OR object_id = ?",
            (eid, eid),
        )
        conn.execute("DELETE FROM predictions WHERE entity_id = ?", (eid,))
        conn.execute("DELETE FROM entities WHERE id = ?", (eid,))

    conn.commit()
    return result


def reprocess_observations(
    conn: sqlite3.Connection,
    *,
    since: str | None = None,
    source: str | None = None,
    dry_run: bool = False,
) -> dict:
    conditions = ["processed = 1"]
    params: list[str] = []

    if since:
        from datetime import datetime as dt

        ts = dt.fromisoformat(since).timestamp()
        conditions.append("timestamp >= ?")
        params.append(str(ts))

    if source:
        conditions.append("source = ?")
        params.append(source)

    where = " AND ".join(conditions)

    count = conn.execute(
        f"SELECT COUNT(*) AS c FROM observations WHERE {where}",
        params,
    ).fetchone()["c"]

    result = {"reset_count": count}

    if dry_run or count == 0:
        return result

    conn.execute(
        f"UPDATE observations SET processed = 0 WHERE {where}",
        params,
    )
    conn.commit()
    return result
