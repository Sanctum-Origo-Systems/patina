"""Entity and data maintenance: merge, dedup, prune, reprocess."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from patina.graph import _SLACK_ID_PAT as _SLACK_ID_RE
from patina.graph import (
    IDENTIFIER_PRECEDENCE,
    _is_multi_identity,
    identifier_type,
    normalize_name,
    resolve_entity_id,
)
from patina.graph import _name_type_rank as _graph_name_type_rank
from patina.graph import normalize_name as _graph_normalize
from patina.owner import normalize_alias
from patina.store import ensure_entity_alias_provenance_table, record_alias_provenance

_PROVENANCE_ADAPTER = "maintenance"


class StaleSnapshotError(Exception):
    """The store was modified between preview and confirm runs."""


def store_snapshot_token(conn: sqlite3.Connection) -> str:
    """Compute a fingerprint of entity-relevant tables for stale-plan detection."""
    rows = conn.execute("SELECT id, type, name, aliases FROM entities ORDER BY id").fetchall()
    h = hashlib.sha256()
    for r in rows:
        h.update(f"{r['id']}|{r['type']}|{r['name']}|{r['aliases']}".encode())
    return h.hexdigest()[:16]


def _check_snapshot_token(conn: sqlite3.Connection, token: str | None) -> None:
    if token is not None:
        current = store_snapshot_token(conn)
        if current != token:
            raise StaleSnapshotError(
                f"Store changed since preview (expected {token}, got {current})"
            )


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

_ORG_SUFFIX_WORDS = frozenset(
    {
        "newsletter",
        "events",
        "research",
        "services",
        "office",
        "department",
        "committee",
        "foundation",
        "institute",
        "association",
        "corporation",
        "corp",
        "inc",
        "llc",
        "ltd",
        "center",
        "centre",
        "bureau",
        "agency",
        "academy",
        "council",
        "society",
        "network",
        "solutions",
        "technologies",
        "labs",
        "consulting",
        "advisory",
        "media",
        "press",
        "publishing",
        "ventures",
        "capital",
        "holdings",
        "studio",
        "partners",
        "operations",
        "logistics",
        "analytics",
        "communications",
        "engagement",
        "outreach",
        "bot",
        "service",
        "notifications",
        "automation",
    }
)

_ROLE_NOUNS = frozenset(
    {
        "manager",
        "director",
        "coordinator",
        "specialist",
        "consultant",
        "advisor",
        "representative",
        "administrator",
        "supervisor",
        "officer",
        "lead",
        "head",
        "chief",
        "president",
        "executive",
        "architect",
        "planner",
        "strategist",
    }
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
    " Team",
    " team",
    " List",
    " list",
    " Group",
    " group",
)

_NON_PERSON_PREFIXES = (
    "Bot ",
    "bot ",
    "noreply",
    "no-reply",
    "donotreply",
    "do-not-reply",
    "do_not_reply",
)

_HYPHENATED_SERVICE_SUFFIXES = (
    "-bot",
    "-ci",
    "-noreply",
    "-commenter",
    "-automation",
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


_SLACK_ID_EXTRACT_RE = re.compile(r"^(?:slack:)?([UW][A-Z0-9]{4,})$", re.IGNORECASE)
_HANDLE_RE = re.compile(r"^[a-z][a-z0-9_]{1,}$")


def _collect_slack_ids(tokens: list[str]) -> set[str]:
    ids: set[str] = set()
    for token in tokens:
        m = _SLACK_ID_EXTRACT_RE.match(token.strip())
        if m and _SLACK_ID_RE.match(m.group(1).upper()):
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
    """Graph display-label rank; a spaced name must also look like a person."""
    return _graph_name_type_rank(name, is_display_name=is_plausible_person_name)


def is_non_person(name: str) -> bool:
    if not name or len(name) < 2:
        return False
    if name.startswith("/O=") or name.startswith("/o="):
        return True
    if any(name.endswith(s) for s in _NON_PERSON_SUFFIXES):
        return True
    if any(name.startswith(s) for s in _NON_PERSON_PREFIXES):
        return True
    if "@" in name and not any(c == " " for c in name):
        local = name.split("@")[0]
        if _NON_PERSON_RE.search(local):
            return True
    if (
        "-" in name
        and " " not in name
        and "@" not in name
        and name == name.lower()
        and any(name.endswith(s) for s in _HYPHENATED_SERVICE_SUFFIXES)
    ):
        return True
    return False


def is_organization(name: str) -> bool:
    if not name or len(name) < 2:
        return False
    words = name.split()
    if len(words) < 2:
        return False
    last = words[-1].lower().rstrip(".,;!?")
    return last in _ORG_SUFFIX_WORDS or last in _ROLE_NOUNS


_LEGACY_DN_RE = re.compile(r"^/[Oo]=")
_BARE_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _is_junk_sender_name(name: str) -> bool:
    if _LEGACY_DN_RE.match(name):
        return True
    if _BARE_EMAIL_RE.match(name):
        return True
    return False


_DN_HANDLE_RE = re.compile(
    r"/cn=[0-9a-f]{8}(?:-?[0-9a-f]{4}){3}-?[0-9a-f]{12}-(?P<handle>[^/=,]+)$",
    re.IGNORECASE,
)


def _dn_trailing_handle(dn: str) -> str | None:
    """Return the handle after the GUID in an Exchange DN, e.g. ...CN=<guid>-DBROOK."""
    m = _DN_HANDLE_RE.search(dn.strip())
    return m.group("handle") if m else None


_DN_SMTP_RE = re.compile(
    r"/cn=(?P<smtp>[^/\s]+@[^/\s]+)$",
    re.IGNORECASE,
)

_ORGANIZER_RE = re.compile(r"Organizer:\s*(.+?),\s*Attendees:")


def _dn_trailing_smtp(dn: str) -> str | None:
    """Return the SMTP address from the trailing CN of an Exchange DN."""
    m = _DN_SMTP_RE.search(dn.strip())
    return m.group("smtp") if m else None


def _normalize_for_dedup(name: str) -> str:
    norm = _graph_normalize(name)
    norm = re.sub(r"[._\-]", " ", norm)
    return " ".join(norm.split())


def _handle_fits_name(handle: str, full_name: str) -> bool:
    """Check if a handle is a plausible abbreviation of a full name."""
    parts = full_name.strip().lower().split()
    if len(parts) < 2:
        return False
    first = parts[0]
    surname = parts[-1]
    h = re.sub(r"[._\-]", "", handle.strip().lower())
    for length in range(3, len(surname) + 1):
        if h.endswith(surname[:length]):
            return True
    if h == first + surname[0]:
        return True
    return False


def _alias_provenance_is_added(conn: sqlite3.Connection, entity_id: str, alias: str) -> bool:
    """True when the latest provenance row for (entity_id, alias) is 'added'."""
    row = conn.execute(
        "SELECT action FROM entity_alias_provenance WHERE entity_id = ? AND alias = ?"
        " ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (entity_id, alias),
    ).fetchone()
    return bool(row) and row["action"] == "added"


def _record_alias_changes(
    conn: sqlite3.Connection,
    entity_id: str,
    *,
    added: Iterable[str] = (),
    removed: Iterable[str] = (),
) -> None:
    """Record maintenance provenance rows for aliases added to / removed from an entity."""
    for alias in dict.fromkeys(added):
        record_alias_provenance(conn, entity_id, alias, adapter=_PROVENANCE_ADAPTER, action="added")
    for alias in dict.fromkeys(removed):
        record_alias_provenance(
            conn, entity_id, alias, adapter=_PROVENANCE_ADAPTER, action="removed"
        )


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

    # Provenance follows the aliases to the survivor; rows are moved, not copied,
    # so the table's row count only grows for aliases with no live 'added' row.
    ensure_entity_alias_provenance_table(conn)
    conn.execute(
        "UPDATE entity_alias_provenance SET entity_id = ? WHERE entity_id = ?",
        (keep_id, drop_id),
    )
    gained = [
        a
        for a in merged_aliases
        if a not in keep_aliases and not _alias_provenance_is_added(conn, keep_id, a)
    ]
    lost = [a for a in keep_aliases + drop_aliases if a not in merged_aliases]
    _record_alias_changes(conn, keep_id, added=gained, removed=lost)

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


def _is_truncated_dn(value: str) -> bool:
    """Return True for legacy DNs that lack a CN component (never an identifier)."""
    return identifier_type(value.strip()) is None


SHAPE_HANDLE_ALIAS = "handle_alias_of_person"
SHAPE_FIRST_NAME = "first_name_only"

# Product and tool names that are never a person's first name (#542). Lowercase,
# matched case-insensitively; extending the list is a code change.
NON_PERSON_TOKENS = frozenset(
    {
        "asana",
        "confluence",
        "docker",
        "figma",
        "github",
        "gitlab",
        "jira",
        "notion",
        "outlook",
        "slack",
        "teams",
        "trello",
        "zoom",
    }
)


def _looks_like_first_name(name: str) -> bool:
    """A capitalized token that is not a known product or tool name."""
    token = name.strip()
    return token[:1].isupper() and token.lower() not in NON_PERSON_TOKENS


# Plural and mailer local parts that the word-bounded _NON_PERSON_RE misses (#546).
_AUTOMATED_LOCAL_RE = re.compile(
    r"(?:^|[._+-])("
    r"notifications|alerts|updates|digest|news"
    r"|bounces?|mailer-daemon|donotreply|do-not-reply|do_not_reply"
    r")(?:$|[._+-])",
    re.IGNORECASE,
)


def _is_automated_address(address: str) -> bool:
    """An email address or mailbox handle whose local part is notification-style."""
    local = address.strip().split("@", 1)[0]
    return bool(local) and bool(_NON_PERSON_RE.search(local) or _AUTOMATED_LOCAL_RE.search(local))


# Observation sources written before the per-adapter source names (#556).
_LEGACY_SOURCES = frozenset({"email"})

# Calendar invite and notification subject prefixes (#556).
_INVITE_SUBJECT_RE = re.compile(
    r"^\s*(?:"
    r"(?:updated |new )?invitation(?: from [^:]*)?"
    r"|accepted|declined|tentative|tentatively accepted"
    r"|cancell?ed(?: event| meeting)?"
    r"|(?:new|updated|cancell?ed) event"
    r"|meeting (?:request|update|cancell?ed)"
    r")\s*:",
    re.IGNORECASE,
)
_REPLY_SUBJECT_RE = re.compile(r"^\s*(?:re|aw|antw)\s*:", re.IGNORECASE)
_TEXT_SUBJECT_RE = re.compile(r"^\s*\[Subject:\s*(.*?)\]")


def _observation_subject(text: str | None, meta: dict) -> str:
    """The subject from metadata, a ``[Subject: ...]`` prefix, or the first text line."""
    if meta.get("subject"):
        return str(meta["subject"])
    text = text or ""
    m = _TEXT_SUBJECT_RE.match(text)
    if m:
        return m.group(1)
    return text.strip().split("\n", 1)[0]


def _is_automated_by_structure(conn: sqlite3.Connection, ent: dict, obs_rows: list) -> bool:
    """An address-less sender whose observations all look like legacy invites (#556).

    Needs at least two observations, every one from a legacy source, with an
    invite or notification subject, and none in a reply thread: a reply
    subject, an ``in_reply_to`` header, or a thread another sender posted in.
    """
    if len(obs_rows) < 2:
        return False
    for r in obs_rows:
        if r["source"] not in _LEGACY_SOURCES:
            return False
        meta = json.loads(r["metadata"] or "{}")
        subject = _observation_subject(r["text"], meta)
        if _REPLY_SUBJECT_RE.match(subject) or meta.get("in_reply_to"):
            return False
        if not _INVITE_SUBJECT_RE.match(subject):
            return False
        if (
            r["thread_id"]
            and conn.execute(
                "SELECT 1 FROM observations WHERE thread_id = ? AND id != ?"
                " AND (sender_entity_id IS NULL OR sender_entity_id != ?) LIMIT 1",
                (r["thread_id"], r["id"], ent["id"]),
            ).fetchone()
        ):
            return False
    return True


def _is_automated_sender(conn: sqlite3.Connection, ent: dict) -> bool:
    """A sender whose every known address is an automated, notification-style one (#546).

    Addresses come from the entity's email aliases, every email alias its
    provenance ever recorded, and the sender DN on each of its observations.
    Any other alias (Slack ID, DN, handle), a Slack sender or a DN with no
    readable mailbox counts as a person signal.

    With no address anywhere, the entity is automated only on structural
    evidence from its observations (#556): at least two, every one from a
    legacy source (``email``), every one an invite or notification subject
    ("Invitation: ...", "Accepted: ...") and none in a reply thread. Any one
    of these signals alone is not enough, and the name is never consulted.
    """
    name_key = normalize_name(ent["name"])
    addresses: list[str] = []
    for alias in ent["aliases"]:
        if "@" in alias:
            addresses.append(alias)
        elif normalize_name(normalize_alias(alias)) != name_key:
            return False

    ensure_entity_alias_provenance_table(conn)
    rows = conn.execute(
        "SELECT DISTINCT alias FROM entity_alias_provenance WHERE entity_id = ?",
        (ent["id"],),
    ).fetchall()
    addresses.extend(r["alias"] for r in rows if "@" in r["alias"])

    obs_rows = conn.execute(
        "SELECT id, source, thread_id, text, metadata FROM observations WHERE sender_entity_id = ?",
        (ent["id"],),
    ).fetchall()
    if not obs_rows:
        return False
    for r in obs_rows:
        meta = json.loads(r["metadata"] or "{}")
        if meta.get("sender_slack_id"):
            return False
        dn = meta.get("sender_dn")
        if dn:
            mailbox = _dn_trailing_smtp(dn) or _dn_trailing_handle(dn)
            if not mailbox:
                return False
            addresses.append(mailbox)

    if not addresses:
        return _is_automated_by_structure(conn, ent, obs_rows)
    return all(_is_automated_address(a) for a in addresses)


def _collect_dns(tokens: list[str]) -> set[str]:
    return {t.strip().upper() for t in tokens if identifier_type(t.strip()) == "dn"}


def _is_full_name(name: str) -> bool:
    return identifier_type(name.strip()) == "display_name"


def _is_first_name(name: str) -> bool:
    """A single capitalized word ("Dana"), unlike a lowercase handle ("dbrook")."""
    name = name.strip()
    return len(name) >= 2 and name.isalpha() and name[0].isupper() and name[1:].islower()


def _handle_alias_keys(p: dict) -> set[str]:
    keys = set()
    for alias in p["aliases"]:
        clean = normalize_alias(alias).strip().lstrip("@")
        if clean and identifier_type(clean) == "handle":
            keys.add(normalize_name(clean))
    return keys


def _find_person_shapes(
    conn: sqlite3.Connection,
    sender_ids: set[str],
    flagged_ids: set[str],
) -> tuple[list[tuple[str, str, str, str]], list[dict], set[str]]:
    """Find one person split across a handle- or first-name entity and a full-name one.

    Shape A (``handle_alias_of_person``): a handle-named person whose normalized
    name is a handle alias of exactly one full-name person merges into it; when
    the holder is a first-name-only person ("Dana" holding "dbrook") it goes to
    review instead, so the first-name entity never survives the handle.
    Shape B (``first_name_only``): a first-name-only person whose first name
    matches exactly one full-name person merges only on a shared Slack ID,
    email or full DN; otherwise it goes to review. Lowercase handles, product
    names and senders seen only from automated addresses still go to review
    but without the ``first_name_only`` label.

    Returns (merge pairs as (drop_id, keep_id, shape, match), review entries,
    entity ids to keep out of every merge group).
    """
    rows = conn.execute(
        "SELECT id, name, aliases, is_owner FROM entities WHERE type = 'person'"
    ).fetchall()
    persons = [
        {
            "id": r["id"],
            "name": r["name"],
            "aliases": json.loads(r["aliases"] or "[]"),
            "is_owner": bool(r["is_owner"]),
        }
        for r in rows
    ]
    full_names = [p for p in persons if _is_full_name(p["name"])]

    handle_holders: dict[str, list[dict]] = {}
    for p in full_names:
        for key in _handle_alias_keys(p):
            handle_holders.setdefault(key, []).append(p)

    # A first-name-only person whose only handle alias is another person's handle.
    first_name_handle_holders: dict[str, list[dict]] = {}
    for p in persons:
        if not _is_first_name(p["name"]):
            continue
        keys = _handle_alias_keys(p) - {normalize_name(p["name"])}
        if len(keys) == 1:
            first_name_handle_holders.setdefault(keys.pop(), []).append(p)

    first_name_holders: dict[str, list[dict]] = {}
    for p in full_names:
        words = normalize_name(p["name"]).split()
        if words:
            first_name_holders.setdefault(words[0], []).append(p)

    singles = [
        p
        for p in persons
        if not p["is_owner"]
        and p["id"] not in flagged_ids
        and identifier_type(p["name"].strip()) == "handle"
        and len(normalize_name(p["name"])) >= 2
    ]
    first_name_counts: dict[str, int] = {}
    for p in singles:
        key = normalize_name(p["name"])
        if key in first_name_holders:
            first_name_counts[key] = first_name_counts.get(key, 0) + 1

    pairs: list[tuple[str, str, str, str]] = []
    review: list[dict] = []
    excluded: set[str] = set()

    def _review(ent: dict, shape: str | None, reason: str, others: list[dict]) -> None:
        excluded.add(ent["id"])
        review.append(
            {
                "id": ent["id"],
                "name": ent["name"],
                "aliases": ent["aliases"],
                "reason": reason,
                **({"shape": shape} if shape else {}),
                "related": [o["name"] for o in others],
            }
        )

    def _blocker(ent: dict, other: dict) -> str | None:
        if ent["is_owner"] or other["is_owner"]:
            return "owner"
        if any(_is_multi_identity(e["name"], e["aliases"]) for e in (ent, other)):
            return "multi-identity"
        ent_tokens = [ent["name"]] + ent["aliases"]
        other_tokens = [other["name"]] + other["aliases"]
        ent_slack, other_slack = _collect_slack_ids(ent_tokens), _collect_slack_ids(other_tokens)
        if ent_slack and other_slack and ent_slack.isdisjoint(other_slack):
            return "conflicting Slack IDs"
        return None

    for ent in singles:
        key = normalize_name(ent["name"])
        tokens = [ent["name"]] + ent["aliases"]

        if key in first_name_holders:
            # Shape B: a name match alone never merges.
            matches = [m for m in first_name_holders[key] if m["id"] != ent["id"]]
            if len(matches) != 1 or first_name_counts[key] != 1:
                continue
            match = matches[0]
            match_tokens = [match["name"]] + match["aliases"]
            shared = (
                (_collect_slack_ids(tokens) & _collect_slack_ids(match_tokens))
                or (_collect_emails(tokens) & _collect_emails(match_tokens))
                or (_collect_dns(tokens) & _collect_dns(match_tokens))
            )
            # Only the review label depends on the name looking like a first name.
            looks_human = _looks_like_first_name(ent["name"]) and not (
                ent["id"] in sender_ids and _is_automated_sender(conn, ent)
            )
            review_shape = SHAPE_FIRST_NAME if looks_human else None
            if not shared:
                _review(ent, review_shape, review_shape or "name match", [match])
                continue
            reason = _blocker(ent, match)
            if reason:
                _review(ent, review_shape, reason, [match])
                continue
            pairs.append((ent["id"], match["id"], SHAPE_FIRST_NAME, sorted(shared)[0].lower()))
            continue

        # Shape A: the handle is an alias of a full-name person.
        holders = [h for h in handle_holders.get(key, []) if h["id"] != ent["id"]]
        first_name_holders_of_key = [
            h for h in first_name_handle_holders.get(key, []) if h["id"] != ent["id"]
        ]
        if len(holders) + len(first_name_holders_of_key) > 1:
            _review(
                ent,
                SHAPE_HANDLE_ALIAS,
                "ambiguous handle alias",
                holders + first_name_holders_of_key,
            )
            continue
        if first_name_holders_of_key:
            # The first-name holder must never survive the handle entity: review only.
            _review(ent, SHAPE_HANDLE_ALIAS, "first-name alias holder", first_name_holders_of_key)
            continue
        if not holders:
            continue
        holder = holders[0]
        reason = _blocker(ent, holder)
        if reason:
            _review(ent, SHAPE_HANDLE_ALIAS, reason, [holder])
            continue
        if ent["id"] in sender_ids:
            pairs.append((ent["id"], holder["id"], SHAPE_HANDLE_ALIAS, key))

    return pairs, review, excluded


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

    sender_ids = {
        r["sender_entity_id"]
        for r in conn.execute(
            "SELECT DISTINCT sender_entity_id FROM observations WHERE sender_entity_id IS NOT NULL"
        ).fetchall()
    }

    shape_pairs, shape_review, shape_excluded = _find_person_shapes(
        conn, sender_ids, {r["id"] for r in needs_review}
    )
    needs_review.extend(shape_review)
    entities = [e for e in clean if e["id"] not in shape_excluded]

    if not entities:
        return {"candidates": [], "needs_review": needs_review}

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
            if _is_truncated_dn(token):
                continue
            key = token.strip().lower()
            if key and len(key) >= 2 and key not in seen:
                seen.add(key)
                is_foreign_handle = (
                    token != ent["name"]
                    and _HANDLE_RE.match(key)
                    and not _SLACK_ID_RE.match(key.upper())
                )
                if is_foreign_handle:
                    if _name_type_rank(ent["name"]) != 0:
                        continue
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
    blocked_slack_conflict: set[int] = set()

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
            blocked_slack_conflict.add(a)
            blocked_slack_conflict.add(b)
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

    index_by_id = {e["id"]: i for i, e in enumerate(entities)}
    shape_by_pair: dict[tuple[int, int], str] = {}
    shape_keep: set[int] = set()
    for drop_id, keep_id, shape, ident in shape_pairs:
        a, b = index_by_id.get(drop_id), index_by_id.get(keep_id)
        if a is None or b is None:
            continue
        pair = (min(a, b), max(a, b))
        pair_match.setdefault(pair, ident)
        shape_by_pair[pair] = shape
        shape_keep.add(b)
        _union(a, b)

    groups_map: dict[int, list[int]] = {}
    for i in range(len(entities)):
        root = _find(i)
        groups_map.setdefault(root, []).append(i)

    for indices in groups_map.values():
        if len(indices) == 1 and indices[0] in blocked_slack_conflict:
            needs_review.append({**entities[indices[0]], "reason": "conflicting Slack IDs"})

    candidates = []
    for indices in groups_map.values():
        if len(indices) < 2:
            continue

        group = [entities[i] for i in indices]
        idx_set = set(indices)
        group_shape = next(
            (s for p, s in shape_by_pair.items() if p[0] in idx_set and p[1] in idx_set), None
        )
        shape_tag = {"shape": group_shape} if group_shape else {}

        group_names_lower = {e["name"].strip().lower() for e in group}
        group_names_lower |= {normalize_name(e["name"]) for e in group}
        send_to_review = False
        for pair, ident in pair_match.items():
            if pair[0] in idx_set and pair[1] in idx_set:
                if (
                    _HANDLE_RE.match(ident)
                    and not _SLACK_ID_RE.match(ident.upper())
                    and ident not in group_names_lower
                ):
                    send_to_review = True
                    break
        if send_to_review:
            needs_review.extend(group)
            continue

        send_to_review = False
        for pair, ident in pair_match.items():
            if pair[0] not in idx_set or pair[1] not in idx_set:
                continue
            if not (_HANDLE_RE.match(ident) and not _SLACK_ID_RE.match(ident.upper())):
                continue
            for a_idx, b_idx in ((pair[0], pair[1]), (pair[1], pair[0])):
                fn_ent = entities[a_idx]
                if _name_type_rank(fn_ent["name"]) != 0 and a_idx not in shape_keep:
                    continue
                if entity_hard_ids[a_idx]["slack_ids"]:
                    continue
                if not entity_hard_ids[b_idx]["slack_ids"]:
                    continue
                if not _handle_fits_name(ident, fn_ent["name"]):
                    send_to_review = True
                    break
            if send_to_review:
                break
        if send_to_review:
            for ent in group:
                needs_review.append({**ent, "reason": "handle-name mismatch", **shape_tag})
            continue

        obs_counts = {}
        for ent in group:
            obs_counts[ent["id"]] = conn.execute(
                "SELECT COUNT(*) AS c FROM observations WHERE sender_entity_id = ?",
                (ent["id"],),
            ).fetchone()["c"]

        # The full-name side of a shape pair survives even when its name
        # does not look like a plausible display name (e.g. all lowercase).
        shape_keep_ids = {entities[i]["id"] for i in shape_keep & idx_set}
        sorted_group = sorted(
            group,
            key=lambda e: (
                0 if e["id"] in shape_keep_ids else _name_type_rank(e["name"]),
                -obs_counts[e["id"]],
            ),
        )
        keep = sorted_group[0]

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
                "shape": group_shape,
            }
        )

    return {"candidates": candidates, "needs_review": needs_review}


def _merge_aliases_collide(
    conn: sqlite3.Connection,
    keep_id: str,
    drop_id: str,
    *,
    extra_exclude_ids: set[str] | None = None,
    drop_override: dict | None = None,
) -> bool:
    keep = conn.execute("SELECT name, aliases FROM entities WHERE id = ?", (keep_id,)).fetchone()
    if not keep:
        return False

    if drop_override:
        drop_name = drop_override["name"]
        drop_aliases = set(drop_override.get("aliases", []))
    else:
        drop = conn.execute(
            "SELECT name, aliases FROM entities WHERE id = ?", (drop_id,)
        ).fetchone()
        if not drop:
            return False
        drop_name = drop["name"]
        drop_aliases = set(json.loads(drop["aliases"] or "[]"))

    keep_aliases = set(json.loads(keep["aliases"] or "[]"))
    new_aliases = (drop_aliases | {drop_name}) - keep_aliases - {keep["name"]}

    exclude_ids = {keep_id, drop_id}
    if extra_exclude_ids:
        exclude_ids |= extra_exclude_ids
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


def _pre_merge_slack_drops(
    conn: sqlite3.Connection,
    drops: list[dict],
    result: dict,
    match_id: str,
    *,
    dry_run: bool = False,
) -> tuple[list[dict], set[str]]:
    """Merge drop entities that share a Slack ID with each other.

    When a dedup group has multiple drops sharing a Slack ID, merge them
    first (handle-named entity wins over ID-named one) so the subsequent
    keep-vs-drop merge sees only one drop holding that Slack ID and the
    alias collision with the now-deleted entity disappears.

    Returns (remaining_drops, folded_entity_ids).
    """
    if len(drops) < 2:
        return drops, set()

    drop_slack_ids: list[set[str]] = []
    for d in drops:
        tokens = [d["name"]] + d.get("aliases", [])
        drop_slack_ids.append(_collect_slack_ids(tokens))

    n = len(drops)
    parent = list(range(n))

    def _find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            si, sj = drop_slack_ids[i], drop_slack_ids[j]
            if si and sj and not si.isdisjoint(sj):
                ri, rj = _find(i), _find(j)
                if ri != rj:
                    parent[ri] = rj

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(_find(i), []).append(i)

    remaining: list[dict] = []
    folded_ids: set[str] = set()
    for indices in groups.values():
        if len(indices) == 1:
            remaining.append(drops[indices[0]])
            continue

        group_drops = [drops[i] for i in indices]
        obs_counts: dict[str, int] = {}
        for d in group_drops:
            obs_counts[d["id"]] = conn.execute(
                "SELECT COUNT(*) AS c FROM observations WHERE sender_entity_id = ?",
                (d["id"],),
            ).fetchone()["c"]

        sorted_drops = sorted(
            group_drops,
            key=lambda d: (_name_type_rank(d["name"]), -obs_counts[d["id"]]),
        )
        sub_keep = sorted_drops[0]

        for sub_drop in sorted_drops[1:]:
            mr = merge_entities(conn, sub_keep["id"], sub_drop["id"], dry_run=dry_run)
            mr["match_identifier"] = match_id
            result["merges"].append(mr)
            result["entities_merged"] += 1
            folded_ids.add(sub_drop["id"])

        if dry_run:
            merged_aliases = set(sub_keep.get("aliases", []))
            for sub_drop in sorted_drops[1:]:
                merged_aliases |= set(sub_drop.get("aliases", []))
                merged_aliases.add(sub_drop["name"])
            remaining.append(
                {
                    "id": sub_keep["id"],
                    "name": sub_keep["name"],
                    "aliases": list(merged_aliases),
                }
            )
        else:
            row = conn.execute(
                "SELECT id, name, aliases FROM entities WHERE id = ?", (sub_keep["id"],)
            ).fetchone()
            if row:
                remaining.append(
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "aliases": json.loads(row["aliases"] or "[]"),
                    }
                )

    return remaining, folded_ids


def dedup_entities(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    snapshot_token: str | None = None,
) -> dict:
    if not dry_run:
        _check_snapshot_token(conn, snapshot_token)
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
        shape_tag = {"shape": group["shape"]} if group.get("shape") else {}
        drops = list(group["drop"])

        drops, folded_ids = _pre_merge_slack_drops(conn, drops, result, match_id, dry_run=dry_run)

        for drop in drops:
            if not dry_run:
                drop_row = conn.execute(
                    "SELECT id, name, aliases FROM entities WHERE id = ?",
                    (drop["id"],),
                ).fetchone()
                if not drop_row:
                    continue
                drop = {
                    "id": drop_row["id"],
                    "name": drop_row["name"],
                    "aliases": json.loads(drop_row["aliases"] or "[]"),
                }

            collide_kw: dict = {}
            if folded_ids:
                collide_kw["extra_exclude_ids"] = folded_ids
                if dry_run:
                    collide_kw["drop_override"] = drop

            if _merge_aliases_collide(conn, keep["id"], drop["id"], **collide_kw):
                keep_tokens = [keep["name"]] + keep.get("aliases", [])
                drop_tokens = [drop["name"]] + drop.get("aliases", [])
                shared_slacks = _collect_slack_ids(keep_tokens) & _collect_slack_ids(drop_tokens)
                if shared_slacks:
                    keep_emails = _collect_emails(keep_tokens)
                    drop_emails = _collect_emails(drop_tokens)
                    extra_keep = keep_emails - drop_emails
                    extra_drop = drop_emails - keep_emails
                    keep_slacks = _collect_slack_ids(keep_tokens)
                    drop_slacks = _collect_slack_ids(drop_tokens)
                    extra_keep_slacks = keep_slacks - shared_slacks
                    extra_drop_slacks = drop_slacks - shared_slacks
                    if extra_keep or extra_drop or extra_keep_slacks or extra_drop_slacks:
                        result["needs_review"].append(
                            {**drop, "reason": "alias collision", **shape_tag}
                        )
                        continue
                else:
                    keep_slacks = _collect_slack_ids(keep_tokens)
                    drop_slacks = _collect_slack_ids(drop_tokens)
                    if keep_slacks and drop_slacks:
                        result["needs_review"].append(
                            {**drop, "reason": "conflicting Slack IDs", **shape_tag}
                        )
                    else:
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
            merge_result["shape"] = group.get("shape")
            result["merges"].append(merge_result)
            result["entities_merged"] += 1

    return result


def prune_non_person_entities(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    snapshot_token: str | None = None,
) -> dict:
    if not dry_run:
        _check_snapshot_token(conn, snapshot_token)
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
    snapshot_token: str | None = None,
) -> dict:
    if not dry_run:
        _check_snapshot_token(conn, snapshot_token)
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


def _store_file_path(conn: sqlite3.Connection) -> Path | None:
    for row in conn.execute("PRAGMA database_list").fetchall():
        if row["name"] == "main" and row["file"]:
            return Path(row["file"])
    return None


def rekey_credential_references(
    conn: sqlite3.Connection,
    *,
    confirm: bool = False,
) -> dict:
    """Re-key reference entities whose URL carries credential query parameters.

    Each affected entity is moved to the id of its sanitized URL, or merged into
    the entity already holding that id. Dry-run by default; with ``confirm`` the
    store is backed up before the first write. Results never include the
    original (credential-bearing) URL.
    """
    from patina.extraction import _make_id, sanitize_reference_url

    rows = conn.execute(
        "SELECT id, name, aliases FROM entities WHERE type = 'reference' ORDER BY id"
    ).fetchall()
    existing_ids = {r["id"] for r in conn.execute("SELECT id FROM entities").fetchall()}

    plan = []
    clean_aliases: dict[str, list[str]] = {}
    for r in rows:
        sanitized = sanitize_reference_url(r["name"])
        aliases = json.loads(r["aliases"] or "[]")
        alias_hit = any(sanitize_reference_url(a) != a for a in aliases)
        if sanitized == r["name"] and not alias_hit:
            continue
        # Credential URLs can also sit in aliases (e.g. from an earlier merge).
        clean_aliases[r["id"]] = [
            a for a in dict.fromkeys(sanitize_reference_url(a) for a in aliases) if a != sanitized
        ]
        if sanitized == r["name"]:
            new_id, action = r["id"], "aliases_sanitized"
        else:
            new_id = _make_id("reference", sanitized)
            action = "merged" if new_id in existing_ids else "renamed"
            existing_ids.add(new_id)
        plan.append(
            {
                "old_id": r["id"],
                "new_id": new_id,
                "name": sanitized,
                "action": action,
                "had_credentials": True,
            }
        )

    result = {
        "renamed": sum(1 for p in plan if p["action"] == "renamed"),
        "merged": sum(1 for p in plan if p["action"] == "merged"),
        "aliases_sanitized": sum(1 for p in plan if p["action"] == "aliases_sanitized"),
        "entities": plan,
        "backup": None,
    }

    if not confirm or not plan:
        return result

    db_path = _store_file_path(conn)
    if db_path is not None:
        result["backup"] = str(backup_store(db_path))

    ensure_entity_alias_provenance_table(conn)
    for p in plan:
        old_id, new_id = p["old_id"], p["new_id"]
        # Drop the credential URL from the name and aliases before merging so it
        # never becomes an alias. Provenance rows are rewritten too: they would
        # otherwise keep the secret.
        conn.execute(
            "UPDATE entities SET name = ?, aliases = ? WHERE id = ?",
            (p["name"], json.dumps(clean_aliases[old_id]), old_id),
        )
        for prov in conn.execute(
            "SELECT rowid, alias FROM entity_alias_provenance WHERE entity_id = ?", (old_id,)
        ).fetchall():
            clean = sanitize_reference_url(prov["alias"])
            if clean != prov["alias"]:
                conn.execute(
                    "UPDATE entity_alias_provenance SET alias = ? WHERE rowid = ?",
                    (clean, prov["rowid"]),
                )
        if p["action"] == "aliases_sanitized":
            continue
        if p["action"] == "merged":
            merge_entities(conn, new_id, old_id)
            # merge_entities keeps the dropped name as an alias; here it equals the
            # survivor's own name, so remove it again.
            keep = conn.execute("SELECT name, aliases FROM entities WHERE id = ?", (new_id,))
            keep = keep.fetchone()
            keep_aliases = json.loads(keep["aliases"] or "[]")
            if keep["name"] in keep_aliases:
                conn.execute(
                    "UPDATE entities SET aliases = ? WHERE id = ?",
                    (json.dumps([a for a in keep_aliases if a != keep["name"]]), new_id),
                )
                _record_alias_changes(conn, new_id, removed=[keep["name"]])
            continue
        conn.execute(
            "INSERT INTO entities (id, type, name, aliases, metadata, first_seen,"
            " last_seen, decay_rate, is_owner)"
            " SELECT ?, type, name, aliases, metadata, first_seen, last_seen,"
            " decay_rate, is_owner FROM entities WHERE id = ?",
            (new_id, old_id),
        )
        rewire_entity_references(conn, new_id, old_id)
        conn.execute(
            "UPDATE entity_alias_provenance SET entity_id = ? WHERE entity_id = ?",
            (new_id, old_id),
        )
        conn.execute("DELETE FROM entities WHERE id = ?", (old_id,))

    conn.commit()
    return result


def find_id_named_entities(conn: sqlite3.Connection) -> list[dict]:
    """Find person entities whose name is a raw Slack ID."""
    rows = conn.execute(
        "SELECT id, name, aliases FROM entities WHERE type = 'person' AND is_owner = 0"
    ).fetchall()
    results = []
    for r in rows:
        if _SLACK_ID_RE.match(r["name"]):
            results.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "aliases": json.loads(r["aliases"] or "[]"),
                }
            )
    return results


def retype_organization_entities(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
    snapshot_token: str | None = None,
) -> dict:
    if not dry_run:
        _check_snapshot_token(conn, snapshot_token)
    rows = conn.execute(
        "SELECT id, name FROM entities WHERE type = 'person' AND is_owner = 0"
    ).fetchall()

    to_retype = []
    for r in rows:
        if is_organization(r["name"]):
            to_retype.append({"id": r["id"], "name": r["name"]})

    result = {
        "retyped": len(to_retype),
        "entities": to_retype,
    }

    if dry_run or not to_retype:
        return result

    for ent in to_retype:
        conn.execute(
            "UPDATE entities SET type = 'organization' WHERE id = ?",
            (ent["id"],),
        )

    conn.commit()
    return result


def fix_junk_senders(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
) -> dict:
    """Merge or retype junk sender entities (legacy DNs and raw emails).

    Finds person entities that are active senders but named by a legacy
    Exchange DN or a bare email address.  For each, tries to resolve the
    entity's SMTP address or aliases to an existing proper person entity
    and merges into it.  Unmatched entities are retyped as ``reference``
    so they no longer pollute the person list.  Observations are never
    deleted.
    """
    rows = conn.execute(
        "SELECT e.id, e.name, e.aliases FROM entities e "
        "WHERE e.is_owner = 0 AND e.type = 'person' "
        "AND e.id IN ("
        "  SELECT DISTINCT sender_entity_id FROM observations "
        "  WHERE sender_entity_id IS NOT NULL"
        ")"
    ).fetchall()

    junk_ids: set[str] = set()
    junk: list[sqlite3.Row] = []
    for r in rows:
        if _is_junk_sender_name(r["name"]):
            junk.append(r)
            junk_ids.add(r["id"])

    if not junk:
        return {"merged": [], "retyped": []}

    all_entities = conn.execute(
        "SELECT id, name, aliases, type FROM entities WHERE is_owner = 0"
    ).fetchall()

    alias_lookup: dict[str, set[str]] = {}
    norm_lookup: dict[str, str] = {}
    for ent in all_entities:
        if ent["id"] in junk_ids:
            continue
        norm = _normalize_for_dedup(ent["name"])
        if norm and len(norm) > 2:
            norm_lookup.setdefault(norm, ent["id"])
        for alias in json.loads(ent["aliases"] or "[]"):
            anorm = _normalize_for_dedup(alias)
            if anorm and len(anorm) > 2:
                norm_lookup.setdefault(anorm, ent["id"])
                if ent["type"] == "person":
                    alias_lookup.setdefault(anorm, set()).add(ent["id"])

    merged: list[dict] = []
    retyped: list[dict] = []
    split_needed: list[dict] = []
    for r in junk:
        aliases = json.loads(r["aliases"] or "[]")

        distinct_targets: set[str] = set()
        for ident in [r["name"]] + aliases:
            if ident.startswith("/O=") or ident.startswith("/o="):
                handle = _dn_trailing_handle(ident)
                if handle:
                    hits = alias_lookup.get(_normalize_for_dedup(handle), set())
                    if len(hits) == 1:
                        distinct_targets.add(next(iter(hits)))
                smtp = _dn_trailing_smtp(ident)
                if smtp:
                    tid = resolve_entity_id(conn, smtp)
                    if tid and tid != r["id"] and tid not in junk_ids:
                        distinct_targets.add(tid)
                continue
            if ident.startswith("slack:"):
                continue
            tid = resolve_entity_id(conn, ident)
            if tid and tid != r["id"] and tid not in junk_ids:
                distinct_targets.add(tid)
                continue
            norm = _normalize_for_dedup(ident)
            if norm and len(norm) > 2 and norm in norm_lookup:
                tid = norm_lookup[norm]
                if tid != r["id"]:
                    distinct_targets.add(tid)

        if len(distinct_targets) > 1:
            split_needed.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "target_count": len(distinct_targets),
                }
            )
            continue

        target_id: str | None = None

        for ident in [r["name"]] + aliases:
            if ident.startswith("/O=") or ident.startswith("/o="):
                handle = _dn_trailing_handle(ident)
                if handle:
                    hits = alias_lookup.get(_normalize_for_dedup(handle), set())
                    if len(hits) == 1:
                        target_id = next(iter(hits))
                        break
                continue
            if ident.startswith("slack:"):
                continue

            tid = resolve_entity_id(conn, ident)
            if tid and tid != r["id"] and tid not in junk_ids:
                target_id = tid
                break

            norm = _normalize_for_dedup(ident)
            if norm and len(norm) > 2 and norm in norm_lookup:
                tid = norm_lookup[norm]
                if tid != r["id"]:
                    target_id = tid
                    break

        if target_id:
            result = merge_entities(conn, target_id, r["id"], dry_run=dry_run)
            merged.append(
                {
                    "junk_id": r["id"],
                    "junk_name": r["name"],
                    "target_id": target_id,
                    "target_name": result["keep_name"],
                }
            )
        else:
            if not dry_run:
                conn.execute(
                    "UPDATE entities SET type = 'reference' WHERE id = ?",
                    (r["id"],),
                )
                conn.commit()
            retyped.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                }
            )

    return {"merged": merged, "retyped": retyped, "split_needed": split_needed}


def _resolve_key_via_aliases(
    key: str,
    person_alias_lookup: dict[str, set[str]],
    exclude_entity_id: str,
) -> str | None:
    """Resolve a non-DN routing key to a unique person entity via alias lookup."""
    for variant in (key, f"slack:{key}"):
        norm = _normalize_for_dedup(variant)
        if norm and len(norm) > 2:
            hits = person_alias_lookup.get(norm, set()) - {exclude_entity_id}
            if len(hits) == 1:
                return next(iter(hits))
    return None


def split_dn_sink(
    conn: sqlite3.Connection,
    entity_id: str,
    *,
    dry_run: bool = True,
) -> dict:
    """Split a DN-sink entity by routing its full-DN aliases to matched persons.

    For each full-DN alias (one containing a trailing handle or SMTP address):
    - If the handle/SMTP matches a person entity, route the alias there
    - Otherwise, create a per-DN reference entity

    Routes observations using source-specific keys:
    - Email: ``metadata.sender_dn`` (backfilled from channel peers when missing)
    - Slack: ``metadata.sender_slack_id`` (backfilled from channel peers when missing)
    - Calendar (``channel_id`` starts with ``calendar:``): ``metadata.organizer_dn``
      (backfilled from observation text when missing)

    In commit mode, routes observations to the correct person, backfills
    missing metadata keys, then re-derives claims for entities that received
    routed observations.
    """
    entity = conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    if not entity:
        raise ValueError(f"Entity '{entity_id}' not found")

    aliases = json.loads(entity["aliases"] or "[]")

    all_entities = conn.execute(
        "SELECT id, name, aliases, type FROM entities WHERE is_owner = 0"
    ).fetchall()

    person_alias_lookup: dict[str, set[str]] = {}
    for ent in all_entities:
        if ent["id"] == entity_id or ent["type"] != "person":
            continue
        for alias in json.loads(ent["aliases"] or "[]"):
            anorm = _normalize_for_dedup(alias)
            if anorm and len(anorm) > 2:
                person_alias_lookup.setdefault(anorm, set()).add(ent["id"])

    routes: list[dict] = []
    for alias in aliases:
        if not _LEGACY_DN_RE.match(alias):
            continue
        handle = _dn_trailing_handle(alias)
        smtp = _dn_trailing_smtp(alias)
        if not handle and not smtp:
            continue

        target_id: str | None = None
        target_name: str | None = None

        for kind in IDENTIFIER_PRECEDENCE:
            if target_id:
                break
            if kind == "email" and smtp:
                tid = resolve_entity_id(conn, smtp)
                if tid and tid != entity_id:
                    target_id = tid
            elif kind == "handle" and handle:
                hits = person_alias_lookup.get(_normalize_for_dedup(handle), set())
                if len(hits) == 1:
                    target_id = next(iter(hits))

        if target_id:
            for ent in all_entities:
                if ent["id"] == target_id:
                    target_name = ent["name"]
                    break

        routes.append(
            {
                "dn": alias,
                "handle": handle,
                "target_id": target_id,
                "target_name": target_name,
            }
        )

    observations = conn.execute(
        "SELECT id, source, channel_id, text, metadata"
        " FROM observations WHERE sender_entity_id = ?",
        (entity_id,),
    ).fetchall()

    dn_to_target = {r["dn"]: r["target_id"] for r in routes if r["target_id"]}

    # Backfill: collect routing keys by channel; only use channels where
    # every key-bearing peer shares the same value
    channel_dns: dict[str, set[str]] = {}
    channel_slack_ids: dict[str, set[str]] = {}
    for obs in observations:
        meta = json.loads(obs["metadata"] or "{}")
        dn = meta.get("sender_dn", "")
        if dn and obs["channel_id"]:
            channel_dns.setdefault(obs["channel_id"], set()).add(dn)
        slack_id = meta.get("sender_slack_id", "")
        if slack_id and obs["channel_id"]:
            channel_slack_ids.setdefault(obs["channel_id"], set()).add(slack_id)
    channel_dn_map: dict[str, str] = {
        ch: next(iter(dns)) for ch, dns in channel_dns.items() if len(dns) == 1
    }
    channel_slack_id_map: dict[str, str] = {
        ch: next(iter(ids)) for ch, ids in channel_slack_ids.items() if len(ids) == 1
    }

    # Resolve routing target for each observation using source-specific keys,
    # tried in IDENTIFIER_PRECEDENCE order
    obs_routing: list[tuple] = []
    unroutable_by_source: dict[str, int] = {}

    for obs in observations:
        meta = json.loads(obs["metadata"] or "{}")
        source = obs["source"]
        channel_id = obs["channel_id"] or ""
        target_id = None
        backfills: dict[str, str] = {}

        for kind in IDENTIFIER_PRECEDENCE:
            if target_id:
                break
            if kind == "slack_id" and source.startswith("slack"):
                # sender_slack_id (direct or backfilled from channel peers)
                slack_id = meta.get("sender_slack_id", "")
                if not slack_id and channel_id in channel_slack_id_map:
                    slack_id = channel_slack_id_map[channel_id]
                    backfills["sender_slack_id"] = slack_id
                if slack_id:
                    target_id = _resolve_key_via_aliases(slack_id, person_alias_lookup, entity_id)
            elif kind == "dn":
                # sender_dn (direct or backfilled from channel peers)
                sender_dn = meta.get("sender_dn", "")
                if not sender_dn and channel_id in channel_dn_map:
                    sender_dn = channel_dn_map[channel_id]
                    backfills["sender_dn"] = sender_dn
                if sender_dn and sender_dn in dn_to_target:
                    target_id = dn_to_target[sender_dn]

        # Calendar: organizer (direct or backfilled from observation text) is a
        # display-name key, the weakest identifier, so it is tried last
        if not target_id and channel_id.startswith("calendar:"):
            org = meta.get("organizer_dn", "")
            if not org:
                m = _ORGANIZER_RE.search(obs["text"] or "")
                if m:
                    org = m.group(1).strip()
                    backfills["organizer_dn"] = org
            if org:
                target_id = _resolve_key_via_aliases(org, person_alias_lookup, entity_id)

        obs_routing.append((obs, target_id, backfills))
        if not target_id:
            unroutable_by_source[source] = unroutable_by_source.get(source, 0) + 1

    routable_count = sum(1 for _, t, _ in obs_routing if t)

    result: dict = {
        "entity_id": entity_id,
        "entity_name": entity["name"],
        "routes": routes,
        "routable_observations": routable_count,
        "unroutable_by_source": unroutable_by_source,
    }

    if dry_run:
        return result

    if routable_count == 0:
        result["observations_routed"] = 0
        return result

    affected_entity_ids: set[str] = set()
    created_references: list[dict] = []
    routed_dn_set = {r["dn"] for r in routes}
    remaining_aliases = [a for a in aliases if a not in routed_dn_set]

    for route in routes:
        dn = route["dn"]
        if route["target_id"]:
            target = conn.execute(
                "SELECT aliases FROM entities WHERE id = ?",
                (route["target_id"],),
            ).fetchone()
            target_aliases = json.loads(target["aliases"] or "[]")
            if dn not in target_aliases:
                target_aliases.append(dn)
                _record_alias_changes(conn, route["target_id"], added=[dn])
            conn.execute(
                "UPDATE entities SET aliases = ? WHERE id = ?",
                (json.dumps(target_aliases), route["target_id"]),
            )
            affected_entity_ids.add(route["target_id"])
        else:
            ref_id = hashlib.sha256(dn.encode()).hexdigest()[:16]
            now = entity["first_seen"] or datetime.now(UTC).isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO entities"
                " (id, type, name, aliases, metadata,"
                "  first_seen, last_seen, decay_rate, is_owner)"
                " VALUES (?, 'reference', ?, '[]', '{}', ?, ?, 0.02, 0)",
                (ref_id, dn, now, now),
            )
            created_references.append({"id": ref_id, "name": dn})

    routed_obs = 0
    for obs, target_id, backfills in obs_routing:
        if target_id:
            conn.execute(
                "UPDATE observations SET sender_entity_id = ? WHERE id = ?",
                (target_id, obs["id"]),
            )
            affected_entity_ids.add(target_id)
            if backfills:
                meta = json.loads(obs["metadata"] or "{}")
                meta.update(backfills)
                conn.execute(
                    "UPDATE observations SET metadata = ? WHERE id = ?",
                    (json.dumps(meta), obs["id"]),
                )
            routed_obs += 1

    conn.execute(
        "UPDATE entities SET aliases = ? WHERE id = ?",
        (json.dumps(remaining_aliases), entity_id),
    )
    _record_alias_changes(
        conn, entity_id, removed=[a for a in aliases if a not in remaining_aliases]
    )

    for eid in affected_entity_ids:
        conn.execute(
            "UPDATE observations SET processed = 0 WHERE sender_entity_id = ?",
            (eid,),
        )

    conn.commit()

    result["created_references"] = created_references
    result["observations_routed"] = routed_obs
    result["rederived_entities"] = sorted(affected_entity_ids)

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


def clean_bogus_slack_aliases(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = False,
) -> dict:
    """Remove ``slack:`` aliases whose value is not a valid Slack ID."""
    rows = conn.execute("SELECT id, name, aliases FROM entities").fetchall()

    cleaned: list[dict] = []
    for r in rows:
        aliases = json.loads(r["aliases"] or "[]")
        kept: list[str] = []
        removed: list[str] = []
        for a in aliases:
            if a.startswith("slack:"):
                suffix = a[len("slack:") :]
                if _SLACK_ID_RE.match(suffix.upper()):
                    kept.append(a)
                else:
                    removed.append(a)
            else:
                kept.append(a)
        if removed:
            cleaned.append({"id": r["id"], "name": r["name"], "removed": removed, "kept": kept})

    if not dry_run and cleaned:
        for c in cleaned:
            conn.execute(
                "UPDATE entities SET aliases = ? WHERE id = ?",
                (json.dumps(c["kept"]), c["id"]),
            )
        conn.commit()

    return {"cleaned": len(cleaned), "entities": cleaned}


def repair_multi_identity_names(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = True,
) -> dict:
    """Repair multi-identity entities retaining a member handle or name.

    Resets the entity name to its original truncated-DN alias if present,
    or otherwise to a neutral non-identity label (e.g. ``/O=SINK/<id>``),
    and strips the stolen name from its aliases.

    A single person carrying one stale Slack ID that another entity holds
    is not a sink (#522): it is left alone and listed under ``skipped``
    with reason ``stale_foreign_id`` for the foreign-ID strip path.
    """
    all_rows = conn.execute("SELECT id, name, aliases, is_owner FROM entities").fetchall()

    slack_holders: dict[str, set[str]] = {}
    token_holders: dict[str, set[str]] = {}
    for r in all_rows:
        tokens = [r["name"], *json.loads(r["aliases"] or "[]")]
        if not r["is_owner"]:
            for sid in _collect_slack_ids(tokens):
                slack_holders.setdefault(sid, set()).add(r["id"])
        for t in tokens:
            key = _graph_normalize(normalize_alias(t))
            if key:
                token_holders.setdefault(key, set()).add(r["id"])

    repaired: list[dict] = []
    skipped: list[dict] = []
    for r in all_rows:
        if r["is_owner"]:
            continue
        aliases = json.loads(r["aliases"] or "[]")
        if not _is_multi_identity(r["name"], aliases):
            continue

        if _is_truncated_dn(r["name"]):
            continue

        # A person with a stale foreign ID: once the Slack IDs another entity
        # holds are dropped, one own ID is left and nobody else holds the name.
        foreign_ids = {
            sid
            for sid in _collect_slack_ids([r["name"], *aliases])
            if slack_holders[sid] - {r["id"]}
        }
        if foreign_ids:
            own_aliases = [a for a in aliases if not _collect_slack_ids([a]) & foreign_ids]
            own_ids = _collect_slack_ids([r["name"], *own_aliases])
            name_key = _graph_normalize(normalize_alias(r["name"]))
            name_held_elsewhere = bool(token_holders.get(name_key, set()) - {r["id"]})
            if (
                len(own_ids) == 1
                and not name_held_elsewhere
                and not _is_multi_identity(r["name"], own_aliases)
            ):
                skipped.append(
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "reason": "stale_foreign_id",
                        "foreign_ids": sorted(foreign_ids),
                    }
                )
                continue

        truncated_dn = next((a for a in aliases if _is_truncated_dn(a)), None)
        new_name = truncated_dn if truncated_dn else f"/O=SINK/{r['id'][:8]}"

        old_name = r["name"]
        old_norm = old_name.strip().lower()
        new_aliases = [
            a
            for a in aliases
            if a.strip().lower() != old_norm
            and (a.split(":", 1)[1].strip().lower() != old_norm if ":" in a else True)
        ]

        repaired.append(
            {
                "id": r["id"],
                "old_name": old_name,
                "new_name": new_name,
                "aliases": new_aliases,
                "stripped_aliases": [a for a in aliases if a not in new_aliases],
            }
        )

    if not dry_run and repaired:
        for item in repaired:
            conn.execute(
                "UPDATE entities SET name = ?, aliases = ? WHERE id = ?",
                (item["new_name"], json.dumps(item["aliases"]), item["id"]),
            )
            _record_alias_changes(conn, item["id"], removed=item["stripped_aliases"])
        conn.commit()

    return {"repaired": len(repaired), "entities": repaired, "skipped": skipped}


def _is_handle_alias(alias: str) -> bool:
    """True for a bare or ``@``-prefixed handle (not a name, email, Slack ID or DN)."""
    value = normalize_alias(alias).strip().lstrip("@")
    if not value or " " in value or "@" in value:
        return False
    if _SLACK_ID_RE.match(value.upper()):
        return False
    return _name_type_rank(value) == 1


def repair_sink_handle_aliases(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = True,
) -> dict:
    """Strip member handle aliases left on multi-identity sinks (#502).

    A handle alias on a multi-identity entity is removed when exactly one
    single-identity entity also holds it (compared with ``normalize_name``).
    Only aliases are touched: names, Slack IDs and DNs stay, and
    single-identity entities are never modified.
    """
    rows = conn.execute("SELECT id, name, aliases FROM entities WHERE is_owner = 0").fetchall()

    sinks: list[tuple[sqlite3.Row, list[str]]] = []
    single_holders: dict[str, set[str]] = {}
    for r in rows:
        aliases = json.loads(r["aliases"] or "[]")
        if _is_multi_identity(r["name"], aliases):
            sinks.append((r, aliases))
            continue
        for a in aliases:
            key = _graph_normalize(normalize_alias(a))
            if key:
                single_holders.setdefault(key, set()).add(r["id"])

    stripped: list[dict] = []
    for r, aliases in sinks:
        kept: list[str] = []
        removed: list[str] = []
        for a in aliases:
            key = _graph_normalize(normalize_alias(a))
            if _is_handle_alias(a) and len(single_holders.get(key, ())) == 1:
                removed.append(a)
            else:
                kept.append(a)
        if removed:
            stripped.append({"id": r["id"], "name": r["name"], "removed": removed, "kept": kept})

    if not dry_run and stripped:
        for item in stripped:
            conn.execute(
                "UPDATE entities SET aliases = ? WHERE id = ?",
                (json.dumps(item["kept"]), item["id"]),
            )
        conn.commit()

    return {
        "stripped": sum(len(item["removed"]) for item in stripped),
        "entities": stripped,
    }
