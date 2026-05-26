"""Live eval: false positive rate in nudge/escalation.

Run manually: uv run python eval/live/nudge_false_positive.py
Reads from ~/.patina/store.db.
"""

from __future__ import annotations

from patina.store import connect, get_db_path


def run_eval():
    db_path = get_db_path()
    if not db_path.exists():
        print("No store.db found. Run 'patina init' and ingest data first.")
        return

    conn = connect(db_path)

    total = conn.execute("SELECT COUNT(*) AS c FROM decisions").fetchone()["c"]
    dismissed = conn.execute(
        "SELECT COUNT(*) AS c FROM decisions WHERE action = 'dismissed'"
    ).fetchone()["c"]

    if total == 0:
        print("No decisions recorded yet.")
        conn.close()
        return

    rate = dismissed / total
    print("False positive analysis:")
    print(f"  Total decisions:  {total}")
    print(f"  Dismissed:        {dismissed}")
    print(f"  Dismiss rate:     {rate:.1%}")

    conn.close()


if __name__ == "__main__":
    run_eval()
