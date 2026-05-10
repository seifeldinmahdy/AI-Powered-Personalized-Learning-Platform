"""Unit tests for per-slide mastery derivation and topic performance update.

Tests all four functions in services/topic_mastery.py:
- derive_topic_mastery
- match_topic_to_performance
- smooth_mastery_sequence
- update_topic_performance_scores

The match_topic_to_performance tests mock the sentence-transformers
embedder so they run without loading a real model.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Ensure the services package is importable
import sys
from pathlib import Path

_ai_service_dir = str(Path(__file__).resolve().parent.parent)
if _ai_service_dir not in sys.path:
    sys.path.insert(0, _ai_service_dir)

from services.topic_mastery import (
    derive_topic_mastery,
    match_topic_to_performance,
    smooth_mastery_sequence,
    update_topic_performance_scores,
)


# =====================================================================
# derive_topic_mastery
# =====================================================================


class TestDeriveTopicMastery:
    """Tests for score → mastery label conversion."""

    def test_expert_above_threshold(self):
        assert derive_topic_mastery(0.9, "Novice") == "Expert"

    def test_expert_at_threshold(self):
        """Exactly at the expert threshold → Expert."""
        assert derive_topic_mastery(0.75, "Novice") == "Expert"

    def test_intermediate_above_threshold(self):
        assert derive_topic_mastery(0.6, "Novice") == "Intermediate"

    def test_intermediate_at_threshold(self):
        """Exactly at the intermediate threshold → Intermediate."""
        assert derive_topic_mastery(0.45, "Novice") == "Intermediate"

    def test_novice_below_threshold(self):
        assert derive_topic_mastery(0.2, "Expert") == "Novice"

    def test_novice_zero(self):
        assert derive_topic_mastery(0.0, "Expert") == "Novice"

    def test_none_fallback_novice(self):
        """None score → global mastery fallback."""
        assert derive_topic_mastery(None, "Novice") == "Novice"

    def test_none_fallback_expert(self):
        """None score → global mastery fallback."""
        assert derive_topic_mastery(None, "Expert") == "Expert"

    def test_none_fallback_intermediate(self):
        assert derive_topic_mastery(None, "Intermediate") == "Intermediate"

    def test_custom_thresholds(self):
        """Custom thresholds override defaults."""
        # With custom thresholds: expert >= 0.9, intermediate >= 0.6
        assert derive_topic_mastery(0.8, "Novice", expert_threshold=0.9, intermediate_threshold=0.6) == "Intermediate"
        assert derive_topic_mastery(0.5, "Novice", expert_threshold=0.9, intermediate_threshold=0.6) == "Novice"
        assert derive_topic_mastery(0.95, "Novice", expert_threshold=0.9, intermediate_threshold=0.6) == "Expert"

    def test_boundary_between_intermediate_and_novice(self):
        """Score just below intermediate threshold → Novice."""
        assert derive_topic_mastery(0.449, "Expert") == "Novice"

    def test_boundary_between_expert_and_intermediate(self):
        """Score just below expert threshold → Intermediate."""
        assert derive_topic_mastery(0.749, "Novice") == "Intermediate"

    def test_perfect_score(self):
        assert derive_topic_mastery(1.0, "Novice") == "Expert"


# =====================================================================
# match_topic_to_performance
# =====================================================================


class TestMatchTopicToPerformance:
    """Tests for fuzzy topic matching — all mock the embedder."""

    def test_exact_match(self):
        """Exact case-insensitive match bypasses the embedder entirely."""
        perf = {"recursion": 0.8, "loops": 0.3}
        score, key = match_topic_to_performance("Recursion", perf)
        assert score == 0.8
        assert key == "recursion"

    def test_empty_topic_performance(self):
        score, key = match_topic_to_performance("recursion", {})
        assert score is None
        assert key is None

    def test_none_topic_performance(self):
        score, key = match_topic_to_performance("recursion", None)
        assert score is None
        assert key is None

    def test_empty_chunk_topic(self):
        score, key = match_topic_to_performance("", {"recursion": 0.5})
        assert score is None
        assert key is None

    def test_blank_chunk_topic(self):
        score, key = match_topic_to_performance("   ", {"recursion": 0.5})
        assert score is None
        assert key is None

    def test_semantic_match_above_threshold(self):
        """Mock embedder returns high similarity → match found."""
        mock_embedder = MagicMock()
        # 2 texts: chunk_topic + 1 perf key = 2 embeddings
        # Make them nearly identical (cosine sim ≈ 0.95)
        mock_embedder.encode.return_value = np.array([
            [1.0, 0.0, 0.0],  # chunk topic
            [0.98, 0.2, 0.0],  # "recursive functions" — high sim
        ])

        perf = {"recursive functions": 0.7}
        score, key = match_topic_to_performance(
            "recursion", perf, similarity_threshold=0.75, _embedder=mock_embedder,
        )
        assert score == 0.7
        assert key == "recursive functions"

    def test_semantic_match_below_threshold(self):
        """Mock embedder returns low similarity → no match."""
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = np.array([
            [1.0, 0.0, 0.0],  # chunk topic
            [0.0, 1.0, 0.0],  # "file io" — orthogonal → sim ≈ 0
        ])

        perf = {"file io": 0.9}
        score, key = match_topic_to_performance(
            "recursion", perf, similarity_threshold=0.75, _embedder=mock_embedder,
        )
        assert score is None
        assert key is None

    def test_multiple_keys_picks_best(self):
        """When multiple keys exist, pick the one with highest similarity."""
        mock_embedder = MagicMock()
        mock_embedder.encode.return_value = np.array([
            [1.0, 0.0, 0.0],   # chunk topic
            [0.3, 0.9, 0.0],   # "lists" — low sim
            [0.95, 0.1, 0.0],  # "recursive functions" — high sim
            [0.0, 0.0, 1.0],   # "classes" — orthogonal
        ])

        perf = {"lists": 0.2, "recursive functions": 0.85, "classes": 0.5}
        score, key = match_topic_to_performance(
            "recursion", perf, similarity_threshold=0.75, _embedder=mock_embedder,
        )
        assert score == 0.85
        assert key == "recursive functions"

    def test_embedder_exception_returns_none(self):
        """If the embedder throws, return (None, None) gracefully."""
        mock_embedder = MagicMock()
        mock_embedder.encode.side_effect = RuntimeError("GPU error")

        perf = {"recursion": 0.5}
        score, key = match_topic_to_performance(
            "something", perf, _embedder=mock_embedder,
        )
        assert score is None
        assert key is None


# =====================================================================
# smooth_mastery_sequence
# =====================================================================


class TestSmoothMasterySequence:
    """Tests for jarring-transition smoothing."""

    def test_no_transitions_needed(self):
        """All same mastery → no change."""
        result = smooth_mastery_sequence(["Expert", "Expert", "Expert"])
        assert result == ["Expert", "Expert", "Expert"]

    def test_adjacent_tiers_unchanged(self):
        """Adjacent tiers (Expert → Intermediate) differ by 1 → no smoothing."""
        result = smooth_mastery_sequence(["Expert", "Intermediate", "Expert"])
        assert result == ["Expert", "Intermediate", "Expert"]

    def test_single_jarring_transition(self):
        """Expert → Novice (diff=2) → Novice nudged up to Intermediate."""
        result = smooth_mastery_sequence(["Expert", "Novice"])
        assert result == ["Expert", "Intermediate"]

    def test_example_from_spec(self):
        """The exact example from the requirements."""
        input_seq = ["Expert", "Novice", "Novice", "Expert", "Intermediate"]
        expected = ["Expert", "Intermediate", "Novice", "Intermediate", "Intermediate"]
        result = smooth_mastery_sequence(input_seq)
        assert result == expected

    def test_multiple_jarring_transitions(self):
        """Multiple jarring transitions smoothed left to right."""
        input_seq = ["Novice", "Expert", "Novice"]
        # Pass 1: idx 1 (Expert) vs idx 0 (Novice) → diff=2 → Expert nudged to Intermediate
        # Pass 2: idx 2 (Novice) vs idx 1 (now Intermediate) → diff=1 → no change
        expected = ["Novice", "Intermediate", "Novice"]
        result = smooth_mastery_sequence(input_seq)
        assert result == expected

    def test_single_element_list(self):
        result = smooth_mastery_sequence(["Expert"])
        assert result == ["Expert"]

    def test_empty_list(self):
        result = smooth_mastery_sequence([])
        assert result == []

    def test_all_novice(self):
        result = smooth_mastery_sequence(["Novice", "Novice", "Novice"])
        assert result == ["Novice", "Novice", "Novice"]

    def test_gradual_ramp_up_unchanged(self):
        """Novice → Intermediate → Expert → smooth, no changes needed."""
        result = smooth_mastery_sequence(["Novice", "Intermediate", "Expert"])
        assert result == ["Novice", "Intermediate", "Expert"]

    def test_gradual_ramp_down_unchanged(self):
        """Expert → Intermediate → Novice → smooth, no changes needed."""
        result = smooth_mastery_sequence(["Expert", "Intermediate", "Novice"])
        assert result == ["Expert", "Intermediate", "Novice"]


# =====================================================================
# update_topic_performance_scores
# =====================================================================


class TestUpdateTopicPerformanceScores:
    """Tests for weighted moving average topic updates."""

    def test_existing_topic_weighted_average(self):
        """Topic already in performance → weighted average applied."""
        current = {"recursion": 0.4}
        session = {"recursion": 1.0}
        result = update_topic_performance_scores(current, session, weight=0.3)
        # (1 - 0.3) * 0.4 + 0.3 * 1.0 = 0.28 + 0.3 = 0.58
        assert result["topic_performance"]["recursion"] == 0.58

    def test_new_topic_added_directly(self):
        """Topic not in performance → added with session score."""
        current = {"loops": 0.5}
        session = {"decorators": 0.9}
        result = update_topic_performance_scores(current, session, weight=0.3)
        assert result["topic_performance"]["decorators"] == 0.9
        # Existing topic unchanged
        assert result["topic_performance"]["loops"] == 0.5

    def test_multiple_topics_updated(self):
        """Multiple topics updated in one call."""
        current = {"loops": 0.3, "functions": 0.8, "recursion": 0.0}
        session = {"loops": 0.9, "functions": 0.4, "generators": 0.7}
        result = update_topic_performance_scores(current, session, weight=0.3)
        # loops: (0.7 * 0.3) + (0.3 * 0.9) = 0.21 + 0.27 = 0.48
        assert result["topic_performance"]["loops"] == 0.48
        # functions: (0.7 * 0.8) + (0.3 * 0.4) = 0.56 + 0.12 = 0.68
        assert result["topic_performance"]["functions"] == 0.68
        # generators: new topic
        assert result["topic_performance"]["generators"] == 0.7
        # recursion: unchanged
        assert result["topic_performance"]["recursion"] == 0.0

    def test_strength_classification_boundary(self):
        """Score exactly 0.7 → NOT a strength (threshold is > 0.7)."""
        current = {}
        session = {"topic_at_boundary": 0.7}
        result = update_topic_performance_scores(current, session)
        assert "topic_at_boundary" not in result["strengths"]

    def test_strength_classification_above(self):
        """Score > 0.7 → IS a strength."""
        current = {}
        session = {"strong_topic": 0.71}
        result = update_topic_performance_scores(current, session)
        assert "strong_topic" in result["strengths"]

    def test_weakness_classification_boundary(self):
        """Score exactly 0.5 → NOT a weakness (threshold is < 0.5)."""
        current = {}
        session = {"topic_at_boundary": 0.5}
        result = update_topic_performance_scores(current, session)
        assert "topic_at_boundary" not in result["weaknesses"]

    def test_weakness_classification_below(self):
        """Score < 0.5 → IS a weakness."""
        current = {}
        session = {"weak_topic": 0.49}
        result = update_topic_performance_scores(current, session)
        assert "weak_topic" in result["weaknesses"]

    def test_weight_zero_unchanged(self):
        """weight=0.0 → current score unchanged."""
        current = {"recursion": 0.4}
        session = {"recursion": 1.0}
        result = update_topic_performance_scores(current, session, weight=0.0)
        assert result["topic_performance"]["recursion"] == 0.4

    def test_weight_one_fully_replaced(self):
        """weight=1.0 → current score fully replaced by session score."""
        current = {"recursion": 0.4}
        session = {"recursion": 1.0}
        result = update_topic_performance_scores(current, session, weight=1.0)
        assert result["topic_performance"]["recursion"] == 1.0

    def test_immutability(self):
        """Input dict is not mutated."""
        current = {"recursion": 0.4, "loops": 0.6}
        original_current = dict(current)
        session = {"recursion": 1.0, "new_topic": 0.8}
        update_topic_performance_scores(current, session, weight=0.3)
        assert current == original_current

    def test_rounding_precision(self):
        """Values are rounded to 4 decimal places."""
        current = {"topic": 0.3333}
        session = {"topic": 0.6666}
        result = update_topic_performance_scores(current, session, weight=0.3)
        score = result["topic_performance"]["topic"]
        # (0.7 * 0.3333) + (0.3 * 0.6666) = 0.23331 + 0.19998 = 0.43329
        assert score == round(score, 4)
        assert len(str(score).split(".")[-1]) <= 4

    def test_empty_session_scores(self):
        """Empty session_scores → no changes."""
        current = {"loops": 0.6}
        result = update_topic_performance_scores(current, {}, weight=0.3)
        assert result["topic_performance"] == {"loops": 0.6}

    def test_empty_current_performance(self):
        """Empty current + session scores → all added as new."""
        session = {"loops": 0.9, "functions": 0.3}
        result = update_topic_performance_scores({}, session, weight=0.3)
        assert result["topic_performance"]["loops"] == 0.9
        assert result["topic_performance"]["functions"] == 0.3
        assert "loops" in result["strengths"]
        assert "functions" in result["weaknesses"]

    def test_strengths_weaknesses_sorted(self):
        """Strengths and weaknesses lists are sorted."""
        session = {"z_topic": 0.9, "a_topic": 0.1, "m_topic": 0.8}
        result = update_topic_performance_scores({}, session)
        assert result["strengths"] == sorted(result["strengths"])
        assert result["weaknesses"] == sorted(result["weaknesses"])

    def test_idempotency_changes_on_repeat(self):
        """Calling twice with same session scores produces different results."""
        current = {"recursion": 0.4}
        session = {"recursion": 1.0}
        r1 = update_topic_performance_scores(current, session, weight=0.3)
        r2 = update_topic_performance_scores(
            r1["topic_performance"], session, weight=0.3,
        )
        # First: 0.58, Second: (0.7*0.58) + (0.3*1.0) = 0.406 + 0.3 = 0.706
        assert r1["topic_performance"]["recursion"] != r2["topic_performance"]["recursion"]
        assert r2["topic_performance"]["recursion"] == 0.706
