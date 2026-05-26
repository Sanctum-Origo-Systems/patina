"""Golden-file eval: severity keyword detection must be 100% accurate."""

from __future__ import annotations

from patina.priority.scoring import _SEVERITY_RE

POSITIVES = [
    "SEV1: complete outage on mobile endpoints",
    "SEV2: production API latency spike detected",
    "sev-1 alert fired for the payment service",
    "INCIDENT: payment processing failing for EU region",
    "Production outage in progress",
    "CRITICAL: database replication lag at 30 seconds",
    "URGENT: client reporting data loss in dashboard",
    "This is a production issue that needs immediate attention",
    "Complete outage on all endpoints",
    "We have an incident in the payment system",
]

NEGATIVES = [
    "the severity was low, no action needed",
    "production ready for launch next week",
    "Happy Friday team!",
    "Sprint planning notes are in the doc",
    "Can someone review my PR?",
    "Good morning everyone!",
    "The design review went well",
    "Feature flag is live for 10% of users",
    "Database indexes added, query time down 40%",
    "Anyone up for lunch?",
]


def test_positives_detected():
    for text in POSITIVES:
        assert _SEVERITY_RE.search(text), f"Expected severity match: {text!r}"


def test_negatives_not_detected():
    for text in NEGATIVES:
        assert not _SEVERITY_RE.search(text), f"False positive: {text!r}"
