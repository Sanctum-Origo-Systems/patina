"""Eval: Outlook relevance filter recall on a labeled, anonymized fixture.

Run: uv run python eval/deterministic/relevance_eval.py [--fixture PATH] [--min-recall X]
The recall threshold comes from ``--min-recall``, else ``PATINA_RELEVANCE_MIN_RECALL``,
else ``DEFAULT_MIN_RECALL``. Exits 1 when recall is below it.

Every item goes through ``patina.ingest.outlook_relevance`` with the fixture's
owner identifiers and objectives; no config or store is read.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from patina.ingest import outlook_relevance
from patina.priority.objectives import Objective

FIXTURE_PATH = Path(__file__).with_name("relevance_fixture.json")
DEFAULT_MIN_RECALL = 0.8
MIN_RECALL_ENV = "PATINA_RELEVANCE_MIN_RECALL"

LABEL_RELEVANT = "relevant"
LABEL_NOISE = "noise"

EDGE_LATE_OBJECTIVE = "late_added_objective"
EDGE_UNKNOWN_PARTICIPANT = "unknown_participant"
EDGE_UNSEEN_CUSTOMER_DOMAIN = "unseen_customer_domain"
EDGE_CASES = (EDGE_LATE_OBJECTIVE, EDGE_UNKNOWN_PARTICIPANT, EDGE_UNSEEN_CUSTOMER_DOMAIN)

STATUS_KEPT = "kept"
STATUS_FALSE_DROP = "false drop"
STATUS_MISSING = "missing"


@dataclass
class EdgeCaseResult:
    edge_case: str
    item_id: str | None
    status: str
    reason: str | None = None

    def line(self) -> str:
        if self.status == STATUS_MISSING:
            return f"{self.edge_case}: {STATUS_MISSING} (no labeled item in fixture)"
        return f"{self.edge_case} [{self.item_id}]: {self.status} ({self.reason})"


@dataclass
class RelevanceReport:
    relevant_total: int = 0
    relevant_kept: int = 0
    # Drop reason -> number of labeled-relevant items it dropped.
    false_drops: dict[str, int] = field(default_factory=dict)
    edge_cases: list[EdgeCaseResult] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return self.relevant_kept / self.relevant_total if self.relevant_total else 0.0


def load_fixture(path: Path = FIXTURE_PATH) -> dict:
    """Load a labeled fixture; raises ``ValueError`` on an unknown label or edge case."""
    with open(path, encoding="utf-8") as f:
        fixture = json.load(f)
    for item in fixture.get("items", []):
        if item.get("label") not in (LABEL_RELEVANT, LABEL_NOISE):
            raise ValueError(f"item {item.get('id')!r}: unknown label {item.get('label')!r}")
        edge = item.get("edge_case")
        if edge is not None and edge not in EDGE_CASES:
            raise ValueError(f"item {item.get('id')!r}: unknown edge case {edge!r}")
        if edge is not None and item["label"] != LABEL_RELEVANT:
            raise ValueError(f"item {item.get('id')!r}: edge cases must be labeled relevant")
    return fixture


def _objective(raw: dict) -> Objective:
    return Objective(
        id=raw["id"],
        label=raw["label"],
        keywords=raw.get("keywords", ""),
        active=raw.get("active", True),
        created_at=raw.get("created_at", ""),
        updated_at=raw.get("updated_at", raw.get("created_at", "")),
        participants=list(raw.get("participants", [])),
        customer_domains=list(raw.get("customer_domains", [])),
    )


def evaluate(fixture: dict) -> RelevanceReport:
    """Run every fixture item through ``outlook_relevance`` and tally the report."""
    owner_identifiers = set(fixture.get("owner_identifiers", []))
    objectives = [_objective(o) for o in fixture.get("objectives", [])]
    report = RelevanceReport()
    seen_edges: set[str] = set()
    for item in fixture.get("items", []):
        relevance = outlook_relevance(
            item.get("source_facts", {}),
            objectives=objectives,
            thread_participants=item.get("thread_participants", []),
            subject=item.get("subject", ""),
            owner_identifiers=owner_identifiers,
        )
        if item["label"] == LABEL_RELEVANT:
            report.relevant_total += 1
            if relevance.keep:
                report.relevant_kept += 1
            else:
                report.false_drops[relevance.reason] = (
                    report.false_drops.get(relevance.reason, 0) + 1
                )
        edge = item.get("edge_case")
        if edge is not None:
            seen_edges.add(edge)
            status = STATUS_KEPT if relevance.keep else STATUS_FALSE_DROP
            report.edge_cases.append(EdgeCaseResult(edge, item["id"], status, relevance.reason))
    for edge in EDGE_CASES:
        if edge not in seen_edges:
            report.edge_cases.append(EdgeCaseResult(edge, None, STATUS_MISSING))
    return report


def report_sections(report: RelevanceReport, min_recall: float) -> list[tuple[str, list[str]]]:
    """The report as ordered ``(title, lines)`` sections.

    Kept as a list so a later store-copy dry run can add its hidden_allies /
    catch_up / relationships before/after section next to ``Recall``.
    """
    verdict = "PASS" if report.recall >= min_recall else "FAIL"
    recall = [
        f"recall: {report.recall:.3f} "
        f"({report.relevant_kept}/{report.relevant_total} labeled-relevant kept)",
        f"threshold: {min_recall:.3f} -> {verdict}",
    ]
    false_drops = [f"{reason}: {n}" for reason, n in sorted(report.false_drops.items())]
    edge_cases = [r.line() for r in report.edge_cases]
    return [
        ("Recall", recall),
        ("False drops by reason", false_drops or ["none"]),
        ("Edge cases", edge_cases),
    ]


def format_report(sections: list[tuple[str, list[str]]]) -> str:
    parts = ["Outlook relevance eval"]
    for title, lines in sections:
        parts.append(f"\n## {title}")
        parts.extend(lines)
    return "\n".join(parts)


def resolve_min_recall(arg: float | None = None) -> float:
    """``--min-recall`` wins, then ``PATINA_RELEVANCE_MIN_RECALL``, then the default."""
    if arg is not None:
        return arg
    env = os.environ.get(MIN_RECALL_ENV)
    return float(env) if env else DEFAULT_MIN_RECALL


def main(argv: list[str] | None = None) -> int:
    """Print the report; return 1 when recall is below the threshold, else 0."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--min-recall", type=float, default=None)
    args = parser.parse_args(argv)

    min_recall = resolve_min_recall(args.min_recall)
    report = evaluate(load_fixture(args.fixture))
    print(format_report(report_sections(report, min_recall)))
    return 0 if report.recall >= min_recall else 1


if __name__ == "__main__":
    sys.exit(main())
