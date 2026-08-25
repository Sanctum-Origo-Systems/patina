"""Backfill decisions from historical reactions in observation metadata.

Scans observations for Slack-style reactions by the owner and records
decision rows so that get_act_on_rate() returns real behavioral data.

Usage:
    python scripts/backfill_decisions_from_reactions.py [--dry-run] [--home PATH]

Run AFTER ingestion. No LLM needed.
"""

from __future__ import annotations

import argparse

from patina.backfill import run_backfill


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill decisions from historical reactions.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print expected count without writing.",
    )
    parser.add_argument(
        "--home",
        type=str,
        default=None,
        help="Custom Patina home directory.",
    )
    args = parser.parse_args()

    from pathlib import Path

    home = Path(args.home) if args.home else None
    result = run_backfill(home=home, dry_run=args.dry_run)

    if result.get("error") == "no_owner_ids":
        print("Error: No owner user IDs configured in config.yaml.")
        return

    mode = "Dry run" if args.dry_run else "Backfill"
    print(f"{mode} complete.")
    print(f"  Observations with reactions: {result['scanned']}")
    print(f"  Decisions inserted: {result['inserted']}")
    print(f"  Already had decision: {result['skipped']}")


if __name__ == "__main__":
    main()
