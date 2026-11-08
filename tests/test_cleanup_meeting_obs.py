from __future__ import annotations

import json
from datetime import datetime

import pytest
from typer.testing import CliRunner

import patina.cleanup_meeting_obs as cleanup
from patina.adapters.outlook_mcp import _email_from_raw
from patina.cleanup_meeting_obs import (
    NO_CLASS_FIELDS,
    NO_SOURCE_ID,
    NOT_IN_CURRENT_INBOX,
    NOT_MEETING,
    REFETCH_UNAVAILABLE,
    SELECTED,
    UNDETERMINED,
    RemovalRefused,
    classify,
    remove_meeting_observations,
    select_meeting_observations,
)
from patina.cli import app
from patina.graph import insert_claim, insert_observation, upsert_relationship
from patina.models import Claim, Observation, Relationship
from patina.store import connect, run_pending_migrations

runner = CliRunner()

RECEIVED = "2026-10-01T15:04:05Z"
RECEIVED_TS = datetime.fromisoformat(RECEIVED).timestamp()


def _payload_580(message_class="IPM.Schedule.Meeting.Resp.Pos", conv_id="CONV_FOX_580"):
    """Anonymized shape of the #580 meeting response that reached the store."""
    return {
        "conversationId": conv_id,
        "topic": "The quick brown fox sync",
        "senders": ["Example, Jordan"],
        "from": {"name": "Jordan Example", "email": "jordan@example.com"},
        "recipients": ["Taylor, Morgan"],
        "preview": "",
        "receivedDateTime": RECEIVED,
        "itemClasses": [message_class],
    }


class FakeAdapter:
    def __init__(self, payloads: dict[str, dict | None] | None = None):
        self.payloads = payloads or {}
        self.calls: list[str] = []

    def get_raw_message(self, source_id: str) -> dict | None:
        self.calls.append(source_id)
        return self.payloads.get(source_id)


@pytest.fixture
def store(db_path):
    conn = connect(db_path)
    run_pending_migrations(conn)
    conn.execute(
        "INSERT INTO entities (id, type, name, aliases, metadata, first_seen, last_seen)"
        " VALUES ('ent_jordan', 'person', 'Jordan Example', '[]', '{}', 'x', 'x')"
    )
    conn.commit()
    yield conn
    conn.close()


_DEFAULT = object()


def _add_obs(
    conn,
    obs_id,
    metadata,
    *,
    ts=RECEIVED_TS,
    source="outlook_mcp_email",
    processed=0,
    channel_id=_DEFAULT,
    thread_id=None,
):
    insert_observation(
        conn,
        Observation(
            id=obs_id,
            source=source,
            channel_id=f"email:{obs_id}" if channel_id is _DEFAULT else channel_id,
            thread_id=thread_id,
            timestamp=ts,
            sender_entity_id=None,
            text="[Subject: The quick brown fox sync] [Participants: Jordan Example]\n",
            metadata=metadata,
            processed=processed,
        ),
    )
    conn.commit()


def _add_ingested_580(conn, obs_id, payload):
    """Store the payload as ingest does: no class fields, source ID kept in metadata."""
    em = _email_from_raw(payload)
    insert_observation(
        conn,
        Observation(
            id=obs_id,
            source="outlook_mcp_email",
            channel_id=f"email:{em.conversation_id or em.id}",
            thread_id=em.conversation_id,
            timestamp=em.timestamp,
            sender_entity_id=None,
            text=em.text,
            metadata={"channel_name": None, "reactions": [], "conversationId": em.id},
        ),
    )
    conn.commit()


LIVE_META = {"channel_name": None, "reactions": []}
LIVE_META_ORGANIZER = {"channel_name": None, "reactions": [], "organizer_dn": "Example, Jordan"}


def _add_live(conn, obs_id, conv_id, *, meta=LIVE_META, ts=RECEIVED_TS, thread=True):
    """Store a row in the live store shape: no ID in metadata, ID in thread/channel columns."""
    _add_obs(
        conn,
        obs_id,
        dict(meta),
        ts=ts,
        channel_id=f"email:{conv_id}" if conv_id else None,
        thread_id=conv_id if thread else None,
    )


def _cite(conn, claim_id, obs_ids):
    insert_claim(
        conn,
        Claim(
            id=claim_id,
            subject_id="ent_jordan",
            predicate="attends",
            object="The quick brown fox sync",
            source_ids=obs_ids,
        ),
    )
    conn.commit()


