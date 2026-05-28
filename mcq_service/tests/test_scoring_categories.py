"""Unit tests for mcq.scoring_categories.

No external dependencies — embedder is mocked where needed.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from mcq.scoring_categories import (
    get_effective_score,
    get_score_category,
    score_category_description,
)


# ── Shared fixture: settings object with default thresholds ─────────


def _make_settings(
    very_weak: float = 0.3,
    weak: float = 0.5,
    moderate: float = 0.75,
) -> SimpleNamespace:
    return SimpleNamespace(
        SCORE_VERY_WEAK_THRESHOLD=very_weak,
        SCORE_WEAK_THRESHOLD=weak,
        SCORE_MODERATE_THRESHOLD=moderate,
    )


# ═══════════════════════════════════════════════════════════════════════
# get_score_category
# ═══════════════════════════════════════════════════════════════════════


class TestGetScoreCategory:
    """Tests for get_score_category threshold boundaries."""

    def test_score_zero_returns_very_weak(self):
        assert get_score_category(0.0, _make_settings()) == "very_weak"

    def test_score_below_very_weak_threshold(self):
        assert get_score_category(0.15, _make_settings()) == "very_weak"

    def test_score_exactly_at_very_weak_threshold_returns_weak(self):
        # Score == 0.3 is NOT below 0.3, so it crosses into "weak"
        assert get_score_category(0.3, _make_settings()) == "weak"

    def test_score_between_very_weak_and_weak(self):
        assert get_score_category(0.4, _make_settings()) == "weak"

    def test_score_exactly_at_weak_threshold_returns_moderate(self):
        # Score == 0.5 is NOT below 0.5, so it crosses into "moderate"
        assert get_score_category(0.5, _make_settings()) == "moderate"

    def test_score_between_weak_and_moderate(self):
        assert get_score_category(0.6, _make_settings()) == "moderate"

    def test_score_exactly_at_moderate_threshold_returns_strong(self):
        # Score == 0.75 is NOT below 0.75, so it crosses into "strong"
        assert get_score_category(0.75, _make_settings()) == "strong"

    def test_score_above_moderate_threshold(self):
        assert get_score_category(0.9, _make_settings()) == "strong"

    def test_score_one_returns_strong(self):
        assert get_score_category(1.0, _make_settings()) == "strong"

    def test_custom_thresholds(self):
        custom = _make_settings(very_weak=0.2, weak=0.4, moderate=0.6)
        assert get_score_category(0.15, custom) == "very_weak"
        assert get_score_category(0.25, custom) == "weak"
        assert get_score_category(0.45, custom) == "moderate"
        assert get_score_category(0.65, custom) == "strong"


# ═══════════════════════════════════════════════════════════════════════
# get_effective_score
# ═══════════════════════════════════════════════════════════════════════


class TestGetEffectiveScore:
    """Tests for get_effective_score resolution logic."""

    def test_direct_match_case_insensitive(self):
        perf = {"Data Structures": 0.8, "Algorithms": 0.6}
        mock_embedder = MagicMock()
        settings = _make_settings()

        score, source = get_effective_score(
            "data structures", perf, "Intermediate", mock_embedder, settings,
        )

        assert score == 0.8
        assert source == "direct_match"
        # Embedder should NOT have been called for a direct match
        mock_embedder.encode.assert_not_called()

    def test_direct_match_exact_case(self):
        perf = {"Loops": 0.55}
        mock_embedder = MagicMock()
        settings = _make_settings()

        score, source = get_effective_score(
            "Loops", perf, "Novice", mock_embedder, settings,
        )

        assert score == 0.55
        assert source == "direct_match"

    def test_empty_performance_returns_mastery_fallback(self):
        mock_embedder = MagicMock()
        settings = _make_settings()

        score, source = get_effective_score(
            "Sorting", {}, "Novice", mock_embedder, settings,
        )

        assert score == 0.3
        assert source == "mastery_fallback"

    def test_empty_topic_returns_mastery_fallback(self):
        perf = {"Data Structures": 0.8}
        mock_embedder = MagicMock()
        settings = _make_settings()

        score, source = get_effective_score(
            "", perf, "Expert", mock_embedder, settings,
        )

        assert score == 0.85
        assert source == "mastery_fallback"

    def test_none_performance_returns_mastery_fallback(self):
        mock_embedder = MagicMock()
        settings = _make_settings()

        score, source = get_effective_score(
            "Trees", None, "Intermediate", mock_embedder, settings,
        )

        assert score == 0.6
        assert source == "mastery_fallback"

    def test_mastery_fallback_novice(self):
        mock_embedder = MagicMock()
        settings = _make_settings()

        score, source = get_effective_score(
            "Unknown Topic", {}, "Novice", mock_embedder, settings,
        )

        assert score == 0.3
        assert source == "mastery_fallback"

    def test_mastery_fallback_intermediate(self):
        mock_embedder = MagicMock()
        settings = _make_settings()

        score, source = get_effective_score(
            "Unknown", {}, "Intermediate", mock_embedder, settings,
        )

        assert score == 0.6
        assert source == "mastery_fallback"

    def test_mastery_fallback_expert(self):
        mock_embedder = MagicMock()
        settings = _make_settings()

        score, source = get_effective_score(
            "Unknown", {}, "Expert", mock_embedder, settings,
        )

        assert score == 0.85
        assert source == "mastery_fallback"

    def test_embedder_exception_returns_mastery_fallback(self):
        """If the embedder or semantic match raises, fallback gracefully."""
        perf = {"Data Structures": 0.8}
        mock_embedder = MagicMock()
        mock_embedder.encode.side_effect = RuntimeError("Embedder crashed")
        settings = _make_settings()

        # Patch the import of match_topic_to_performance to use our mocked embedder
        with patch(
            "mcq.scoring_categories.get_effective_score.__module__",
            create=True,
        ):
            score, source = get_effective_score(
                "Sorting Algorithms", perf, "Intermediate",
                mock_embedder, settings,
            )

        # Should NOT raise — should return mastery fallback
        assert isinstance(score, float)
        assert source in ("mastery_fallback", "semantic_match", "direct_match")


# ═══════════════════════════════════════════════════════════════════════
# score_category_description
# ═══════════════════════════════════════════════════════════════════════


class TestScoreCategoryDescription:
    """Tests for score_category_description."""

    def test_all_categories_return_non_empty_string(self):
        for cat in ("very_weak", "weak", "moderate", "strong"):
            desc = score_category_description(cat)
            assert isinstance(desc, str)
            assert len(desc) > 10, f"Description for '{cat}' is too short"

    def test_unknown_category_returns_moderate_default(self):
        desc = score_category_description("nonexistent")
        moderate_desc = score_category_description("moderate")
        assert desc == moderate_desc

    def test_descriptions_are_distinct(self):
        descs = {cat: score_category_description(cat) for cat in ("very_weak", "weak", "moderate", "strong")}
        # All four descriptions should be different
        assert len(set(descs.values())) == 4
