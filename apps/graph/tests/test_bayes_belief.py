"""Tests for graph.services.bayes_belief.

The Bayes belief function turns three count-style inputs into a posterior
probability in (0, 1):
  * n_supporting_papers — distinct PMIDs that support this edge
  * n_models_agreeing   — distinct extractor models that found this edge
  * mean_recency        — exp-decayed weight over evidence ages (1.0 = today,
                          0.5 ≈ 5 years old, ~0.0 ≈ 20+ years old)

Numerical sanity table (from plan Self-Review):
  0 papers / 0 models → 0.300 (prior)
  1 paper  / 1 model  → ~0.55 (candidate)
  1 paper  / 7 models → ≥0.80 (accepted threshold)
  5 papers / 7 models → >0.99 (strongly accepted)
"""

from __future__ import annotations

import pytest

from graph.services import (
    BAYES_PRIOR,
    BELIEF_THRESHOLD_ACCEPTED,
    BELIEF_THRESHOLD_REJECTED,
    bayes_belief,
)


def test_belief_with_no_evidence_equals_prior():
    score = bayes_belief(n_supporting_papers=0, n_models_agreeing=0, mean_recency=1.0)
    assert score == pytest.approx(BAYES_PRIOR, abs=1e-9)


def test_belief_strictly_in_open_unit_interval():
    score = bayes_belief(n_supporting_papers=5, n_models_agreeing=7, mean_recency=1.0)
    assert 0.0 < score < 1.0


def test_belief_monotonic_in_supporting_papers():
    s1 = bayes_belief(n_supporting_papers=1, n_models_agreeing=3, mean_recency=1.0)
    s5 = bayes_belief(n_supporting_papers=5, n_models_agreeing=3, mean_recency=1.0)
    assert s5 > s1


def test_belief_monotonic_in_models_agreeing():
    s1 = bayes_belief(n_supporting_papers=3, n_models_agreeing=1, mean_recency=1.0)
    s7 = bayes_belief(n_supporting_papers=3, n_models_agreeing=7, mean_recency=1.0)
    assert s7 > s1


def test_belief_monotonic_in_recency():
    s_old = bayes_belief(n_supporting_papers=3, n_models_agreeing=3, mean_recency=0.1)
    s_new = bayes_belief(n_supporting_papers=3, n_models_agreeing=3, mean_recency=1.0)
    assert s_new > s_old


def test_belief_saturates_near_one_with_many_supporters():
    score = bayes_belief(n_supporting_papers=50, n_models_agreeing=7, mean_recency=1.0)
    assert score > 0.99
    assert score < 1.0  # never exactly 1.0


def test_belief_handles_zero_recency_gracefully():
    """With zero recency, paper contributions are nullified but models still boost.
    The score should be strictly between prior and the full-recency score."""
    score_zero = bayes_belief(n_supporting_papers=3, n_models_agreeing=3, mean_recency=0.0)
    score_full = bayes_belief(n_supporting_papers=3, n_models_agreeing=3, mean_recency=1.0)
    score_models_only = bayes_belief(n_supporting_papers=0, n_models_agreeing=3, mean_recency=0.0)
    # Zero recency papers contribute nothing → same as if no papers
    assert score_zero == pytest.approx(score_models_only, abs=1e-9)
    # Must be strictly less than full-recency score (papers add value when recent)
    assert score_zero < score_full
    # Must be greater than prior (models still contribute)
    assert score_zero > BAYES_PRIOR


def test_thresholds_are_well_defined():
    assert 0.0 < BELIEF_THRESHOLD_REJECTED < BAYES_PRIOR < BELIEF_THRESHOLD_ACCEPTED < 1.0


def test_belief_with_one_paper_seven_models_recent_exceeds_accepted_threshold():
    """The 'consensus' case — 7 models agree on a single recent paper."""
    score = bayes_belief(n_supporting_papers=1, n_models_agreeing=7, mean_recency=1.0)
    assert score >= BELIEF_THRESHOLD_ACCEPTED


def test_belief_with_one_paper_one_model_stays_candidate():
    score = bayes_belief(n_supporting_papers=1, n_models_agreeing=1, mean_recency=1.0)
    assert BELIEF_THRESHOLD_REJECTED < score < BELIEF_THRESHOLD_ACCEPTED


def test_belief_rejects_negative_counts():
    with pytest.raises(ValueError):
        bayes_belief(n_supporting_papers=-1, n_models_agreeing=1, mean_recency=1.0)
    with pytest.raises(ValueError):
        bayes_belief(n_supporting_papers=1, n_models_agreeing=-1, mean_recency=1.0)


def test_belief_clamps_recency_to_unit_interval():
    s = bayes_belief(n_supporting_papers=3, n_models_agreeing=3, mean_recency=1.5)
    s_clamped = bayes_belief(n_supporting_papers=3, n_models_agreeing=3, mean_recency=1.0)
    assert s == pytest.approx(s_clamped)


def test_numerical_sanity_zero_zero():
    """0 papers / 0 models → exactly prior (0.300)."""
    score = bayes_belief(n_supporting_papers=0, n_models_agreeing=0, mean_recency=1.0)
    assert score == pytest.approx(0.300, abs=1e-3)


def test_numerical_sanity_one_paper_one_model():
    """1 paper / 1 model → ~0.55 (candidate zone)."""
    score = bayes_belief(n_supporting_papers=1, n_models_agreeing=1, mean_recency=1.0)
    assert 0.45 < score < 0.75


def test_numerical_sanity_five_papers_seven_models():
    """5 papers / 7 models → >0.99."""
    score = bayes_belief(n_supporting_papers=5, n_models_agreeing=7, mean_recency=1.0)
    assert score > 0.99