def _ids(selection):
    return {s.observation_id for s in selection.selected}


class TestSelectionFromRefetch:
    @pytest.mark.parametrize(
        "message_class",
        [
            "IPM.Schedule.Meeting.Resp.Pos",
            "IPM.Schedule.Meeting.Request",
            "IPM.Schedule.Meeting.Canceled",
        ],
    )
    def test_ingested_580_row_selected(self, store, db_path, message_class):
        payload = _payload_580(message_class)
        _add_ingested_580(store, "obs_fox", payload)
        adapter = FakeAdapter({"CONV_FOX_580": payload})

        selection = select_meeting_observations(db_path, adapter)

        assert _ids(selection) == {"obs_fox"}
        assert adapter.calls == ["CONV_FOX_580"]
        row = selection.selected[0]
        assert row.item_classes == [message_class]
        assert row.timestamp == RECEIVED_TS
        assert row.processed is False
        assert row.citing_claims == 0

    def test_refetch_uses_id_when_no_conversation_id(self, store, db_path):
        _add_obs(store, "obs_a", {"id": "MSG_001"})
        adapter = FakeAdapter({"MSG_001": {"messageClass": "IPM.Schedule.Meeting.Request"}})

        assert _ids(select_meeting_observations(db_path, adapter)) == {"obs_a"}
        assert adapter.calls == ["MSG_001"]


class TestClassifyFromMetadata:
    @pytest.mark.parametrize(
        "meta",
        [
            {"itemClasses": ["IPM.Schedule.Meeting.Resp.Pos"], "conversationId": "C1"},
            {"messageClass": "IPM.Schedule.Meeting.Request", "conversationId": "C1"},
            {"message_class": "IPM.Schedule.Meeting.Canceled", "id": "C1"},
        ],
    )
    def test_class_fields_used_without_fetch(self, store, db_path, meta):
        _add_obs(store, "obs_meta", meta)
        adapter = FakeAdapter({"C1": {"itemClasses": ["IPM.Note"]}})

        selection = select_meeting_observations(db_path, adapter)

        assert _ids(selection) == {"obs_meta"}
        assert adapter.calls == []

    def test_note_with_empty_preview_not_selected(self, store, db_path):
        _add_obs(store, "obs_note", {"itemClasses": ["IPM.Note"], "preview": ""})

        selection = select_meeting_observations(db_path, FakeAdapter())

        assert selection.selected == []
        assert selection.undetermined.count == 0
        assert selection.not_meeting_count == 1

    def test_mixed_note_and_meeting_not_selected(self, store, db_path):
        meta = {"itemClasses": ["IPM.Note", "IPM.Schedule.Meeting.Resp.Pos"]}
        _add_obs(store, "obs_mixed", meta)

        selection = select_meeting_observations(db_path, FakeAdapter())

        assert selection.selected == []
        assert selection.undetermined.count == 0

    def test_classify_verdicts(self):
        meeting = {"messageClass": "IPM.Schedule.Meeting.Request"}
        assert classify(meeting, None) == (SELECTED, ["IPM.Schedule.Meeting.Request"])
        assert classify({"itemClasses": ["IPM.Note"]}, None) == (NOT_MEETING, [])
        assert classify({}, None) == (UNDETERMINED, [])
        assert classify({"conversationId": "C1"}, None) == (UNDETERMINED, [])


class TestUndetermined:
    def test_unclassifiable_rows_in_bucket(self, store, db_path):
        _add_obs(store, "obs_no_id", {"channel_name": None}, ts=1000.0, channel_id=None)
        _add_obs(store, "obs_none", {"conversationId": "GONE"}, ts=3000.0)
        _add_obs(store, "obs_classless", {"conversationId": "BARE"}, ts=2000.0)
        bare = _payload_580()
        del bare["itemClasses"]
        adapter = FakeAdapter({"GONE": None, "BARE": bare})

        selection = select_meeting_observations(db_path, adapter)

        assert selection.selected == []
        assert selection.undetermined.count == 3
        assert selection.undetermined.earliest == 1000.0
        assert selection.undetermined.latest == 3000.0
        assert set(selection.undetermined.observation_ids) == {
            "obs_no_id",
            "obs_none",
            "obs_classless",
        }
        assert selection.undetermined.reasons == {
            NO_SOURCE_ID: 1,
            NOT_IN_CURRENT_INBOX: 1,
            NO_CLASS_FIELDS: 1,
            REFETCH_UNAVAILABLE: 0,
        }
        assert adapter.calls == ["BARE", "GONE"]

    def test_no_adapter_means_undetermined(self, store, db_path):
        _add_obs(store, "obs_x", {"conversationId": "C1"})

        selection = select_meeting_observations(db_path)

        assert selection.selected == []
        assert selection.undetermined.count == 1
        assert selection.undetermined.reasons[REFETCH_UNAVAILABLE] == 1


