"""Tests for checkpoint scoring — focus on per-concept aggregation, the signal
that feeds concept mastery on the write path."""

from mcq.models import CheckpointSubmission, MCQQuestion
from mcq.scoring import score_checkpoint


def _q(correct_answer: str, topic: str, concept_id: str = "") -> MCQQuestion:
    """Build a minimal valid MCQQuestion (4 options, one correct)."""
    return MCQQuestion(
        question=f"Q about {topic}?",
        options=[
            {"text": correct_answer, "is_correct": True},
            {"text": "x", "is_correct": False},
            {"text": "y", "is_correct": False},
            {"text": "z", "is_correct": False},
        ],
        correct_answer=correct_answer,
        explanation="because",
        question_type="4a",
        topic=topic,
        concept_id=concept_id,
        mastery_used="Novice",
        score_category_used="weak",
        generation_mode="test",
    )


def _submit(questions, answers) -> CheckpointSubmission:
    return CheckpointSubmission(
        questions=questions,
        answers=answers,
        student_id="7",
        course_id="3",
        session_number=1,
        checkpoint_index=0,
    )


def test_per_concept_scores_aggregate_by_concept_id():
    # Two concepts: c1 (one right, one wrong → 0.5), c2 (one right → 1.0)
    questions = [
        _q("a", "Recursion", concept_id="c1"),
        _q("b", "Recursion", concept_id="c1"),
        _q("c", "Loops", concept_id="c2"),
    ]
    answers = {0: "a", 1: "WRONG", 2: "c"}
    result = score_checkpoint(_submit(questions, answers))

    assert result.per_concept_scores == {"c1": 0.5, "c2": 1.0}
    # Topic scores still produced (legacy/display)
    assert result.per_topic_scores["Loops"] == 1.0
    # question_results carry the concept_id
    assert result.question_results[0]["concept_id"] == "c1"


def test_untagged_questions_yield_empty_per_concept():
    questions = [_q("a", "Loops"), _q("b", "Loops")]
    result = score_checkpoint(_submit(questions, {0: "a", 1: "b"}))

    assert result.per_concept_scores == {}
    assert result.per_topic_scores == {"Loops": 1.0}


def test_mixed_tagged_and_untagged():
    questions = [_q("a", "Loops", concept_id="c1"), _q("b", "Sets")]
    result = score_checkpoint(_submit(questions, {0: "WRONG", 1: "b"}))

    # Only the tagged question contributes to per-concept
    assert result.per_concept_scores == {"c1": 0.0}
