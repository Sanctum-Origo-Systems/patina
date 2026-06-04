from __future__ import annotations

from patina.beliefs.contradictions import find_contradictions_tier1
from patina.beliefs.decay import get_stale_beliefs
from patina.beliefs.relationships import get_relationship_map
from patina.store import connect, get_db_path, init_db


def _get_conn(home=None):
    db_path = get_db_path(home)
    init_db(db_path)
    return connect(db_path)


def beliefs(entity_type: str | None = None) -> str:
    conn = _get_conn()
    try:
        if entity_type:
            rows = conn.execute(
                "SELECT id, type, name FROM entities WHERE type = ? AND is_owner = 0 ORDER BY name",
                (entity_type,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, type, name FROM entities WHERE is_owner = 0 ORDER BY type, name"
            ).fetchall()

        if not rows:
            return "No entities found."

        lines = []
        for ent in rows:
            cc = conn.execute(
                "SELECT COUNT(*) AS c FROM claims WHERE subject_id = ?",
                (ent["id"],),
            ).fetchone()["c"]
            rc = conn.execute(
                "SELECT COUNT(*) AS c FROM relationships WHERE subject_id = ? OR object_id = ?",
                (ent["id"], ent["id"]),
            ).fetchone()["c"]
            lines.append(f"- [{ent['type']}] **{ent['name']}**: {cc} claims, {rc} relationships")
        return "\n".join(lines)
    finally:
        conn.close()


def stale(threshold: float = 0.3) -> str:
    conn = _get_conn()
    try:
        items = get_stale_beliefs(conn, threshold)
        if not items:
            return "No stale beliefs found."
        lines = [f"Stale beliefs (confidence < {threshold}):"]
        for item in items:
            lines.append(
                f"- [{item['type']}] {item['subject_name']} "
                f"{item['predicate']} {item['object']} "
                f"(conf={item['effective_confidence']:.2f}, "
                f"{item['days_since_confirmed']:.0f}d old)"
            )
        return "\n".join(lines)
    finally:
        conn.close()


def contradictions() -> str:
    conn = _get_conn()
    try:
        results = find_contradictions_tier1(conn)
        if not results:
            return "No contradictions found."
        lines = [f"Found {len(results)} contradiction(s):"]
        for item in results:
            lines.append(
                f"- **{item['subject']}** {item['predicate']}:\n"
                f"  - A: {item['object_1']} (conf={item['confidence_1']:.2f})\n"
                f"  - B: {item['object_2']} (conf={item['confidence_2']:.2f})"
            )
        return "\n".join(lines)
    finally:
        conn.close()


def relationships(top_n: int = 20) -> str:
    conn = _get_conn()
    try:
        rels = get_relationship_map(conn, top_n=top_n)
        if not rels:
            return "No relationships found."
        lines = ["| Name | Trust | Activity | Msgs/wk | Last |", "|---|---|---|---|---|"]
        for r in rels:
            days = f"{r['days_since_last']:.0f}d ago" if r["days_since_last"] else "never"
            lines.append(
                f"| {r['name']} | {r['trust_level']:.2f} | "
                f"{r['activity_status']} | {r['avg_per_week']:.1f} | {days} |"
            )
        return "\n".join(lines)
    finally:
        conn.close()


def register(mcp):
    mcp.tool()(beliefs)
    mcp.tool()(stale)
    mcp.tool()(contradictions)
    mcp.tool()(relationships)