class TestLiveRowShape:
    """#609: live rows keep the conversation ID in thread_id/channel_id, not metadata."""

    @pytest.mark.parametrize("meta", [LIVE_META, LIVE_META_ORGANIZER])
    def test_id_read_from_thread_id(self, store, db_path, meta):
        _add_live(store, "obs_fox", "CONV_FOX_580", meta=meta)
        adapter = FakeAdapter({"CONV_FOX_580": _payload_580()})

        selection = select_meeting_observations(db_path, adapter)

        assert _ids(selection) == {"obs_fox"}
        assert adapter.calls == ["CONV_FOX_580"]
        assert selection.selected[0].item_classes == ["IPM.Schedule.Meeting.Resp.Pos"]
        assert selection.undetermined.count == 0

    def test_id_read_from_channel_id_when_thread_id_null(self, store, db_path):
        _add_live(store, "obs_fox", "CONV_FOX_580", thread=False)
        adapter = FakeAdapter({"CONV_FOX_580": _payload_580()})

        selection = select_meeting_observations(db_path, adapter)

        assert _ids(selection) == {"obs_fox"}
        assert adapter.calls == ["CONV_FOX_580"]

    def test_thread_id_preferred_over_channel_id(self, store, db_path):
        _add_obs(
            store,
            "obs_fox",
            dict(LIVE_META),
            thread_id="CONV_FOX_580",
            channel_id="email:OTHER",
        )
        adapter = FakeAdapter({"CONV_FOX_580": _payload_580()})

        assert _ids(select_meeting_observations(db_path, adapter)) == {"obs_fox"}
        assert adapter.calls == ["CONV_FOX_580"]

    def test_metadata_id_preferred_over_columns(self, store, db_path):
        _add_obs(
            store,
            "obs_fox",
            {**LIVE_META, "conversationId": "CONV_FOX_580"},
            thread_id="OTHER",
            channel_id="email:OTHER",
        )
        adapter = FakeAdapter({"CONV_FOX_580": _payload_580()})

        assert _ids(select_meeting_observations(db_path, adapter)) == {"obs_fox"}
        assert adapter.calls == ["CONV_FOX_580"]

    def test_conversation_outside_listing_is_not_in_current_inbox(self, store, db_path):
        _add_live(store, "obs_old", "CONV_OLD_FOX")
        adapter = FakeAdapter({"CONV_FOX_580": _payload_580()})

        selection = select_meeting_observations(db_path, adapter)

        assert selection.selected == []
        assert selection.undetermined.count == 1
        assert selection.undetermined.reasons[NOT_IN_CURRENT_INBOX] == 1
        assert adapter.calls == ["CONV_OLD_FOX"]

    @pytest.mark.parametrize("channel_id", [None, "email:", "slack:C123"])
    def test_no_id_anywhere_is_no_source_id(self, store, db_path, channel_id):
        _add_obs(store, "obs_bare", dict(LIVE_META), channel_id=channel_id)
        adapter = FakeAdapter()

        selection = select_meeting_observations(db_path, adapter)

        assert selection.undetermined.count == 1
        assert selection.undetermined.reasons[NO_SOURCE_ID] == 1
        assert adapter.calls == []

    def test_refetch_without_class_fields_is_no_class_fields(self, store, db_path):
        _add_live(store, "obs_fox", "CONV_FOX_580")
        bare = _payload_580()
        del bare["itemClasses"]

        selection = select_meeting_observations(db_path, FakeAdapter({"CONV_FOX_580": bare}))

        assert selection.undetermined.reasons[NO_CLASS_FIELDS] == 1

    def test_zero_timestamp_counted_and_left_out_of_range(self, store, db_path):
        _add_live(store, "obs_epoch", "CONV_EPOCH", ts=0.0)
        _add_live(store, "obs_a", "CONV_A", ts=2000.0)
        _add_live(store, "obs_b", "CONV_B", ts=4000.0)

        selection = select_meeting_observations(db_path, FakeAdapter())

        und = selection.undetermined
        assert und.count == 3
        assert und.zero_timestamp == 1
        assert und.earliest == 2000.0
        assert und.latest == 4000.0
        assert "obs_epoch" in und.observation_ids
        assert und.reasons[NOT_IN_CURRENT_INBOX] == 3

    def test_only_zero_timestamp_rows_have_no_range(self, store, db_path):
        _add_live(store, "obs_epoch", "CONV_EPOCH", ts=0.0)

        und = select_meeting_observations(db_path, FakeAdapter()).undetermined

        assert und.count == 1
        assert und.zero_timestamp == 1
        assert und.earliest is None
        assert und.latest is None

    def test_refetched_note_with_empty_preview_not_meeting(self, store, db_path):
        _add_live(store, "obs_note", "CONV_NOTE")
        note = _payload_580("IPM.Note", conv_id="CONV_NOTE")
        store.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = db_path.read_bytes()

        selection = select_meeting_observations(db_path, FakeAdapter({"CONV_NOTE": note}))

        assert selection.selected == []
        assert selection.undetermined.count == 0
        assert selection.not_meeting_count == 1
        assert db_path.read_bytes() == before

    def test_live_dry_run_leaves_store_byte_identical(self, store, db_path):
        _add_live(store, "obs_fox", "CONV_FOX_580")
        _add_live(store, "obs_org", "CONV_ORG", meta=LIVE_META_ORGANIZER, thread=False)
        _add_live(store, "obs_old", "CONV_OLD_FOX")
        _add_live(store, "obs_epoch", None, ts=0.0)
        store.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = db_path.read_bytes()
        adapter = FakeAdapter(
            {
                "CONV_FOX_580": _payload_580(),
                "CONV_ORG": _payload_580("IPM.Schedule.Meeting.Request", conv_id="CONV_ORG"),
            }
        )

        selection = select_meeting_observations(db_path, adapter)

        assert _ids(selection) == {"obs_fox", "obs_org"}
        assert selection.undetermined.reasons[NOT_IN_CURRENT_INBOX] == 1
        assert selection.undetermined.reasons[NO_SOURCE_ID] == 1
        assert selection.undetermined.zero_timestamp == 1
        assert db_path.read_bytes() == before


