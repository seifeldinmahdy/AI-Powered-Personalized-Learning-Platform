"""Derived (never-stored) student-facing problem-set scoring.

The student-facing lesson score is computed from append-only attempts, never
written back as a mutable field. Exact aggregation (per the agreed spec):

    per question  -> best attempt score        (max over that question's attempts)
    per generation-> mean of its questions' bests
    per lesson    -> best generation score      (max over generations)

i.e. per-question-best, aggregated (mean) ACROSS that generation's questions,
then the best such generation — NOT the single highest-scoring question attempt.

Content-free: the denominator is the denormalized ``num_questions`` and the
numerator comes from attempt rows, so this never loads ``content_json`` — the
resume timeline can show best scores without a content scan.

Best score (visible) and mastery (truth-tracking) are SEPARATE levers: this
function never touches mastery.
"""

from .models import ProblemSet


def generation_score(problem_set: ProblemSet) -> float | None:
    """Mean of per-question best attempt scores for one generation.

    Unattempted questions count as 0 via the ``num_questions`` denominator.
    Returns None when the generation has no questions to score against.
    """
    n = problem_set.num_questions or 0
    if n <= 0:
        return None
    best_by_q: dict[str, int] = {}
    for att in problem_set.attempts.all():
        if att.score > best_by_q.get(att.question_id, -1):
            best_by_q[att.question_id] = att.score
    # Sum of attempted-question bests; unattempted contribute 0 through n.
    return round(sum(best_by_q.values()) / n, 2)


def best_lesson_score(enrollment_id: int, lesson_id: int, plan_version: int | None = None) -> float | None:
    """Best generation score for a lesson across its retained generations.

    ``plan_version`` filters to one course version when supplied (a new plan
    version is a genuinely different course); omitted = across all versions.
    Superseded (regenerated-over) generations still count — they are retained.
    Loads no content (defers content_json / hint_tracking).
    """
    qs = ProblemSet.objects.filter(enrollment_id=enrollment_id, lesson_id=lesson_id)
    if plan_version is not None:
        qs = qs.filter(plan_version=plan_version)
    qs = qs.defer("content_json", "hint_tracking").prefetch_related("attempts")

    scores = [s for s in (generation_score(ps) for ps in qs) if s is not None]
    return max(scores) if scores else None
