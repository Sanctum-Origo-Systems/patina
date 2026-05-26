"""Eval: decay model mathematical correctness."""

from __future__ import annotations

from patina.beliefs.decay import compute_effective_confidence


def test_zero_days_no_decay():
    assert compute_effective_confidence(1.0, 0.02, 0.0) == 1.0


def test_30_days_2pct():
    eff = compute_effective_confidence(1.0, 0.02, 30)
    assert abs(eff - 0.545) < 0.01


def test_60_days_2pct():
    eff = compute_effective_confidence(1.0, 0.02, 60)
    assert abs(eff - 0.297) < 0.01


def test_never_goes_negative():
    eff = compute_effective_confidence(1.0, 0.02, 1000)
    assert eff >= 0.0


def test_zero_decay_rate_no_change():
    eff = compute_effective_confidence(0.8, 0.0, 365)
    assert eff == 0.8


def test_low_decay_rate_slow():
    eff = compute_effective_confidence(1.0, 0.005, 30)
    assert eff > 0.85


def test_formula_matches_spec():
    confidence = 0.9
    decay_rate = 0.02
    days = 15
    expected = confidence * (1 - decay_rate) ** days
    actual = compute_effective_confidence(confidence, decay_rate, days)
    assert abs(actual - expected) < 1e-10
