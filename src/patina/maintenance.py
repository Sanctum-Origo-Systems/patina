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


_GRAMMAR_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "for",
        "nor",
        "so",
        "yet",
        "in",
        "on",
        "at",
        "to",
        "of",
        "by",
        "with",
        "from",
        "into",
        "about",
        "through",
        "during",
        "before",
        "after",
        "between",
        "under",
        "over",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "has",
        "have",
        "had",
        "do",
        "does",
        "did",
        "would",
        "could",
        "should",
        "might",
        "not",
        "no",
        "that",
        "this",
        "who",
        "whom",
        "which",
        "what",
        "offered",
        "said",
        "mentioned",
        "asked",
        "told",
        "suggested",
    }
)

_NON_NAME_NOUNS = frozenset(
    {
        "office",
        "team",
        "project",
        "employee",
        "integration",
        "support",
        "meeting",
        "review",
        "feedback",
        "department",
        "group",
    }
)


_SLACK_ID_RE = re.compile(r"^[UW](?=[A-Z0-9]*\d)[A-Z0-9]{8,10}$")
_SLACK_ID_EXTRACT_RE = re.compile(r"^(?:slack:)?([UW][A-Z0-9]{4,})$", re.IGNORECASE)
_HANDLE_RE = re.compile(r"^[a-z][a-z0-9_]{1,}$")


def _collect_slack_ids(tokens: list[str]) -> set[str]:
    ids: set[str] = set()
    for token in tokens:
        m = _SLACK_ID_EXTRACT_RE.match(token.strip())
        if m:
            ids.add(m.group(1).upper())
    return ids


def _collect_emails(tokens: list[str]) -> set[str]:
    return {t.strip().lower() for t in tokens if "@" in t.strip()}


def is_plausible_person_name(name: str) -> bool:
    if not name or len(name) < 3 or len(name) > 50:
        return False
    if _SLACK_ID_RE.match(name):
        return True
    if any(c in name for c in "()[]/@:."):
        return False
    if name.isupper():
        return False
    words = name.split()
    if len(words) > 4:
        return False
    if sum(1 for w in words if w[0].isupper()) < 1:
        return False
    lower_words = {w.lower().rstrip(".,;!?") for w in words}
    if lower_words & _GRAMMAR_WORDS:
        return False
    if lower_words & _NON_NAME_NOUNS:
        return False
    return True


def _name_type_rank(name: str) -> int:
    """Rank: full name (0) > handle (1) > email (2) > raw Slack ID (3)."""
    if " " in name and is_plausible_person_name(name):
        return 0
    if "@" in name:
        return 2
    if _SLACK_ID_RE.match(name):
        return 3
    return 1


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


