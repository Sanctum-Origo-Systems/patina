"""Extract beliefs from observations — thin wrapper around patina.beliefs.extractor.

Prefer: uv run patina extract [--batch-size 10] [--limit 500] [--model sonnet] [--dry-run]
"""

from __future__ import annotations

import argparse

from patina.beliefs.extractor import extract_beliefs

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract beliefs from observations")
    parser.add_argument("--batch-size", type=int, default=10, help="Messages per LLM call")
    parser.add_argument("--limit", type=int, default=500, help="Max observations to process")
    parser.add_argument("--model", type=str, default="sonnet", help="Claude model to use")
    parser.add_argument("--dry-run", action="store_true", help="Don't call LLM, just count")
    args = parser.parse_args()

    extract_beliefs(
        batch_size=args.batch_size,
        limit=args.limit,
        model=args.model,
        dry_run=args.dry_run,
    )
