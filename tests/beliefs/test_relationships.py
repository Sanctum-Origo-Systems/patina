from __future__ import annotations

import time

from patina.beliefs.relationships import (
    _classify_activity,
    _score_behavioral_claims,
    _score_relationship_predicates,
    compute_interaction_stats,
    compute_trust_level,
    get_relationship_map,
)
from patina.decisions import record_decision
from patina.graph import insert_observation, upsert_entity
from patina.models import Entity, Observation


def _add_obs(conn, obs_id, sender_id, text="hello", ts=None):
    if ts is None:
        ts = time.time()
    obs = Observation(
        id=obs_id,
        source="slack",
        channel_id="C1",
        thread_id=None,
        timestamp=ts,
        sender_entity_id=sender_id,
        text=text,
    )
    insert_observation(conn, obs)


def test_stats_computed(db_conn):
    e = Entity(id="e1", type="person", name="Alice")
    upsert_entity(db_conn, e)
    now = time.time()
    _add_obs(db_conn, "o1", "e1", ts=now - 86400)
    _add_obs(db_conn, "o2", "e1", ts=now - 3600)
    _add_obs(db_conn, "o3", "e1", ts=now)

    stats = compute_interaction_stats(db_conn, "e1")
    assert stats["message_count"] == 3
    assert stats["days_since_last"] is not None
    assert stats["avg_messages_per_week"] > 0


def test_classify_active():
    assert _classify_activity(5.0, 2.0) == "active"


def test_classify_low_frequency():
    assert _classify_activity(0.5, 10.0) == "low-frequency"


def test_classify_dormant():
    assert _classify_activity(0.1, 90.0) == "dormant"


def test_classify_dormant_none():
    assert _classify_activity(0.0, None) == "dormant"


def test_trust_uses_act_rate_not_recency(db_conn):
    e = Entity(id="e1", type="person", name="Alice")
    upsert_entity(db_conn, e)

    now = time.time()
    _add_obs(db_conn, "o1", "e1", ts=now - 90 * 86400)
    record_decision(db_conn, "o1", "acted")

    trust = compute_trust_level(db_conn, "e1")
    assert trust > 0.5


def test_high_trust_dormant_valid(db_conn):
    e = Entity(id="e1", type="person", name="Alice")
    upsert_entity(db_conn, e)

    old_ts = time.time() - 90 * 86400
    _add_obs(db_conn, "o1", "e1", ts=old_ts)
    record_decision(db_conn, "o1", "acted")

    trust = compute_trust_level(db_conn, "e1")
    stats = compute_interaction_stats(db_conn, "e1")
    activity = _classify_activity(stats["avg_messages_per_week"], stats["days_since_last"])

    assert trust > 0.5
    assert activity == "dormant"


def test_relationship_map_top_n(db_conn):
    for i in range(5):
        eid = f"e{i}"
        upsert_entity(db_conn, Entity(id=eid, type="person", name=f"Person {i}"))
        _add_obs(db_conn, f"o{i}", eid)

    results = get_relationship_map(db_conn, top_n=3)
    assert len(results) <= 3


def test_empty_graph_empty_map(db_conn):
    results = get_relationship_map(db_conn)
    assert results == []


def _insert_claim(conn, subject_id, predicate, obj, confidence=0.8):
    import hashlib

    claim_id = hashlib.sha256(
        f"{subject_id}:{predicate}:{obj}".encode()
    ).hexdigest()[:16]
    now = "2026-06-29T00:00:00+00:00"
    conn.execute(
        """INSERT OR REPLACE INTO claims
           (id, subject_id, predicate, object, confidence,
            first_asserted, last_confirmed, decay_rate, source_ids)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0.02, '[]')""",
        (claim_id, subject_id, predicate, obj, confidence, now, now),
    )
    conn.commit()


def _insert_relationship(conn, subject_id, predicate, object_id, confidence=0.8):
    import hashlib

    rel_id = hashlib.sha256(
        f"{subject_id}:{predicate}:{object_id}".encode()
    ).hexdigest()[:16]
    now = "2026-06-29T00:00:00+00:00"
    conn.execute(
        """INSERT OR REPLACE INTO relationships
           (id, subject_id, predicate, object_id, confidence,
            first_seen, last_confirmed, source_ids)
           VALUES (?, ?, ?, ?, ?, ?, ?, '[]')""",
        (rel_id, subject_id, predicate, object_id, confidence, now, now),
    )
    conn.commit()


