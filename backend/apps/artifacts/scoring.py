"""Derived (never-stored) student-facing problem-set scoring.

The student-facing lesson score is computed from append-only attempts, never
written back as a mutable field. Exact aggregation (per the agreed spec):

    per question  -> best attempt score        (max over that question's attempts)
    per generation-> mean of its questions' bests
    per lesson    -> best generation score      (max over generations)

i.e. per-question-best, aggregated (mean) ACROSS that generation's questions,
then the best such generation — NOT the single highest-scoring question attempt.

Best score (visible) and mastery (truth-tracking) are SEPARATE levers: this
function never touches mastery.
"""

from .models import ProblemSet, ProblemSetAttempt


def generation_score(problem_set: ProblemSet) -> float | None:
    """Mean of per-question best attempt scores for one generation.

    Returns None if the generation has no questions to score against.
    """
    questions = (problem_set.content_json or {}).get("questions", []) or []
    question_ids = [q.get("id") for q in questions if q.get("id")]
    if not question_ids:
        return None

    best_by_q: dict[str, int] = {}
    for att in problem_set.attempts.all():
        prev = best_by_q.get(att.question_id)
        if prev is None or att.score > prev:
            best_by_q[att.question_id] = att.score

    # Unattempted questions count as 0 (a half-finished set is not a 100%).
    total = sum(best_by_q.get(qid, 0) for qid in question_ids)
    return round(total / len(question_ids), 2)


def best_lesson_score(enrollment_id: int, lesson_id: int, plan_version: int | None = None) -> float | None:
    """Best generation score for a lesson across its retained generations.

    ``plan_version`` filters to one course version when supplied (a new plan
    version is a genuinely different course); omitted = across all versions.
    Superseded (regenerated-over) generations still count — they are retained.
    """
    qs = ProblemSet.objects.filter(enrollment_id=enrollment_id, lesson_id=lesson_id)
    if plan_version is not None:
        qs = qs.filter(plan_version=plan_version)
    qs = qs.prefetch_related("attempts")

    scores = [s for s in (generation_score(ps) for ps in qs) if s is not None]
    return max(scores) if scores else None