class TestDecidedByIsMeetingMessage:
    def test_patching_adapter_function_flips_selection(self, store, db_path, monkeypatch):
        _add_obs(store, "obs_meet", {"itemClasses": ["IPM.Schedule.Meeting.Request"]})
        _add_obs(store, "obs_note", {"itemClasses": ["IPM.Note"]})

        assert _ids(select_meeting_observations(db_path)) == {"obs_meet"}

        monkeypatch.setattr(
            "patina.adapters.outlook_mcp._is_meeting_message",
            lambda raw: raw.get("itemClasses") == ["IPM.Note"],
        )
        assert _ids(select_meeting_observations(db_path)) == {"obs_note"}

        monkeypatch.setattr("patina.adapters.outlook_mcp._is_meeting_message", lambda raw: False)
        assert _ids(select_meeting_observations(db_path)) == set()


class TestSelectionReport:
    def test_counts_citations_timestamps_and_processed(self, store, db_path):
        meeting = {"itemClasses": ["IPM.Schedule.Meeting.Resp.Pos"]}
        _add_obs(store, "obs_1", meeting, ts=1000.0, processed=1)
        _add_obs(store, "obs_2", meeting, ts=5000.0)
        _add_obs(store, "obs_3", meeting, ts=3000.0)
        _add_obs(store, "obs_slack", meeting, source="slack_mcp")
        _cite(store, "claim_a", ["obs_1", "obs_2"])
        _cite(store, "claim_b", ["obs_1"])

        selection = select_meeting_observations(db_path)

        assert _ids(selection) == {"obs_1", "obs_2", "obs_3"}
        assert selection.selected_count == 3
        by_id = {s.observation_id: s for s in selection.selected}
        assert by_id["obs_1"].citing_claims == 2
        assert by_id["obs_2"].citing_claims == 1
        assert by_id["obs_3"].citing_claims == 0
        assert selection.total_citations == 3
        assert selection.earliest == 1000.0
        assert selection.latest == 5000.0
        assert selection.processed_count == 1
        assert selection.unprocessed_count == 2

    def test_selection_leaves_store_byte_identical(self, store, db_path):
        _add_ingested_580(store, "obs_fox", _payload_580())
        _add_obs(store, "obs_meta", {"itemClasses": ["IPM.Schedule.Meeting.Request"]})
        store.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = db_path.read_bytes()

        selection = select_meeting_observations(
            db_path, FakeAdapter({"CONV_FOX_580": _payload_580()})
        )

        assert selection.selected_count == 2
        assert db_path.read_bytes() == before

    def test_selection_on_closed_store_is_byte_identical(self, db_path):
        conn = connect(db_path)
        _add_obs(conn, "obs_meta", {"itemClasses": ["IPM.Schedule.Meeting.Request"]})
        conn.close()
        before = db_path.read_bytes()

        selection = select_meeting_observations(db_path)

        assert selection.selected_count == 1
        assert db_path.read_bytes() == before