class TestScoreBehavioralClaims:
    def _claim(self, predicate, obj, confidence=0.8):
        return {"predicate": predicate, "object": obj, "confidence": confidence}

    def test_positive_keywords_increase_score(self):
        claims = [self._claim("behavioral:communication_style", "very responsive and helpful")]
        score = _score_behavioral_claims(claims)
        assert score > 0.5

    def test_negative_keywords_decrease_score(self):
        claims = [self._claim("behavioral:communication_style", "avoids and ignores messages")]
        score = _score_behavioral_claims(claims)
        assert score < 0.5

    def test_commitment_predicate_boosts_base(self):
        claims = [self._claim("behavioral:commitment", "follows through on tasks")]
        score = _score_behavioral_claims(claims)
        assert score > 0.5

    def test_neutral_claims_return_baseline(self):
        claims = [self._claim("behavioral:pattern", "sends messages in the morning")]
        score = _score_behavioral_claims(claims)
        assert score == 0.5

    def test_empty_claims_return_baseline(self):
        assert _score_behavioral_claims([]) == 0.5

    def test_mixed_signals_blend(self):
        claims = [
            self._claim("behavioral:style", "responsive and proactive", 0.9),
            self._claim("behavioral:style", "sometimes delays", 0.5),
        ]
        score = _score_behavioral_claims(claims)
        assert 0.3 < score < 0.8

    def test_score_bounded(self):
        claims = [
            self._claim(
                "behavioral:style",
                "responsive helpful reliable consistent proactive delivers on time",
            )
        ]
        score = _score_behavioral_claims(claims)
        assert score <= 1.0

    def test_negative_score_bounded(self):
        claims = [
            self._claim(
                "behavioral:style",
                "escalates pressures demands avoids delays ignores unreliable",
            )
        ]
        score = _score_behavioral_claims(claims)
        assert score >= 0.0


class TestScoreRelationshipPredicates:
    def _rel(self, predicate, confidence=0.8):
        return {"predicate": predicate, "confidence": confidence}

    def test_manages_scores_high(self):
        score = _score_relationship_predicates([self._rel("manages")])
        assert score == 0.8

    def test_collaborates_with(self):
        score = _score_relationship_predicates([self._rel("collaborates_with")])
        assert score == 0.7

    def test_unknown_predicate_gets_baseline(self):
        score = _score_relationship_predicates([self._rel("unknown_rel")])
        assert score == 0.5

    def test_empty_returns_baseline(self):
        assert _score_relationship_predicates([]) == 0.5

    def test_multiple_predicates_blend(self):
        rels = [self._rel("manages", 0.9), self._rel("works_with", 0.5)]
        score = _score_relationship_predicates(rels)
        assert 0.65 < score < 0.8


class TestComputeTrustLevelBlended:
    def test_no_signals_returns_baseline(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        trust = compute_trust_level(db_conn, "e1")
        assert trust == 0.5

    def test_behavioral_only(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        _add_obs(db_conn, "o1", "e1")
        _insert_claim(
            db_conn, "e1", "behavioral:style", "very responsive and helpful"
        )
        trust = compute_trust_level(db_conn, "e1")
        assert trust > 0.5

    def test_decision_only(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        _add_obs(db_conn, "o1", "e1")
        record_decision(db_conn, "o1", "acted")
        trust = compute_trust_level(db_conn, "e1")
        assert trust > 0.5

    def test_relationship_only(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        upsert_entity(db_conn, Entity(id="e2", type="person", name="Bob"))
        _add_obs(db_conn, "o1", "e1")
        _insert_relationship(db_conn, "e1", "manages", "e2")
        trust = compute_trust_level(db_conn, "e1")
        assert trust > 0.5

    def test_all_three_signals(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        upsert_entity(db_conn, Entity(id="e2", type="person", name="Bob"))
        _add_obs(db_conn, "o1", "e1")
        record_decision(db_conn, "o1", "acted")
        _insert_claim(
            db_conn, "e1", "behavioral:commitment", "always delivers on time"
        )
        _insert_relationship(db_conn, "e1", "collaborates_with", "e2")
        trust = compute_trust_level(db_conn, "e1")
        assert trust > 0.6

    def test_negative_behavioral_lowers_trust(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        _add_obs(db_conn, "o1", "e1")
        _insert_claim(
            db_conn, "e1", "behavioral:style", "avoids and ignores messages"
        )
        trust = compute_trust_level(db_conn, "e1")
        assert trust < 0.5


class TestRelationshipMapBehavioralNote:
    def test_includes_behavioral_note(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        _add_obs(db_conn, "o1", "e1")
        _insert_claim(
            db_conn, "e1", "behavioral:style", "very responsive", 0.9
        )
        results = get_relationship_map(db_conn)
        assert len(results) == 1
        assert results[0]["behavioral_note"] == "very responsive"

    def test_no_behavioral_note_is_none(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        _add_obs(db_conn, "o1", "e1")
        results = get_relationship_map(db_conn)
        assert len(results) == 1
        assert results[0]["behavioral_note"] is None

    def test_behavioral_note_truncated(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        _add_obs(db_conn, "o1", "e1")
        _insert_claim(db_conn, "e1", "behavioral:style", "x" * 200, 0.9)
        results = get_relationship_map(db_conn)
        assert len(results[0]["behavioral_note"]) == 80
