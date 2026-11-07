from __future__ import annotations

from datetime import datetime

import pytest

import patina.cleanup_meeting_obs as cleanup
from patina.adapters.outlook_mcp import _email_from_raw
from patina.cleanup_meeting_obs import (
    NOT_MEETING,
    SELECTED,
    UNDETERMINED,
    RemovalRefused,
    classify,
    remove_meeting_observations,
    select_meeting_observations,
)
from patina.graph import insert_claim, insert_observation
from patina.models import Claim, Observation
from patina.store import connect, run_pending_migrations

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


def _add_obs(conn, obs_id, metadata, *, ts=RECEIVED_TS, source="outlook_mcp_email", processed=0):
    insert_observation(
        conn,
        Observation(
            id=obs_id,
            source=source,
            channel_id=f"email:{obs_id}",
            thread_id=None,
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
        _add_obs(store, "obs_no_id", {"channel_name": None}, ts=1000.0)
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

    def test_no_adapter_means_undetermined(self, store, db_path):
        _add_obs(store, "obs_x", {"conversationId": "C1"})

        selection = select_meeting_observations(db_path)

        assert selection.selected == []
        assert selection.undetermined.count == 1


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