class TestRemoval:
    def _seed_mixed(self, conn):
        _add_ingested_580(conn, "obs_fox", _payload_580())
        _add_obs(conn, "obs_meta", {"itemClasses": ["IPM.Schedule.Meeting.Canceled"]})
        _add_obs(conn, "obs_note", {"itemClasses": ["IPM.Note"], "preview": ""})
        _add_obs(conn, "obs_unknown", {"channel_name": None})

    def _source_ids(self, conn):
        rows = conn.execute(
            "SELECT id FROM observations WHERE source = 'outlook_mcp_email'"
        ).fetchall()
        return {r["id"] for r in rows}

    def test_removes_only_selected_rows_with_backup(self, store, db_path):
        self._seed_mixed(store)
        adapter = FakeAdapter({"CONV_FOX_580": _payload_580()})
        selection = select_meeting_observations(db_path, adapter)

        result = remove_meeting_observations(db_path, selection)

        assert result.backup_path is not None
        assert result.backup_path.exists()
        assert result.deleted == 2
        assert result.before_count == 4
        assert result.after_count == 2
        assert self._source_ids(store) == {"obs_note", "obs_unknown"}

        backup = connect(result.backup_path)
        try:
            assert self._source_ids(backup) == {"obs_fox", "obs_meta", "obs_note", "obs_unknown"}
        finally:
            backup.close()

        fts = store.execute(
            "SELECT COUNT(*) AS c FROM observations_fts WHERE observations_fts MATCH 'fox'"
        ).fetchone()["c"]
        assert fts == 2

    def test_second_run_selects_nothing_and_changes_nothing(self, store, db_path, monkeypatch):
        self._seed_mixed(store)
        adapter = FakeAdapter({"CONV_FOX_580": _payload_580()})
        remove_meeting_observations(db_path, select_meeting_observations(db_path, adapter))
        store.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = db_path.read_bytes()
        backups = set(db_path.parent.glob("*.bak.*"))

        def _no_backup(path):
            raise AssertionError("backup_store must not run when nothing is selected")

        monkeypatch.setattr(cleanup, "backup_store", _no_backup)
        selection = select_meeting_observations(db_path, adapter)
        result = remove_meeting_observations(db_path, selection)

        assert selection.selected_count == 0
        assert result.deleted == 0
        assert result.backup_path is None
        assert result.before_count == result.after_count == 2
        assert db_path.read_bytes() == before
        assert set(db_path.parent.glob("*.bak.*")) == backups

    def test_refuses_when_selected_rows_are_cited(self, store, db_path, monkeypatch):
        self._seed_mixed(store)
        _cite(store, "claim_fox", ["obs_fox"])
        selection = select_meeting_observations(
            db_path, FakeAdapter({"CONV_FOX_580": _payload_580()})
        )
        backup_calls = []
        monkeypatch.setattr(cleanup, "backup_store", lambda p: backup_calls.append(p))

        with pytest.raises(RemovalRefused) as exc:
            remove_meeting_observations(db_path, selection)

        assert [r.observation_id for r in exc.value.rows] == ["obs_fox"]
        assert backup_calls == []
        assert self._source_ids(store) == {"obs_fox", "obs_meta", "obs_note", "obs_unknown"}

    def test_refuses_when_claim_added_after_selection(self, store, db_path, monkeypatch):
        self._seed_mixed(store)
        selection = select_meeting_observations(db_path)
        assert _ids(selection) == {"obs_meta"}
        _cite(store, "claim_late", ["obs_meta"])
        backup_calls = []
        monkeypatch.setattr(cleanup, "backup_store", lambda p: backup_calls.append(p))

        with pytest.raises(RemovalRefused):
            remove_meeting_observations(db_path, selection)

        assert backup_calls == []
        assert "obs_meta" in self._source_ids(store)

    def test_backup_taken_before_delete(self, store, db_path, monkeypatch):
        self._seed_mixed(store)
        selection = select_meeting_observations(db_path)
        seen = []

        def _spy(path):
            seen.append(self._source_ids(store))
            return path.with_suffix(".db.bak.test")

        monkeypatch.setattr(cleanup, "backup_store", _spy)
        result = remove_meeting_observations(db_path, selection)

        assert seen == [{"obs_fox", "obs_meta", "obs_note", "obs_unknown"}]
        assert result.backup_path == db_path.with_suffix(".db.bak.test")