def find_dedup_candidates(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT id, name, aliases FROM entities WHERE is_owner = 0").fetchall()

    entities = []
    for r in rows:
        aliases = json.loads(r["aliases"] or "[]")
        entities.append(
            {
                "id": r["id"],
                "name": r["name"],
                "aliases": aliases,
            }
        )

    if not entities:
        return {"candidates": [], "needs_review": []}

    needs_review = []
    clean = []
    for ent in entities:
        all_tokens = [ent["name"]] + ent["aliases"]
        if len(_collect_slack_ids(all_tokens)) > 1:
            needs_review.append({**ent, "reason": "multiple Slack IDs"})
        else:
            clean.append(ent)
    entities = clean

    if not entities:
        return {"candidates": [], "needs_review": needs_review}

    sender_ids = {
        r["sender_entity_id"]
        for r in conn.execute(
            "SELECT DISTINCT sender_entity_id FROM observations WHERE sender_entity_id IS NOT NULL"
        ).fetchall()
    }

    name_by_handle: dict[str, list[dict]] = {}
    for ent in entities:
        key = ent["name"].strip().lower()
        if _HANDLE_RE.match(key) and not _SLACK_ID_RE.match(key.upper()):
            name_by_handle.setdefault(key, []).append(ent)

    alias_holders_by_handle: dict[str, list[dict]] = {}
    for ent in entities:
        if _name_type_rank(ent["name"]) != 0:
            continue
        for alias in ent["aliases"]:
            akey = alias.strip().lower()
            if _HANDLE_RE.match(akey) and not _SLACK_ID_RE.match(akey.upper()):
                alias_holders_by_handle.setdefault(akey, []).append(ent)

    ambiguous_handle_ids: set[str] = set()
    for handle_key, holders in alias_holders_by_handle.items():
        if len(holders) > 1:
            for named_ent in name_by_handle.get(handle_key, []):
                if named_ent["id"] not in ambiguous_handle_ids:
                    ambiguous_handle_ids.add(named_ent["id"])
                    needs_review.append({**named_ent, "reason": "ambiguous handle alias"})

    if ambiguous_handle_ids:
        entities = [e for e in entities if e["id"] not in ambiguous_handle_ids]

    if not entities:
        return {"candidates": [], "needs_review": needs_review}

    entity_hard_ids = []
    for ent in entities:
        all_tokens = [ent["name"]] + ent["aliases"]
        entity_hard_ids.append(
            {
                "slack_ids": _collect_slack_ids(all_tokens),
                "emails": _collect_emails(all_tokens),
            }
        )

    ident_map: dict[str, list[int]] = {}
    for i, ent in enumerate(entities):
        seen: set[str] = set()
        for token in [ent["name"]] + ent["aliases"]:
            key = token.strip().lower()
            if key and len(key) >= 2 and key not in seen:
                seen.add(key)
                is_foreign_handle = (
                    token != ent["name"]
                    and _HANDLE_RE.match(key)
                    and not _SLACK_ID_RE.match(key.upper())
                )
                if is_foreign_handle:
                    named = [
                        n
                        for n in name_by_handle.get(key, [])
                        if n["id"] not in ambiguous_handle_ids
                    ]
                    holders = alias_holders_by_handle.get(key, [])
                    if not (len(named) == 1 and named[0]["id"] in sender_ids and len(holders) == 1):
                        continue
                ident_map.setdefault(key, []).append(i)

    parent = list(range(len(entities)))
    group_slack = [h["slack_ids"].copy() for h in entity_hard_ids]
    group_emails = [h["emails"].copy() for h in entity_hard_ids]

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: int, b: int) -> None:
        ra, rb = _find(a), _find(b)
        if ra == rb:
            return
        sa, sb = group_slack[ra], group_slack[rb]
        if sa and sb and sa.isdisjoint(sb):
            return
        ea, eb = group_emails[ra], group_emails[rb]
        if ea and eb and ea.isdisjoint(eb):
            return
        parent[ra] = rb
        group_slack[rb] |= sa
        group_emails[rb] |= ea

    pair_match: dict[tuple[int, int], str] = {}
    for ident, indices in ident_map.items():
        if len(indices) < 2:
            continue
        for j in range(1, len(indices)):
            a, b = indices[0], indices[j]
            pair = (min(a, b), max(a, b))
            if pair not in pair_match:
                pair_match[pair] = ident
            _union(a, b)

    groups_map: dict[int, list[int]] = {}
    for i in range(len(entities)):
        root = _find(i)
        groups_map.setdefault(root, []).append(i)

    candidates = []
    for indices in groups_map.values():
        if len(indices) < 2:
            continue

        group = [entities[i] for i in indices]

        obs_counts = {}
        for ent in group:
            obs_counts[ent["id"]] = conn.execute(
                "SELECT COUNT(*) AS c FROM observations WHERE sender_entity_id = ?",
                (ent["id"],),
            ).fetchone()["c"]

        sorted_group = sorted(
            group,
            key=lambda e: (
                _name_type_rank(e["name"]),
                -obs_counts[e["id"]],
            ),
        )
        keep = sorted_group[0]

        idx_set = set(indices)
        match_ident = ""
        for pair, ident in pair_match.items():
            if pair[0] in idx_set and pair[1] in idx_set:
                match_ident = ident
                break

        candidates.append(
            {
                "keep": keep,
                "drop": sorted_group[1:],
                "match_identifier": match_ident,
            }
        )

    return {"candidates": candidates, "needs_review": needs_review}


