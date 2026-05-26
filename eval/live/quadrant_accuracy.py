"""Live eval: quadrant prediction accuracy on user's actual data.

Run manually: uv run python eval/live/quadrant_accuracy.py
Reads from ~/.patina/store.db.
"""

from __future__ import annotations

import time

from patina.store import connect, get_db_path


def run_eval():
    db_path = get_db_path()
    if not db_path.exists():
        print("No store.db found. Run 'patina init' and ingest data first.")
        return

    conn = connect(db_path)

    cutoff_24h = time.time() - 86400

    acted = conn.execute(
        """SELECT COUNT(*) AS c FROM decisions
           WHERE action = 'acted' AND acted_at >= ?""",
        (str(cutoff_24h),),
    ).fetchone()["c"]

    dismissed = conn.execute(
        """SELECT COUNT(*) AS c FROM decisions
           WHERE action = 'dismissed' AND acted_at >= ?""",
        (str(cutoff_24h),),
    ).fetchone()["c"]

    total = acted + dismissed
    if total == 0:
        print("No decisions in the last 24h. Use patina for a day first.")
        conn.close()
        return

    print("Quadrant accuracy (last 24h):")
    print(f"  Acted on:  {acted}")
    print(f"  Dismissed: {dismissed}")
    print(f"  Total:     {total}")
    print(f"  Act rate:  {acted / total:.0%}")

    conn.close()


if __name__ == "__main__":
    run_eval()