MEETING_META = {"itemClasses": ["IPM.Schedule.Meeting.Request"]}
NOTE_META = {"itemClasses": ["IPM.Note"]}
LEGACY_SOURCE_IDS = [[], ["extraction"], ["behavioral_extraction"], ["envoy_migration"]]


def _relate(conn, rel_id, obs_ids):
    conn.execute(
        "INSERT OR IGNORE INTO entities (id, type, name, aliases, metadata, first_seen, last_seen)"
        " VALUES ('ent_taylor', 'person', 'Taylor Morgan', '[]', '{}', 'x', 'x')"
    )
    upsert_relationship(
        conn,
        Relationship(
            id=rel_id,
            subject_id="ent_jordan",
            predicate="works-with",
            object_id="ent_taylor",
            source_ids=obs_ids,
        ),
    )


def _citations(db_path, obs_ids):
    conn = connect(db_path)
    try:
        return cleanup._citation_counts(conn, set(obs_ids))
    finally:
        conn.close()


def _invoke(db_path, *args):
    return runner.invoke(app, ["cleanup-meeting-obs", *args, "--home", str(db_path.parent)])


class TestProvenance:
    """#615: only real observation ids cite; rows with none are unknown provenance."""

    def test_claim_citing_selected_row(self, store, db_path):
        _add_obs(store, "obs_meet", MEETING_META)
        _cite(store, "claim_fox", ["obs_meet"])

        assert _citations(db_path, {"obs_meet"}) == ({"obs_meet": 1}, 0)
        selection = select_meeting_observations(db_path)
        assert selection.selected[0].citing_claims == 1
        assert selection.total_citations == 1
        assert selection.unknown_provenance == 0

    @pytest.mark.parametrize("source_ids", LEGACY_SOURCE_IDS)
    def test_legacy_label_or_empty_is_unknown_provenance(self, store, db_path, source_ids):
        _add_obs(store, "obs_meet", MEETING_META)
        _cite(store, "claim_old", source_ids)

        assert _citations(db_path, {"obs_meet"}) == ({"obs_meet": 0}, 1)

    def test_null_source_ids_is_unknown_provenance(self, store, db_path):
        _add_obs(store, "obs_meet", MEETING_META)
        _cite(store, "claim_null", [])
        store.execute("UPDATE claims SET source_ids = NULL")
        store.commit()

        assert _citations(db_path, {"obs_meet"}) == ({"obs_meet": 0}, 1)

    def test_label_never_cites_even_if_passed_as_selected(self, store, db_path):
        _add_obs(store, "obs_meet", MEETING_META)
        _cite(store, "claim_old", ["extraction"])

        counts, unknown = _citations(db_path, {"obs_meet", "extraction"})

        assert counts == {"obs_meet": 0, "extraction": 0}
        assert unknown == 1

    def test_unselected_real_id_is_neither(self, store, db_path):
        _add_obs(store, "obs_meet", MEETING_META)
        _add_obs(store, "obs_note", NOTE_META)
        _cite(store, "claim_note", ["obs_note"])

        assert _citations(db_path, {"obs_meet"}) == ({"obs_meet": 0}, 0)
        selection = select_meeting_observations(db_path)
        assert _ids(selection) == {"obs_meet"}
        assert selection.total_citations == 0
        assert selection.unknown_provenance == 0

    @pytest.mark.parametrize(
        ("source_ids", "expected"),
        [
            (["extraction", "obs_meet"], ({"obs_meet": 1}, 0)),
            (["obs_note", "behavioral_extraction"], ({"obs_meet": 0}, 0)),
        ],
    )
    def test_mixed_label_and_real_id_classified_by_real_id(
        self, store, db_path, source_ids, expected
    ):
        _add_obs(store, "obs_meet", MEETING_META)
        _add_obs(store, "obs_note", NOTE_META)
        _cite(store, "claim_mixed", source_ids)

        assert _citations(db_path, {"obs_meet"}) == expected

    def test_relationship_citing_selected_row(self, store, db_path):
        _add_obs(store, "obs_meet", MEETING_META)
        _relate(store, "rel_fox", ["obs_meet"])

        assert _citations(db_path, {"obs_meet"}) == ({"obs_meet": 1}, 0)
        assert select_meeting_observations(db_path).total_citations == 1

    def test_relationship_with_legacy_label_is_unknown_provenance(self, store, db_path):
        _add_obs(store, "obs_meet", MEETING_META)
        _relate(store, "rel_old", ["extraction"])

        assert _citations(db_path, {"obs_meet"}) == ({"obs_meet": 0}, 1)

    def test_cited_by_relationship_refuses_removal(self, store, db_path):
        _add_obs(store, "obs_meet", MEETING_META)
        _relate(store, "rel_fox", ["obs_meet"])

        with pytest.raises(RemovalRefused):
            remove_meeting_observations(db_path, select_meeting_observations(db_path))

        assert store.execute("SELECT COUNT(*) AS c FROM observations").fetchone()["c"] == 1


