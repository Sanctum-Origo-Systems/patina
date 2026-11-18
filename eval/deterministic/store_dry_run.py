"""Report for the store-copy dry run of the Outlook relevance filter (#668).

``assemble_report`` takes the step-1 fixture eval (``relevance_eval``) and adds
the downstream before/after numbers measured on a store copy, so recall, false
drops and the hidden_allies / catch_up / relationships deltas are one report.
The copy and replay live in ``scripts/relevance_dry_run.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from eval.deterministic.relevance_eval import RelevanceReport, report_sections

DOWNSTREAM_FEATURES = ("hidden_allies", "catch_up", "relationships")
NOT_AVAILABLE = "not available"
DOWNSTREAM_TITLE = "Downstream before/after (filter off -> on, store copy)"
REPLAY_TITLE = "Store-copy replay"


@dataclass
class DownstreamDelta:
    feature: str
    before: int
    after: int

    @property
    def delta(self) -> int:
        return self.after - self.before

    def line(self) -> str:
        return f"{self.feature}: {self.before} -> {self.after} ({self.delta:+d})"


def downstream_deltas(before: dict[str, int], after: dict[str, int]) -> list[DownstreamDelta]:
    """One row per ``DOWNSTREAM_FEATURES`` entry; a feature missing from a side counts 0."""
    return [DownstreamDelta(f, before.get(f, 0), after.get(f, 0)) for f in DOWNSTREAM_FEATURES]


def retain_only_line(count: int | None) -> str:
    """``None`` means RETAIN_ONLY does not exist in this codebase."""
    return f"would-be drops in RETAIN_ONLY: {NOT_AVAILABLE if count is None else count}"


def assemble_report(
    relevance: RelevanceReport,
    deltas: list[DownstreamDelta],
    *,
    min_recall: float,
    replay_lines: list[str] | None = None,
    retain_only: int | None = None,
) -> list[tuple[str, list[str]]]:
    """The step-1 sections with the downstream and replay sections after the false drops."""
    sections = report_sections(relevance, min_recall)
    downstream = [d.line() for d in deltas]
    replay = [*(replay_lines or []), retain_only_line(retain_only)]
    at = next(i for i, (title, _) in enumerate(sections) if title == "False drops by reason") + 1
    sections[at:at] = [(DOWNSTREAM_TITLE, downstream), (REPLAY_TITLE, replay)]
    return sections
