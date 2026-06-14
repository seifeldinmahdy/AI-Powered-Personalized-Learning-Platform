"""Unit tests for ai_service/services/mastery.py — pure math only, no I/O."""

import pytest
from services.mastery import (
    update, time_decay, derive_trend,
    top_weak_concepts, outcomes_from_eval,
)


class TestUpdate:
    def test_outcome_1_increases_score(self):
        new = update(0.5, 1.0)
        assert new > 0.5

    def test_outcome_0_decreases_score(self):
        new = update(0.5, 0.0)
        assert new < 0.5

    def test_converges_to_1_on_repeated_passes(self):
        score = 0.5
        for _ in range(50):
            score = update(score, 1.0)
        assert score > 0.95

    def test_converges_to_0_on_repeated_fails(self):
        score = 0.5
        for _ in range(50):
            score = update(score, 0.0)
        assert score < 0.05

    def test_custom_alpha(self):
        new = update(0.0, 1.0, alpha=1.0)
        assert new == 1.0


class TestTimeDecay:
    def test_no_decay_at_zero_days(self):
        s = time_decay(0.8, 0)
        assert abs(s - 0.8) < 0.0001

    def test_half_life_halves_distance_from_neutral(self):
        s = time_decay(0.9, 30.0, half_life=30.0)
        # distance from 0.5 should halve: (0.9-0.5)*0.5 = 0.2, so 0.5+0.2=0.7
        assert abs(s - 0.7) < 0.001

    def test_decays_toward_05_not_0(self):
        s = time_decay(0.1, 1000, half_life=30.0)
        assert abs(s - 0.5) < 0.01


class TestDeriveTrend:
    def test_up_when_new_significantly_higher(self):
        assert derive_trend(0.4, 0.5) == "up"

    def test_down_when_new_significantly_lower(self):
        assert derive_trend(0.6, 0.5) == "down"

    def test_flat_when_change_within_epsilon(self):
        assert derive_trend(0.5, 0.51) == "flat"

    def test_flat_when_equal(self):
        assert derive_trend(0.5, 0.5) == "flat"


class TestTopWeakConcepts:
    def test_returns_n_weakest(self):
        cm = {
            "1": {"score": 0.3, "evidence": 5},
            "2": {"score": 0.8, "evidence": 5},
            "3": {"score": 0.1, "evidence": 2},
            "4": {"score": 0.5, "evidence": 1},
        }
        result = top_weak_concepts(cm, n=2)
        assert len(result) == 2
        assert result[0]["concept_id"] == "3"  # lowest score

    def test_empty_mastery_returns_empty(self):
        assert top_weak_concepts({}) == []

    def test_respects_n_limit(self):
        cm = {str(i): {"score": i * 0.1, "evidence": 1} for i in range(10)}
        assert len(top_weak_concepts(cm, n=3)) == 3


class TestDeriveMasteryLevel:
    def test_assist_only_concept_counts_as_data(self):
        from services.mastery import derive_mastery_level
        # Concept "2" is assist-only (evidence 0) with a low score. It must COUNT
        # in the mean (→ Intermediate), not be dropped as "no data" (→ Expert).
        cm = {"1": {"score": 0.9, "evidence": 3}, "2": {"score": 0.1, "evidence": 0}}
        assert derive_mastery_level(cm) == "Intermediate"

    def test_truly_empty_is_novice(self):
        from services.mastery import derive_mastery_level
        assert derive_mastery_level({}) == "Novice"


class TestOutcomesFromEval:
    """outcomes_from_eval aggregates rubric → per-concept OUTCOMES (no EMA)."""

    def _make_rubric(self, concept_id, result_value, category="correctness"):
        return {
            "id": "r1", "category": category, "name": "Test", "weight": 100.0,
            "concept_id": concept_id,
            "checks": [{"id": "r1c1", "question": "Q?", "weight": 1.0, "result": result_value}],
        }

    def test_pass_outcome_is_one(self):
        out = outcomes_from_eval([self._make_rubric("42", True)])
        assert out == [{"concept_id": "42", "outcome": 1.0, "mistake_tag": ""}]

    def test_fail_outcome_is_zero_with_tag(self):
        out = outcomes_from_eval([self._make_rubric("42", False, "logic")])
        assert out[0]["outcome"] == 0.0
        assert out[0]["mistake_tag"] == "logic"

    def test_no_concept_id_is_ignored(self):
        assert outcomes_from_eval([self._make_rubric(None, True)]) == []

    def test_multiple_criteria_same_concept_averaged(self):
        out = outcomes_from_eval([
            self._make_rubric("1", True, "correctness"),
            self._make_rubric("1", False, "logic"),
        ])
        assert len(out) == 1 and out[0]["concept_id"] == "1"
        assert abs(out[0]["outcome"] - 0.5) < 1e-9