class TestProvenanceCli:
    def test_citing_claim_in_text_and_json(self, store, db_path):
        _add_obs(store, "obs_meet", MEETING_META)
        _cite(store, "claim_fox", ["obs_meet"])

        text = _invoke(db_path)
        result = _invoke(db_path, "--json")

        assert text.exit_code == 0, text.output
        assert "Total citing claims: 1" in text.stdout
        assert "obs_meet" in text.stdout and "citing claims: 1" in text.stdout
        assert "unknown provenance: 0" in text.stdout.splitlines()
        data = json.loads(result.stdout)
        assert data["total_citations"] == 1
        assert data["selected"][0]["citing_claims"] == 1
        assert data["unknown_provenance"] == 0

    def test_confirm_refuses_and_keeps_rows(self, store, db_path):
        _add_obs(store, "obs_meet", MEETING_META)
        _cite(store, "claim_fox", ["obs_meet"])
        store.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        before = db_path.read_bytes()

        result = _invoke(db_path, "--confirm")

        assert result.exit_code != 0
        assert "Total citing claims: 1" in result.stdout
        assert "Refusing to delete: 1 selected row(s) have citing claims" in result.stdout
        assert "obs_meet  citing claims: 1" in result.stdout
        assert "No changes made." in result.stdout
        ids = {r["id"] for r in store.execute("SELECT id FROM observations").fetchall()}
        assert ids == {"obs_meet"}
        assert db_path.read_bytes() == before
        assert list(db_path.parent.glob("*.bak.*")) == []

    def test_legacy_claims_reported_as_unknown_provenance(self, store, db_path):
        _add_obs(store, "obs_meet", MEETING_META)
        for i, source_ids in enumerate(LEGACY_SOURCE_IDS):
            _cite(store, f"claim_old_{i}", source_ids)
        n = len(LEGACY_SOURCE_IDS)

        text = _invoke(db_path)
        result = _invoke(db_path, "--json")

        assert text.exit_code == 0, text.output
        assert "Total citing claims: 0" in text.stdout
        assert f"unknown provenance: {n}" in text.stdout.splitlines()
        data = json.loads(result.stdout)
        assert data["total_citations"] == 0
        assert data["unknown_provenance"] == n

    def test_json_new_key_is_additive(self, store, db_path):
        _add_obs(store, "obs_meet", MEETING_META)
        _cite(store, "claim_old", ["extraction"])

        result = _invoke(db_path, "--json")

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert set(data) == {
            "selected_count",
            "earliest",
            "latest",
            "processed",
            "unprocessed",
            "selected",
            "total_citations",
            "unknown_provenance",
            "undetermined",
        }
        assert set(data["selected"][0]) == {
            "observation_id",
            "date",
            "item_classes",
            "citing_claims",
        }
        assert set(data["undetermined"]) == {
            "count",
            "earliest",
            "latest",
            "reasons",
            "zero_timestamp",
        }
        assert data["unknown_provenance"] == 1
