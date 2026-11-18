"""Eval: the checked-in relevance fixture meets the recall gate (CI path)."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

from relevance_eval import (
    EDGE_CASES,
    EDGE_LATE_OBJECTIVE,
    EDGE_UNKNOWN_PARTICIPANT,
    EDGE_UNSEEN_CUSTOMER_DOMAIN,
    FIXTURE_PATH,
    LABEL_NOISE,
    LABEL_RELEVANT,
    MIN_RECALL_ENV,
    STATUS_MISSING,
    evaluate,
    load_fixture,
    main,
)

from patina.adapters.outlook_mcp import normalize_sender

UNSEEN_DOMAIN = "northwind-example.test"


def _edge_items(fixture: dict, edge: str) -> list[dict]:
    return [i for i in fixture["items"] if i.get("edge_case") == edge]


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_fixture_has_every_edge_case_label():
    fixture = load_fixture()
    missing = [e for e in EDGE_CASES if not _edge_items(fixture, e)]
    assert not missing, f"fixture is missing edge-case labels: {missing}"


def test_fixture_has_relevant_and_noise_items():
    labels = {i["label"] for i in load_fixture()["items"]}
    assert labels == {LABEL_RELEVANT, LABEL_NOISE}


def test_late_added_objective_was_created_after_the_email():
    fixture = load_fixture()
    created = [_time(o["created_at"]) for o in fixture["objectives"]]
    for item in _edge_items(fixture, EDGE_LATE_OBJECTIVE):
        assert any(c > _time(item["received_at"]) for c in created), item["id"]


def test_unknown_participant_is_on_no_objective():
    fixture = load_fixture()
    known = {normalize_sender(p) for o in fixture["objectives"] for p in o["participants"]}
    known |= set(fixture["owner_identifiers"])
    for item in _edge_items(fixture, EDGE_UNKNOWN_PARTICIPANT):
        assert normalize_sender(item["source_facts"]["sender_key"]) not in known, item["id"]


def test_unseen_customer_domain_is_listed_on_no_objective():
    fixture = load_fixture()
    domains = {d for o in fixture["objectives"] for d in o["customer_domains"]}
    items = _edge_items(fixture, EDGE_UNSEEN_CUSTOMER_DOMAIN)
    assert any(i["source_facts"]["sender_key"].endswith(f"@{UNSEEN_DOMAIN}") for i in items)
    assert UNSEEN_DOMAIN not in domains


def test_every_edge_case_has_an_explicit_status():
    report = evaluate(load_fixture())
    assert {r.edge_case for r in report.edge_cases} == set(EDGE_CASES)
    assert all(r.status != STATUS_MISSING and r.reason for r in report.edge_cases)


def test_checked_in_fixture_meets_recall_gate(capsys, monkeypatch):
    monkeypatch.delenv(MIN_RECALL_ENV, raising=False)

    assert main([]) == 0
    out = capsys.readouterr().out
    assert "recall: " in out
    assert "## False drops by reason" in out
    for edge in EDGE_CASES:
        assert edge in out


def test_eval_runs_without_a_store(tmp_path):
    """AC: HOME is an empty directory; the eval completes and creates nothing there."""
    env = {k: v for k, v in os.environ.items() if k != MIN_RECALL_ENV}
    env["HOME"] = str(tmp_path)
    script = FIXTURE_PATH.with_name("relevance_eval.py")

    result = subprocess.run(
        [sys.executable, str(script)], env=env, capture_output=True, text=True, timeout=60
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "recall: " in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_default_config_leaves_relevance_filter_off(tmp_path):
    from typer.testing import CliRunner

    from patina.cli import app
    from patina.ingest import _outlook_filter_enabled

    assert _outlook_filter_enabled(tmp_path) is False
    result = CliRunner().invoke(app, ["init", "--home", str(tmp_path)], input="\n")
    assert result.exit_code == 0
    assert (tmp_path / "config.yaml").exists()
    assert _outlook_filter_enabled(tmp_path) is False
