#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

EVAL_DIR="${EVAL_DIR:-$PROJECT_ROOT/eval/cognitive}"
CHANGELOG="${CHANGELOG_FILE:-$PROJECT_ROOT/CHANGELOG}"
PYTHON="${PYTHON:-python}"

export PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:$PYTHONPATH}"

"$PYTHON" "$EVAL_DIR/run.py"

DELTA_OUTPUT=$("$PYTHON" "$EVAL_DIR/compare.py")

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
printf '\n## Eval Delta — %s\n\n%s\n' "$TIMESTAMP" "$DELTA_OUTPUT" >> "$CHANGELOG"
