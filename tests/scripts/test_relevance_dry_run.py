"""Tests for scripts/relevance_dry_run.py — store-copy dry run (#668)."""

from __future__ import annotations

import enum
import json
import re
import time
from pathlib import Path

import pytest
import scripts.relevance_dry_run as dry_run
import yaml
from scripts.identity_gate import sha256_file
from scripts.relevance_dry_run import main
from typer.testing import CliRunner

from patina.cli import app
from patina.ingest import _emails_to_chat_messages, _ingest_messages, _outlook_filter_enabled
from patina.models import EmailMessage, IngestionOutcome
from patina.store import connect, get_db_path
from tests.eval.test_relevance_eval import MIXED

SOURCE = "outlook_mcp_email"
OWNER_EMAIL = "jane.owner@example.com"
OWNER_NAME = "Owner, Jane"


def _email(eid: str, sender: str, recipients: list[str], hours_ago: float) -> EmailMessage:
    return EmailMessage(
        id=eid,
        sender=sender,
        subject="The quick brown fox",
        text=f"The quick brown fox jumps over the lazy dog ({eid})",
        timestamp=time.time() - hours_ago * 3600,
        conversation_id=f"conv-{eid}",
        sender_name=None if "@" in sender else sender,
        source_facts={
            "item_class": ["IPM.Note"],
            "sender_key": sender,
            "recipients": recipients,
        },
    )


# Jordan writes to the Owner directly (kept). Casey only writes to a list and
# the newsletter is a bot (dropped), so the filter changes every downstream count.
EMAILS = [
    *[_email(f"direct-{i}", "Example, Jordan", [OWNER_NAME], 2 + i) for i in range(3)],
    *[_email(f"list-{i}", "Lee, Casey", ["Team All"], 3 + i) for i in range(3)],
    _email("bot-0", "no-reply@tickets.example", [OWNER_NAME], 4),
]


def _obs_ids_conn(conn, sender_key: str) -> list[str]:
    rows = conn.execute("SELECT id, metadata FROM observations ORDER BY timestamp").fetchall()
    return [
        r["id"] for r in rows if json.loads(r["metadata"])["source"]["sender_key"] == sender_key
    ]


