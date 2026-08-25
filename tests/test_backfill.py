from __future__ import annotations

from patina.backfill import ACK_REACTIONS, backfill_decisions_from_reactions
from patina.decisions import get_act_on_rate, record_decision
from patina.graph import insert_observation
from patina.models import Observation


def _make_obs(
    conn,
    obs_id: str,
    *,
    reactions: list[dict] | None = None,
    sender: str | None = None,
    timestamp: float = 1000.0,
) -> None:
    meta = {}
    if reactions is not None:
        meta["reactions"] = reactions
    obs = Observation(
        id=obs_id,
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=timestamp,
        sender_entity_id=sender,
        text="hello",
        metadata=meta,
    )
    insert_observation(conn, obs)


OWNER_ID = "U_OWNER"
OTHER_ID = "U_OTHER"


def test_backfill_inserts_for_owner_ack(db_conn):
    _make_obs(
        db_conn,
        "obs1",
        reactions=[{"name": "thumbsup", "users": [OWNER_ID], "count": 1}],
    )
    result = backfill_decisions_from_reactions(db_conn, [OWNER_ID])
    assert result["inserted"] == 1
    assert result["skipped"] == 0

    row = db_conn.execute("SELECT * FROM decisions WHERE observation_id = 'obs1'").fetchone()
    assert row is not None
    assert row["action"] == "acted"
    assert row["context"] == "backfill:reaction"
    assert row["latency_seconds"] is None


def test_backfill_skips_non_owner_reactions(db_conn):
    _make_obs(
        db_conn,
        "obs1",
        reactions=[{"name": "thumbsup", "users": [OTHER_ID], "count": 1}],
    )
    result = backfill_decisions_from_reactions(db_conn, [OWNER_ID])
    assert result["inserted"] == 0
    assert result["scanned"] == 1


def test_backfill_skips_non_ack_reactions(db_conn):
    _make_obs(
        db_conn,
        "obs1",
        reactions=[{"name": "eyes", "users": [OWNER_ID], "count": 1}],
    )
    result = backfill_decisions_from_reactions(db_conn, [OWNER_ID])
    assert result["inserted"] == 0


def test_backfill_idempotent(db_conn):
    _make_obs(
        db_conn,
        "obs1",
        reactions=[{"name": "+1", "users": [OWNER_ID], "count": 1}],
    )
    r1 = backfill_decisions_from_reactions(db_conn, [OWNER_ID])
    assert r1["inserted"] == 1

    r2 = backfill_decisions_from_reactions(db_conn, [OWNER_ID])
    assert r2["inserted"] == 0
    assert r2["skipped"] == 1

    count = db_conn.execute(
        "SELECT COUNT(*) AS c FROM decisions WHERE observation_id = 'obs1'"
    ).fetchone()["c"]
    assert count == 1


def test_backfill_skips_obs_with_existing_decision(db_conn):
    _make_obs(
        db_conn,
        "obs1",
        reactions=[{"name": "white_check_mark", "users": [OWNER_ID], "count": 1}],
    )
    record_decision(db_conn, "obs1", "dismissed")

    result = backfill_decisions_from_reactions(db_conn, [OWNER_ID])
    assert result["inserted"] == 0
    assert result["skipped"] == 1


def test_backfill_dry_run_does_not_write(db_conn):
    _make_obs(
        db_conn,
        "obs1",
        reactions=[{"name": "thumbsup", "users": [OWNER_ID], "count": 1}],
    )
    result = backfill_decisions_from_reactions(db_conn, [OWNER_ID], dry_run=True)
    assert result["inserted"] == 1

    row = db_conn.execute("SELECT * FROM decisions WHERE observation_id = 'obs1'").fetchone()
    assert row is None


def test_backfill_no_owner_ids_returns_zero(db_conn):
    _make_obs(
        db_conn,
        "obs1",
        reactions=[{"name": "thumbsup", "users": [OWNER_ID], "count": 1}],
    )
    result = backfill_decisions_from_reactions(db_conn, [])
    assert result["inserted"] == 0
    assert result["scanned"] == 0


def test_backfill_multiple_observations(db_conn):
    _make_obs(
        db_conn,
        "obs1",
        reactions=[{"name": "thumbsup", "users": [OWNER_ID], "count": 1}],
    )
    _make_obs(
        db_conn,
        "obs2",
        reactions=[{"name": "heavy_check_mark", "users": [OWNER_ID], "count": 1}],
    )
    _make_obs(
        db_conn,
        "obs3",
        reactions=[{"name": "eyes", "users": [OWNER_ID], "count": 1}],
    )
    _make_obs(db_conn, "obs4")

    result = backfill_decisions_from_reactions(db_conn, [OWNER_ID])
    assert result["inserted"] == 2
    assert result["scanned"] == 3


def test_backfill_mixed_owner_and_non_owner_on_same_reaction(db_conn):
    _make_obs(
        db_conn,
        "obs1",
        reactions=[{"name": "thumbsup", "users": [OTHER_ID, OWNER_ID], "count": 2}],
    )
    result = backfill_decisions_from_reactions(db_conn, [OWNER_ID])
    assert result["inserted"] == 1


def test_backfill_multiple_owner_ids(db_conn):
    second_owner = "U_OWNER2"
    _make_obs(
        db_conn,
        "obs1",
        reactions=[{"name": "+1", "users": [second_owner], "count": 1}],
    )
    result = backfill_decisions_from_reactions(db_conn, [OWNER_ID, second_owner])
    assert result["inserted"] == 1


def test_act_on_rate_changes_after_backfill(db_conn):
    rate_before = get_act_on_rate(db_conn)
    assert rate_before == 0.5

    _make_obs(
        db_conn,
        "obs1",
        reactions=[{"name": "thumbsup", "users": [OWNER_ID], "count": 1}],
    )
    _make_obs(
        db_conn,
        "obs2",
        reactions=[{"name": "+1", "users": [OWNER_ID], "count": 1}],
    )
    backfill_decisions_from_reactions(db_conn, [OWNER_ID])

    rate_after = get_act_on_rate(db_conn)
    assert rate_after == 1.0


def test_backfill_obs_without_reactions_key_skipped(db_conn):
    obs = Observation(
        id="obs1",
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=1000.0,
        sender_entity_id=None,
        text="hi",
        metadata={"channel_name": "general"},
    )
    insert_observation(db_conn, obs)

    result = backfill_decisions_from_reactions(db_conn, [OWNER_ID])
    assert result["scanned"] == 0
    assert result["inserted"] == 0


def test_backfill_empty_reactions_list_skipped(db_conn):
    _make_obs(db_conn, "obs1", reactions=[])
    result = backfill_decisions_from_reactions(db_conn, [OWNER_ID])
    assert result["scanned"] == 0
    assert result["inserted"] == 0


def test_all_ack_reactions_are_recognized(db_conn):
    for i, name in enumerate(sorted(ACK_REACTIONS)):
        _make_obs(
            db_conn,
            f"obs_{i}",
            reactions=[{"name": name, "users": [OWNER_ID], "count": 1}],
        )

    result = backfill_decisions_from_reactions(db_conn, [OWNER_ID])
    assert result["inserted"] == len(ACK_REACTIONS)
