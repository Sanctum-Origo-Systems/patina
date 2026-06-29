from __future__ import annotations

import time

from patina.beliefs.relationships import (
    _classify_activity,
    _score_behavioral_claims,
    _score_relationship_predicates,
    compute_interaction_stats,
    compute_trust_level,
    get_hidden_allies,
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


class TestClassifyActivity:
    def test_core(self):
        assert _classify_activity(20.0, 1.0) == "core"

    def test_core_boundary(self):
        assert _classify_activity(15.0, 2.0) == "core"

    def test_active(self):
        assert _classify_activity(8.0, 2.0) == "active"

    def test_active_boundary(self):
        assert _classify_activity(5.0, 3.0) == "active"

    def test_moderate(self):
        assert _classify_activity(2.0, 7.0) == "moderate"

    def test_moderate_boundary(self):
        assert _classify_activity(1.0, 14.0) == "moderate"

    def test_occasional(self):
        assert _classify_activity(0.5, 20.0) == "occasional"

    def test_occasional_boundary(self):
        assert _classify_activity(0.3, 30.0) == "occasional"

    def test_low_frequency(self):
        assert _classify_activity(0.2, 45.0) == "low-frequency"

    def test_dormant(self):
        assert _classify_activity(0.1, 90.0) == "dormant"

    def test_dormant_none(self):
        assert _classify_activity(0.0, None) == "dormant"

    def test_dormant_boundary(self):
        assert _classify_activity(5.0, 61.0) == "dormant"


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

    claim_id = hashlib.sha256(f"{subject_id}:{predicate}:{obj}".encode()).hexdigest()[:16]
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

    rel_id = hashlib.sha256(f"{subject_id}:{predicate}:{object_id}".encode()).hexdigest()[:16]
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
        _insert_claim(db_conn, "e1", "behavioral:style", "very responsive and helpful")
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
        _insert_claim(db_conn, "e1", "behavioral:commitment", "always delivers on time")
        _insert_relationship(db_conn, "e1", "collaborates_with", "e2")
        trust = compute_trust_level(db_conn, "e1")
        assert trust > 0.6

    def test_negative_behavioral_lowers_trust(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        _add_obs(db_conn, "o1", "e1")
        _insert_claim(db_conn, "e1", "behavioral:style", "avoids and ignores messages")
        trust = compute_trust_level(db_conn, "e1")
        assert trust < 0.5


class TestRelationshipMapBehavioralNote:
    def test_includes_behavioral_note(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        _add_obs(db_conn, "o1", "e1")
        _insert_claim(db_conn, "e1", "behavioral:style", "very responsive", 0.9)
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


class TestRelationshipMapRanking:
    def test_high_messages_beats_high_trust(self, db_conn):
        """50 messages + baseline trust should rank above 2 messages + high trust."""
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        upsert_entity(db_conn, Entity(id="e2", type="person", name="Bob"))
        now = time.time()
        for i in range(50):
            _add_obs(db_conn, f"a{i}", "e1", ts=now - i * 3600)
        _add_obs(db_conn, "b0", "e2", ts=now)
        _add_obs(db_conn, "b1", "e2", ts=now - 3600)
        _insert_claim(db_conn, "e2", "behavioral:style", "very responsive and helpful")
        results = get_relationship_map(db_conn)
        assert results[0]["name"] == "Alice"
        assert results[1]["name"] == "Bob"

    def test_equal_messages_trust_breaks_tie(self, db_conn):
        """Same message count — higher trust should win."""
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        upsert_entity(db_conn, Entity(id="e2", type="person", name="Bob"))
        now = time.time()
        _add_obs(db_conn, "a0", "e1", ts=now)
        _add_obs(db_conn, "b0", "e2", ts=now)
        _insert_claim(db_conn, "e2", "behavioral:commitment", "delivers on time")
        results = get_relationship_map(db_conn)
        assert results[0]["name"] == "Bob"

    def test_message_count_caps_at_100(self, db_conn):
        """200 messages should rank the same as 100 messages
        (both cap at 1.0 for the message component)."""
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        upsert_entity(db_conn, Entity(id="e2", type="person", name="Bob"))
        now = time.time()
        for i in range(200):
            _add_obs(db_conn, f"a{i}", "e1", ts=now - i * 600)
        for i in range(100):
            _add_obs(db_conn, f"b{i}", "e2", ts=now - i * 600)
        results = get_relationship_map(db_conn)
        r1 = next(r for r in results if r["name"] == "Alice")
        r2 = next(r for r in results if r["name"] == "Bob")
        score1 = r1["trust_level"] * 0.4 + min(r1["message_count"] / 100, 1.0) * 0.6
        score2 = r2["trust_level"] * 0.4 + min(r2["message_count"] / 100, 1.0) * 0.6
        assert abs(score1 - score2) < 0.01

    def test_ranking_stable_across_additions(self, db_conn):
        """Adding a third person shouldn't change relative order of first two."""
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        upsert_entity(db_conn, Entity(id="e2", type="person", name="Bob"))
        now = time.time()
        for i in range(30):
            _add_obs(db_conn, f"a{i}", "e1", ts=now - i * 3600)
        for i in range(5):
            _add_obs(db_conn, f"b{i}", "e2", ts=now - i * 3600)
        results_before = get_relationship_map(db_conn)
        order_before = [r["name"] for r in results_before]

        upsert_entity(db_conn, Entity(id="e3", type="person", name="Carol"))
        for i in range(15):
            _add_obs(db_conn, f"c{i}", "e3", ts=now - i * 3600)
        results_after = get_relationship_map(db_conn)
        order_after = [r["name"] for r in results_after]

        idx_a = order_after.index("Alice")
        idx_b = order_after.index("Bob")
        assert idx_a < idx_b
        assert order_before[0] == "Alice"

    def test_single_message_low_rank(self, db_conn):
        """1 message should produce a low rank score."""
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        _add_obs(db_conn, "a0", "e1")
        results = get_relationship_map(db_conn)
        r = results[0]
        rank = r["trust_level"] * 0.4 + min(r["message_count"] / 100, 1.0) * 0.6
        assert rank < 0.3

    def test_activity_tier_breaks_tie(self, db_conn):
        """Same trust+msg score, higher activity tier wins."""
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        upsert_entity(db_conn, Entity(id="e2", type="person", name="Bob"))
        now = time.time()
        for i in range(10):
            _add_obs(db_conn, f"a{i}", "e1", ts=now - i * 3600)
            _add_obs(db_conn, f"b{i}", "e2", ts=now - i * 86400 * 3)
        results = get_relationship_map(db_conn)
        names = [r["name"] for r in results]
        assert names.index("Alice") < names.index("Bob")


class TestWidenedTrustSpread:
    def _claim(self, predicate, obj, confidence=0.8):
        return {"predicate": predicate, "object": obj, "confidence": confidence}

    def test_accommodating_ally_scores_high(self):
        claims = [
            self._claim("behavioral:style", "accommodates and adapts schedule"),
            self._claim("behavioral:commitment", "volunteers for tasks"),
        ]
        score = _score_behavioral_claims(claims)
        assert score >= 0.7

    def test_demanding_authority_scores_low(self):
        claims = [
            self._claim("behavioral:style", "demands accountability on deadline"),
        ]
        score = _score_behavioral_claims(claims)
        assert score < 0.4

    def test_spread_between_ally_and_authority(self):
        ally = [
            self._claim("behavioral:style", "accommodates and volunteers"),
        ]
        authority = [
            self._claim("behavioral:style", "demands accountability"),
        ]
        ally_score = _score_behavioral_claims(ally)
        authority_score = _score_behavioral_claims(authority)
        assert ally_score - authority_score >= 0.2

    def test_mixed_signals_net_positive(self):
        claims = [
            self._claim("behavioral:style", "responsive but sometimes demands"),
        ]
        score = _score_behavioral_claims(claims)
        assert 0.3 < score < 0.7

    def test_mixed_signals_net_negative(self):
        claims = [
            self._claim(
                "behavioral:style",
                "demands accountability and pressures on deadline",
            ),
        ]
        score = _score_behavioral_claims(claims)
        assert score < 0.5

    def test_commitment_base_raised(self):
        claims = [self._claim("behavioral:commitment", "neutral note")]
        score = _score_behavioral_claims(claims)
        assert score == 0.8

    def test_new_positive_keywords(self):
        for kw in ["accommodates", "shields", "volunteers", "champions"]:
            claims = [self._claim("behavioral:style", f"person {kw} others")]
            score = _score_behavioral_claims(claims)
            assert score > 0.5, f"keyword '{kw}' should boost score"

    def test_new_negative_keywords(self):
        for kw in ["controls", "accountability", "constraint"]:
            claims = [self._claim("behavioral:style", f"person {kw} others")]
            score = _score_behavioral_claims(claims)
            assert score < 0.5, f"keyword '{kw}' should lower score"


class TestHiddenAllies:
    def test_returns_empty_when_no_entities(self, db_conn):
        assert get_hidden_allies(db_conn) == []

    def test_excludes_dormant(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        old = time.time() - 90 * 86400
        for i in range(5):
            _add_obs(db_conn, f"o{i}", "e1", ts=old - i * 3600)
        _insert_claim(db_conn, "e1", "behavioral:style", "helpful")
        results = get_hidden_allies(db_conn)
        assert len(results) == 0

    def test_excludes_low_message_count(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        now = time.time()
        _add_obs(db_conn, "o0", "e1", ts=now)
        _add_obs(db_conn, "o1", "e1", ts=now - 3600)
        results = get_hidden_allies(db_conn)
        assert len(results) == 0

    def test_high_depth_low_volume_ranks_first(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Quiet Ally"))
        upsert_entity(db_conn, Entity(id="e2", type="person", name="Loud Talker"))
        now = time.time()
        for i in range(5):
            _add_obs(db_conn, f"q{i}", "e1", ts=now - i * 3600)
        for i in range(50):
            _add_obs(db_conn, f"l{i}", "e2", ts=now - i * 3600)
        for i in range(10):
            _insert_claim(db_conn, "e1", f"role:{i}", f"claim {i}", 0.8)
        for i in range(10):
            _insert_claim(db_conn, "e2", f"role:{i}", f"claim {i}", 0.8)
        _insert_claim(db_conn, "e1", "behavioral:style", "helpful", 0.9)
        results = get_hidden_allies(db_conn)
        assert results[0]["name"] == "Quiet Ally"

    def test_includes_depth_ratio(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        now = time.time()
        for i in range(5):
            _add_obs(db_conn, f"o{i}", "e1", ts=now - i * 3600)
        for i in range(15):
            _insert_claim(db_conn, "e1", f"fact:{i}", f"val {i}")
        results = get_hidden_allies(db_conn)
        assert len(results) == 1
        assert results[0]["depth_ratio"] == 3.0

    def test_includes_behavioral_note(self, db_conn):
        upsert_entity(db_conn, Entity(id="e1", type="person", name="Alice"))
        now = time.time()
        for i in range(5):
            _add_obs(db_conn, f"o{i}", "e1", ts=now - i * 3600)
        _insert_claim(db_conn, "e1", "behavioral:style", "very supportive", 0.9)
        results = get_hidden_allies(db_conn)
        assert results[0]["behavioral_note"] == "very supportive"

    def test_top_n_limits_results(self, db_conn):
        now = time.time()
        for j in range(5):
            eid = f"e{j}"
            upsert_entity(db_conn, Entity(id=eid, type="person", name=f"Person {j}"))
            for i in range(5):
                _add_obs(db_conn, f"o{j}_{i}", eid, ts=now - i * 3600)
            _insert_claim(db_conn, eid, "role:x", "val")
        results = get_hidden_allies(db_conn, top_n=3)
        assert len(results) <= 3