def _build_store(home: Path) -> Path:
    """A `patina init` home (filter off by default) with the synthetic Outlook emails."""
    result = CliRunner().invoke(app, ["init", "--home", str(home)], input="\n")
    assert result.exit_code == 0
    config_path = home / "config.yaml"
    config = yaml.safe_load(config_path.read_text()) or {}
    config["owner"] = {"emails": [OWNER_EMAIL], "display_names": [OWNER_NAME]}
    config_path.write_text(yaml.safe_dump(config))

    db = get_db_path(home)
    conn = connect(db)
    try:
        _ingest_messages(conn, _emails_to_chat_messages(EMAILS), SOURCE, home=home)
        casey_obs = _obs_ids_conn(conn, "Lee, Casey")
        casey_id = conn.execute(
            "SELECT sender_entity_id FROM observations WHERE id = ?", (casey_obs[0],)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO claims (id, subject_id, predicate, object, confidence,"
            " first_asserted, last_confirmed, source_ids)"
            " VALUES ('claim-casey', ?, 'behavioral:style', 'responsive', 0.8,"
            " '2026-11-01T00:00:00+00:00', '2026-11-01T00:00:00+00:00', ?)",
            (casey_id, json.dumps(casey_obs)),
        )
        conn.execute(
            "INSERT INTO decisions (id, observation_id, action, acted_at)"
            " VALUES ('dec-casey', ?, 'acted', '2026-11-01T00:00:00+00:00')",
            (casey_obs[0],),
        )
        conn.commit()
    finally:
        conn.close()
    return db


def _fixture(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(MIXED), encoding="utf-8")
    return path


@pytest.fixture
def store(tmp_path) -> Path:
    return _build_store(tmp_path / "home")


def _run(store: Path, tmp_path: Path, capsys, *extra: str) -> tuple[int, str]:
    code = main(["--source", str(store), "--fixture", str(_fixture(tmp_path)), *extra])
    return code, capsys.readouterr().out


def _copy_path(out: str) -> Path:
    return Path(re.search(r"^copy: (\S+) \(", out, re.MULTILINE).group(1))


def _row_counts(db: Path) -> dict[str, int]:
    conn = connect(db)
    try:
        return {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("observations", "entities", "claims", "decisions")
        }
    finally:
        conn.close()


def test_one_report_has_recall_false_drops_and_downstream_before_after(store, tmp_path, capsys):
    code, out = _run(store, tmp_path, capsys)

    assert code == 0
    assert out.count("Outlook relevance eval") == 1
    assert "recall: 0.400 (2/5 labeled-relevant kept)" in out
    assert "bot_or_list: 1" in out
    assert "not_direct: 2" in out
    for feature in ("hidden_allies", "catch_up", "relationships"):
        assert re.search(rf"^{feature}: \d+ -> \d+ \([+-]\d+\)$", out, re.MULTILINE), feature
    assert (
        out.index("## Recall")
        < out.index("## False drops by reason")
        < out.index("## Downstream before/after")
    )


def test_report_shows_before_after_and_delta_when_metrics_differ(store, tmp_path, capsys):
    _, out = _run(store, tmp_path, capsys)

    # Before: Jordan and Casey each have 3 messages; the bot has 1. One of Casey's
    # emails has a decision, so catch_up starts at 6 of the 7 emails.
    # After: Casey's list mail and the bot are dropped, Jordan's direct mail stays.
    assert "hidden_allies: 2 -> 1 (-1)" in out
    assert "catch_up: 6 -> 3 (-3)" in out
    assert "relationships: 3 -> 1 (-2)" in out
    assert "would-be drops: 4" in out
    assert "  dropped_bot_or_list: 1" in out
    assert "  dropped_not_direct: 3" in out
    assert "  direct: 3" in out


def test_source_store_unchanged_and_copy_cleaned_up(store, tmp_path, capsys):
    home = store.parent
    before = (sha256_file(store), store.stat().st_mtime_ns, _row_counts(store))
    files_before = sorted(p.name for p in home.iterdir())

    code, out = _run(store, tmp_path, capsys)

    assert code == 0
    assert (sha256_file(store), store.stat().st_mtime_ns, _row_counts(store)) == before
    assert sorted(p.name for p in home.iterdir()) == files_before
    copy = _copy_path(out)
    assert copy.resolve() != store.resolve()
    assert f"copy: {copy} (removed after the run)" in out
    assert not copy.exists()
    assert not copy.parent.exists()


def test_keep_copy_leaves_the_replayed_copy(store, tmp_path, capsys):
    _, out = _run(store, tmp_path, capsys, "--keep-copy")

    copy = _copy_path(out)
    assert f"copy: {copy} (kept)" in out
    assert _row_counts(copy)["observations"] == 3
    assert _row_counts(store)["observations"] == 7


def test_filter_forced_on_for_copy_only(store, tmp_path, capsys):
    home = store.parent
    config_bytes = (home / "config.yaml").read_bytes()
    assert _outlook_filter_enabled(home) is False

    _, out = _run(store, tmp_path, capsys, "--keep-copy")

    copy_home = _copy_path(out).parent
    assert "relevance filter: on (copy only)" in out
    assert _outlook_filter_enabled(copy_home) is True
    # The copy keeps the source's owner config so the replay sees the Owner.
    assert yaml.safe_load((copy_home / "config.yaml").read_text())["owner"]["emails"] == [
        OWNER_EMAIL
    ]
    assert (home / "config.yaml").read_bytes() == config_bytes
    assert _outlook_filter_enabled(home) is False


def test_replay_refuses_a_copy_without_the_filter_on(store, tmp_path):
    copy_home = tmp_path / "unforced"
    copy_home.mkdir()
    (copy_home / "store.db").write_bytes(store.read_bytes())

    with pytest.raises(RuntimeError, match="relevance filter is not on"):
        dry_run.replay_with_filter(copy_home)


def test_retain_only_count_when_present(store, tmp_path, capsys):
    conn = connect(store)
    try:
        conn.execute(
            "UPDATE observations SET outcome = ? WHERE id = ?",
            (IngestionOutcome.RETAIN_ONLY, _obs_ids_conn(conn, "Lee, Casey")[0]),
        )
        # A kept email marked RETAIN_ONLY is not a would-be drop.
        conn.execute(
            "UPDATE observations SET outcome = ? WHERE id = ?",
            (IngestionOutcome.RETAIN_ONLY, _obs_ids_conn(conn, "Example, Jordan")[0]),
        )
        conn.commit()
    finally:
        conn.close()

    code, out = _run(store, tmp_path, capsys)

    assert code == 0
    assert "would-be drops in RETAIN_ONLY: 1" in out


def test_retain_only_marked_not_available_when_absent(store, tmp_path, capsys, monkeypatch):
    class OutcomeWithoutRetainOnly(enum.StrEnum):
        DROP = "DROP"
        RETAIN_AND_EXTRACT = "RETAIN_AND_EXTRACT"

    monkeypatch.setattr(dry_run, "IngestionOutcome", OutcomeWithoutRetainOnly)

    code, out = _run(store, tmp_path, capsys)

    assert code == 0
    assert "would-be drops in RETAIN_ONLY: not available" in out
    assert "hidden_allies: 2 -> 1 (-1)" in out


def test_nonexistent_source_exits_nonzero_and_creates_nothing(tmp_path, capsys):
    missing = tmp_path / "nowhere" / "store.db"

    code = main(["--source", str(missing)])

    assert code != 0
    assert "source store not found" in capsys.readouterr().err
    assert not missing.exists()
    assert not missing.parent.exists()


def test_directory_source_exits_nonzero(tmp_path, capsys):
    as_dir = tmp_path / "store.db"
    as_dir.mkdir()

    code = main(["--source", str(as_dir)])

    assert code != 0
    assert "source store not found" in capsys.readouterr().err
    assert list(as_dir.iterdir()) == []


def test_unreadable_source_exits_nonzero_and_is_untouched(tmp_path, capsys):
    corrupt = tmp_path / "store.db"
    corrupt.write_bytes(b"The quick brown fox is not a SQLite database" * 100)
    before = (sha256_file(corrupt), corrupt.stat().st_mtime_ns)

    code = main(["--source", str(corrupt), "--fixture", str(_fixture(tmp_path))])

    assert code != 0
    assert "cannot read source store" in capsys.readouterr().err
    assert (sha256_file(corrupt), corrupt.stat().st_mtime_ns) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fixture.json", "store.db"]
