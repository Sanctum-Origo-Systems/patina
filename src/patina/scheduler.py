from __future__ import annotations

import time
from pathlib import Path

from patina.beliefs.decay import run_decay_pass
from patina.ingest import ingest_all
from patina.priority.escalation import detect_urgency_shifts
from patina.store import connect, get_db_path, init_db


def heartbeat_once(*, home: Path | None = None) -> dict:
    db_path = get_db_path(home)
    init_db(db_path)

    results: dict = {"tasks_run": [], "errors": []}

    try:
        ingest_result = ingest_all(home=home)
        results["ingest"] = ingest_result
        results["tasks_run"].append("ingest")
    except Exception as e:
        results["errors"].append(f"ingest: {e}")

    conn = connect(db_path)
    try:
        try:
            stale_count = run_decay_pass(conn)
            results["decay"] = {"stale_count": stale_count}
            results["tasks_run"].append("decay")
        except Exception as e:
            results["errors"].append(f"decay: {e}")

        try:
            shifts = detect_urgency_shifts(conn, since_days=1, home=home)
            results["escalation"] = {"shifts": len(shifts)}
            results["tasks_run"].append("escalation_check")
        except Exception as e:
            results["errors"].append(f"escalation: {e}")
    finally:
        conn.close()

    return results


def heartbeat_start(*, interval_minutes: int = 30, home: Path | None = None) -> None:
    while True:
        heartbeat_once(home=home)
        time.sleep(interval_minutes * 60)