def _merge_aliases_collide(
    conn: sqlite3.Connection,
    keep_id: str,
    drop_id: str,
) -> bool:
    keep = conn.execute("SELECT name, aliases FROM entities WHERE id = ?", (keep_id,)).fetchone()
    drop = conn.execute("SELECT name, aliases FROM entities WHERE id = ?", (drop_id,)).fetchone()
    if not keep or not drop:
        return False

    keep_aliases = set(json.loads(keep["aliases"] or "[]"))
    drop_aliases = set(json.loads(drop["aliases"] or "[]"))
    new_aliases = (drop_aliases | {drop["name"]}) - keep_aliases - {keep["name"]}

    exclude_ids = {keep_id, drop_id}
    rows = conn.execute("SELECT id, name, aliases FROM entities").fetchall()
    for alias in new_aliases:
        norm = _normalize_for_dedup(alias)
        if not norm:
            continue
        for r in rows:
            if r["id"] in exclude_ids:
                continue
            if _normalize_for_dedup(r["name"]) == norm:
                return True
            for stored in json.loads(r["aliases"] or "[]"):
                if _normalize_for_dedup(stored) == norm:
                    return True
    return False


def dedup_entities(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
) -> dict:
    dedup_result = find_dedup_candidates(conn)
    candidates = dedup_result["candidates"]

    result = {
        "groups": len(candidates),
        "entities_merged": 0,
        "merges": [],
        "skipped": [],
        "needs_review": dedup_result["needs_review"],
    }

    for group in candidates:
        keep = group["keep"]
        match_id = group.get("match_identifier", "")
        for drop in group["drop"]:
            if _merge_aliases_collide(conn, keep["id"], drop["id"]):
                result["skipped"].append(
                    {
                        "keep_id": keep["id"],
                        "keep_name": keep["name"],
                        "drop_id": drop["id"],
                        "drop_name": drop["name"],
                        "reason": "alias collision",
                    }
                )
                continue
            merge_result = merge_entities(conn, keep["id"], drop["id"], dry_run=dry_run)
            merge_result["match_identifier"] = match_id
            result["merges"].append(merge_result)
            result["entities_merged"] += 1

    return result


def prune_non_person_entities(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
) -> dict:
    rows = conn.execute("SELECT id, name, type FROM entities WHERE is_owner = 0").fetchall()

    sender_ids = {
        r["sender_entity_id"]
        for r in conn.execute(
            "SELECT DISTINCT sender_entity_id FROM observations WHERE sender_entity_id IS NOT NULL"
        ).fetchall()
    }

    to_prune = []
    for r in rows:
        if r["id"] in sender_ids:
            continue
        if is_non_person(r["name"]):
            to_prune.append({"id": r["id"], "name": r["name"]})
        elif r["type"] == "person" and not is_plausible_person_name(r["name"]):
            to_prune.append({"id": r["id"], "name": r["name"]})

    if dry_run and to_prune:
        eids = [ent["id"] for ent in to_prune]
        ph = ",".join("?" for _ in eids)
        claims_count = conn.execute(
            f"SELECT COUNT(*) AS c FROM claims WHERE subject_id IN ({ph})", eids
        ).fetchone()["c"]
        rels_count = conn.execute(
            f"SELECT COUNT(*) AS c FROM relationships "
            f"WHERE subject_id IN ({ph}) OR object_id IN ({ph})",
            eids + eids,
        ).fetchone()["c"]
        return {
            "pruned": len(to_prune),
            "entities": to_prune,
            "claims_removed": claims_count,
            "relationships_removed": rels_count,
        }

    result = {
        "pruned": len(to_prune),
        "entities": to_prune,
    }

    if not to_prune:
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
