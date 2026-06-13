"""Unit tests for ai_service/services/mastery.py — pure math only, no I/O."""

import pytest
from services.mastery import (
    update, time_decay, derive_trend, build_entry,
    top_weak_concepts, compute_mastery_updates,
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


class TestBuildEntry:
    def test_evidence_increments(self):
        old = {"score": 0.5, "evidence": 3, "trend": "flat", "last_updated": "", "linked_mistakes": []}
        new = build_entry(old, 1.0)
        assert new["evidence"] == 4

    def test_linked_mistakes_appended_on_fail(self):
        old = {"score": 0.5, "evidence": 0, "trend": "flat", "last_updated": "", "linked_mistakes": []}
        new = build_entry(old, 0.0, mistake_tag="edge_cases")
        assert "edge_cases" in new["linked_mistakes"]

    def test_mistakes_not_appended_on_pass(self):
        old = {"score": 0.5, "evidence": 0, "trend": "flat", "last_updated": "", "linked_mistakes": []}
        new = build_entry(old, 1.0, mistake_tag="edge_cases")
        assert "edge_cases" not in new["linked_mistakes"]

    def test_duplicate_mistakes_not_added(self):
        old = {"score": 0.5, "evidence": 0, "trend": "flat", "last_updated": "", "linked_mistakes": ["edge_cases"]}
        new = build_entry(old, 0.0, mistake_tag="edge_cases")
        assert new["linked_mistakes"].count("edge_cases") == 1

    def test_empty_old_entry_uses_defaults(self):
        new = build_entry({}, 1.0)
        assert new["score"] > 0.5
        assert new["evidence"] == 1

    def test_last_updated_is_set(self):
        new = build_entry({}, 1.0)
        assert new["last_updated"]


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


class TestComputeMasteryUpdates:
    def _make_rubric(self, concept_id, result_value, category="correctness"):
        return {
            "id": "r1",
            "category": category,
            "name": "Test",
            "weight": 100.0,
            "concept_id": concept_id,
            "checks": [{"id": "r1c1", "question": "Q?", "weight": 1.0, "result": result_value}],
        }

    def test_pass_increases_score(self):
        rubric = [self._make_rubric("42", True)]
        updates = compute_mastery_updates(rubric, {})
        assert updates["42"]["score"] > 0.5

    def test_fail_decreases_score(self):
        rubric = [self._make_rubric("42", False)]
        existing = {"42": {"score": 0.8, "evidence": 3, "trend": "up", "last_updated": "", "linked_mistakes": []}}
        updates = compute_mastery_updates(rubric, existing)
        assert updates["42"]["score"] < 0.8

    def test_no_concept_id_is_ignored(self):
        rubric = [self._make_rubric(None, True)]
        updates = compute_mastery_updates(rubric, {})
        assert not updates

    def test_multiple_criteria_same_concept_averaged(self):
        rubric = [
            self._make_rubric("1", True, "correctness"),
            self._make_rubric("1", False, "logic"),
        ]
        updates = compute_mastery_updates(rubric, {})
        # 0.5 average of [1.0, 0.0] → should end up near initial (0.5 outcome → no change from 0.5)
        assert "1" in updates
        # Score should be close to initial 0.5 since average outcome is 0.5
        assert abs(updates["1"]["score"] - 0.5) < 0.05
