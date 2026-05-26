"""Eval: commitment detection via regex patterns.

Threshold: precision >= 0.85, recall >= 0.75
"""

from __future__ import annotations

import re

_COMMITMENT_RE = re.compile(
    r"\b(I'll|I will|we'll|we will|will send|will get|will take|will follow|"
    r"will review|will set up|will update|let me|I can|I'm going to|"
    r"going to handle|take care of|get back to you|have .+ ready by)\b",
    re.IGNORECASE,
)

POSITIVE_EXAMPLES = [
    ("I'll have the report ready by end of day", True),
    ("I'll get back to you by tomorrow", True),
    ("Will send the updated spec by Friday", True),
    ("I'll take care of the deployment", True),
    ("Let me follow up with the vendor on this", True),
    ("I'll review and merge by EOD", True),
    ("I'll set up the meeting for next week", True),
    ("Will update the ticket after I investigate", True),
    ("I'm going to handle the frontend changes", True),
    ("I can get that done by Thursday", True),
    ("We will send the proposal tomorrow", True),
    ("I'll have it ready by noon", True),
]

NEGATIVE_EXAMPLES = [
    ("Good morning everyone!", False),
    ("Has anyone seen the dashboard?", False),
    ("Happy Friday team!", False),
    ("Thanks for the great work", False),
    ("The design review went well", False),
    ("QA found a regression", False),
    ("Sprint planning notes are in the doc", False),
    ("Feature flag is live for 10%", False),
    ("Database indexes added", False),
    ("Performance tests look good", False),
]


def _is_commitment(text: str) -> bool:
    return bool(_COMMITMENT_RE.search(text))


def test_commitment_precision():
    tp = sum(1 for text, _ in POSITIVE_EXAMPLES if _is_commitment(text))
    fp = sum(1 for text, _ in NEGATIVE_EXAMPLES if _is_commitment(text))
    precision = tp / max(tp + fp, 1)
    assert precision >= 0.85, f"Precision {precision:.2f} < 0.85"


def test_commitment_recall():
    tp = sum(1 for text, _ in POSITIVE_EXAMPLES if _is_commitment(text))
    fn = sum(1 for text, _ in POSITIVE_EXAMPLES if not _is_commitment(text))
    recall = tp / max(tp + fn, 1)
    assert recall >= 0.75, f"Recall {recall:.2f} < 0.75"


def test_positive_examples():
    for text, expected in POSITIVE_EXAMPLES:
        result = _is_commitment(text)
        if expected:
            assert result, f"Missed commitment: {text!r}"


def test_negative_examples():
    for text, expected in NEGATIVE_EXAMPLES:
        result = _is_commitment(text)
        if not expected:
            assert not result, f"False positive: {text!r}"
