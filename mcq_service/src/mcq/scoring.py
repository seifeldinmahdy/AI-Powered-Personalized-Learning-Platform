"""Checkpoint scoring — scores student answers and computes per-topic performance.

Uses the existing ``update_topic_performance_scores`` from ai_service's
topic_mastery.py for the weighted moving average update.
"""

from __future__ import annotations

import structlog

from mcq.models import CheckpointResult, CheckpointSubmission, MCQQuestion

logger = structlog.get_logger(__name__)


def score_checkpoint(submission: CheckpointSubmission) -> CheckpointResult:
    """Score a checkpoint submission and return per-topic breakdown.

    Parameters
    ----------
    submission :
        The student's answers to a set of checkpoint questions.

    Returns
    -------
    CheckpointResult
        Overall score, per-topic scores, and per-question detail.
    """
    questions = submission.questions
    answers = submission.answers
    total = len(questions)

    if total == 0:
        return CheckpointResult(
            score=0.0,
            per_topic_scores={},
            correct_count=0,
            total_count=0,
            question_results=[],
        )

    question_results: list[dict] = []
    correct_count = 0

    # Per-topic accumulators
    topic_correct: dict[str, int] = {}
    topic_total: dict[str, int] = {}

    for idx, q in enumerate(questions):
        chosen = answers.get(idx, "")
        is_correct = chosen.strip() == q.correct_answer.strip()

        if is_correct:
            correct_count += 1

        question_results.append({
            "index": idx,
            "correct": is_correct,
            "chosen_answer": chosen,
            "correct_answer": q.correct_answer,
            "explanation": q.explanation,
            "question_type": q.question_type,
            "topic": q.topic,
        })

        topic = q.topic or "General"
        topic_total[topic] = topic_total.get(topic, 0) + 1
        if is_correct:
            topic_correct[topic] = topic_correct.get(topic, 0) + 1

    # Compute per-topic scores
    per_topic_scores: dict[str, float] = {}
    for topic, total_count in topic_total.items():
        per_topic_scores[topic] = round(
            topic_correct.get(topic, 0) / total_count, 4,
        )

    overall_score = round(correct_count / total, 4) if total > 0 else 0.0

    logger.info(
        "checkpoint_scored",
        student_id=submission.student_id,
        course_id=submission.course_id,
        session_number=submission.session_number,
        checkpoint_index=submission.checkpoint_index,
        score=overall_score,
        correct=correct_count,
        total=total,
        per_topic=per_topic_scores,
    )

    return CheckpointResult(
        score=overall_score,
        per_topic_scores=per_topic_scores,
        correct_count=correct_count,
        total_count=total,
        question_results=question_results,
    )
