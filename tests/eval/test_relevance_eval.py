"""Tests for eval/deterministic/relevance_eval.py on small hand-built fixtures."""

from __future__ import annotations

import json

import pytest
from eval.deterministic.relevance_eval import (
    EDGE_CASES,
    EDGE_LATE_OBJECTIVE,
    EDGE_UNKNOWN_PARTICIPANT,
    EDGE_UNSEEN_CUSTOMER_DOMAIN,
    MIN_RECALL_ENV,
    STATUS_FALSE_DROP,
    STATUS_KEPT,
    STATUS_MISSING,
    evaluate,
    load_fixture,
    main,
    resolve_min_recall,
)

OWNER_EMAIL = "jane.owner@example.com"
OWNER_TO = [{"name": "Owner, Jane", "email": OWNER_EMAIL}]
LIST_TO = [{"name": "Team All", "email": "team-all@example.com", "isDistributionList": True}]

OBJECTIVE = {
    "id": "obj-fox",
    "label": "The quick brown fox launch",
    "keywords": "quick brown fox",
    "active": True,
    "created_at": "2026-11-10T09:00:00+00:00",
    "participants": ["Quinn, Avery"],
    "customer_domains": ["partner.example"],
}


def _item(item_id, label, sender, *, to=None, recipients=None, edge_case=None):
    facts = {"item_class": ["IPM.Note"], "sender_key": sender}
    if to is not None:
        facts["to"] = to
    if recipients is not None:
        facts["recipients"] = recipients
    item = {
        "id": item_id,
        "label": label,
        "subject": "The quick brown fox",
        "thread_participants": [sender],
        "source_facts": facts,
    }
    if edge_case:
        item["edge_case"] = edge_case
    return item


def _fixture(items):
    return {
        "owner_identifiers": [OWNER_EMAIL, "Owner, Jane"],
        "objectives": [OBJECTIVE],
        "items": items,
    }


# 5 relevant: 2 kept (direct, engagement); 2 dropped as not_direct, 1 as bot_or_list.
# 2 noise items, one kept, so noise never counts toward recall.
MIXED = _fixture(
    [
        _item("r-direct", "relevant", "Example, Jordan", recipients=["Owner, Jane"]),
        _item("r-engaged", "relevant", "riley.sample@partner.example", to=LIST_TO),
        _item("r-list-1", "relevant", "Lee, Casey", recipients=["Team All"]),
        _item("r-list-2", "relevant", "casey.lee@example.com", to=LIST_TO),
        _item("r-bot", "relevant", "no-reply@tickets.example", to=OWNER_TO),
        _item("n-bot", "noise", "newsletter@news.example", to=OWNER_TO),
        _item("n-kept", "noise", "Rowe, Dana", recipients=["Owner, Jane"]),
    ]
)

EDGES = _fixture(
    [
        _item(
            "e-late",
            "relevant",
            "Quinn, Avery",
            recipients=["Harbor Working Group"],
            edge_case=EDGE_LATE_OBJECTIVE,
        ),
        _item(
            "e-unknown",
            "relevant",
            "Drake, Sky (Vendor)",
            recipients=["Owner, Jane"],
            edge_case=EDGE_UNKNOWN_PARTICIPANT,
        ),
        _item(
            "e-unseen",
            "relevant",
            "jamie.sample@northwind-example.test",
            to=LIST_TO,
            edge_case=EDGE_UNSEEN_CUSTOMER_DOMAIN,
        ),
    ]
)


def _write(tmp_path, fixture) -> str:
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    return str(path)


def test_recall_is_kept_relevant_over_total_relevant():
    report = evaluate(MIXED)

    assert report.relevant_total == 5
    assert report.relevant_kept == 2
    assert report.recall == 2 / 5


def test_false_drops_grouped_by_reason():
    report = evaluate(MIXED)

    assert report.false_drops == {"not_direct": 2, "bot_or_list": 1}


def test_edge_cases_have_explicit_status():
    results = {r.edge_case: r for r in evaluate(EDGES).edge_cases}

    assert set(results) == set(EDGE_CASES)
    assert (results[EDGE_LATE_OBJECTIVE].status, results[EDGE_LATE_OBJECTIVE].reason) == (
        STATUS_KEPT,
        "engagement",
    )
    assert (results[EDGE_UNKNOWN_PARTICIPANT].status, results[EDGE_UNKNOWN_PARTICIPANT].reason) == (
        STATUS_KEPT,
        "direct",
    )
    unseen = results[EDGE_UNSEEN_CUSTOMER_DOMAIN]
    assert (unseen.status, unseen.reason, unseen.item_id) == (
        STATUS_FALSE_DROP,
        "not_direct",
        "e-unseen",
    )


def test_absent_edge_case_is_reported_missing_not_silent():
    results = {r.edge_case: r.status for r in evaluate(MIXED).edge_cases}

    assert results == {e: STATUS_MISSING for e in EDGE_CASES}


def test_edge_case_must_be_labeled_relevant(tmp_path):
    bad = _fixture(
        [_item("x", "noise", "Lee, Casey", recipients=["Team All"], edge_case=EDGE_LATE_OBJECTIVE)]
    )

    with pytest.raises(ValueError, match="labeled relevant"):
        load_fixture(_write(tmp_path, bad))


def test_main_fails_below_threshold_and_passes_at_or_above(tmp_path, monkeypatch):
    monkeypatch.delenv(MIN_RECALL_ENV, raising=False)
    path = _write(tmp_path, MIXED)  # recall 0.4

    assert main(["--fixture", path, "--min-recall", "0.5"]) == 1
    assert main(["--fixture", path, "--min-recall", "0.4"]) == 0
    assert main(["--fixture", path, "--min-recall", "0.3"]) == 0


def test_threshold_from_env_and_argument_wins(tmp_path, monkeypatch):
    path = _write(tmp_path, MIXED)  # recall 0.4

    monkeypatch.setenv(MIN_RECALL_ENV, "0.9")
    assert resolve_min_recall() == 0.9
    assert main(["--fixture", path]) == 1

    monkeypatch.setenv(MIN_RECALL_ENV, "0.2")
    assert main(["--fixture", path]) == 0
    assert main(["--fixture", path, "--min-recall", "0.9"]) == 1


def test_report_stdout_has_recall_drops_and_edge_cases(tmp_path, capsys):
    main(["--fixture", _write(tmp_path, {**MIXED, "items": MIXED["items"] + EDGES["items"]})])
    out = capsys.readouterr().out

    assert "recall: 0.500 (4/8 labeled-relevant kept)" in out
    assert "bot_or_list: 1" in out
    assert "not_direct: 3" in out
    assert "late_added_objective [e-late]: kept (engagement)" in out
    assert "unknown_participant [e-unknown]: kept (direct)" in out
    assert "unseen_customer_domain [e-unseen]: false drop (not_direct)" in out
    # Recall comes first, so the store-copy dry run can add its section next to it.
    assert (
        out.index("## Recall") < out.index("## False drops by reason") < out.index("## Edge cases")
    )


def test_default_config_leaves_relevance_filter_off(tmp_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.ingest import _outlook_filter_enabled

    result = CliRunner().invoke(app, ["init", "--home", str(tmp_path)], input="\n")

    assert result.exit_code == 0
    assert _outlook_filter_enabled(tmp_path) is False
