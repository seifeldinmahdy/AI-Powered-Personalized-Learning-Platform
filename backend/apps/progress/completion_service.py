"""Server-side lesson completion — the single place a lesson becomes "Completed".

A lesson is genuinely finished only after its problem set runs (that step writes
the concept_mastery capstone grading and CLO attainment depend on). The
completion transition is therefore triggered server-side from the problem-set
completion event (AI service → /progress/complete-lesson/), NOT from a frontend
"mark complete" call at the end of the live session. This keeps it resilient to a
closed tab and removes the contradiction where a student could reach the capstone
CTA (progress == 100) without having done the final, mastery-writing step.

`complete_lesson` is idempotent: it transitions the row to "Completed" once, under
a row lock, and lets the gamification post_save signal award XP/streak/progress
exactly once (the signal carries its own latch as well). Calling it again is a
no-op that re-reports the already-awarded achievements as none.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.courses.models import Enrollment
from .models import LessonCompletion

logger = logging.getLogger(__name__)


def _lesson_course_id(lesson):
    """Resolve the owning course id for a lesson (lesson → module → course)."""
    return lesson.module.course_id


def _advance_current_lesson(enrollment):
    """Point enrollment.current_lesson at the first incomplete lesson (or the
    last lesson when all are done). Drives the resume "Continue" jump."""
    from apps.courses.models import Lesson

    completed_ids = set(
        LessonCompletion.objects.filter(enrollment=enrollment, status="Completed")
        .values_list("lesson_id", flat=True)
    )
    lessons = list(
        Lesson.objects.filter(module__course_id=enrollment.course_id)
        .order_by("module__module_order", "lesson_order")
    )
    if not lessons:
        return
    target = next((l for l in lessons if l.id not in completed_ids), lessons[-1])
    if enrollment.current_lesson_id != target.id:
        enrollment.current_lesson_id = target.id
        enrollment.save(update_fields=["current_lesson"])


def complete_lesson(user, lesson, *, time_spent_minutes=None, score=None):
    """Idempotently mark `lesson` Completed for `user`. Returns a dict:

        {"completion": LessonCompletion, "already_completed": bool,
         "newly_earned_achievements": [{name, icon_url, xp_reward}, ...]}

    Returns ``None`` if the student has no enrollment in the lesson's course.

    The transition (and the gamification signal it triggers) fires at most once
    per completion. Time/score are recorded conservatively: an existing positive
    time_spent is never overwritten (the live session already measured it).
    """
    from apps.gamification.models import UserAchievement

    course_id = _lesson_course_id(lesson)
    enrollment = Enrollment.objects.filter(student=user, course_id=course_id).first()
    if not enrollment:
        logger.warning(
            "complete_lesson: no enrollment for student=%s course=%s lesson=%s",
            user.id, course_id, lesson.id,
        )
        return None

    before_ids = set(
        UserAchievement.objects.filter(user=user).values_list("achievement_id", flat=True)
    )

    with transaction.atomic():
        completion, _created = (
            LessonCompletion.objects.select_for_update().get_or_create(
                enrollment=enrollment,
                lesson=lesson,
                defaults={"status": "In Progress"},
            )
        )

        already = completion.status == "Completed" and completion.completed_at is not None
        if already:
            return {
                "completion": completion,
                "already_completed": True,
                "newly_earned_achievements": [],
            }

        completion.status = "Completed"
        completion.completed_at = timezone.now()
        if score is not None:
            completion.score = score
        if time_spent_minutes is not None:
            try:
                tsm = max(0, int(time_spent_minutes))
            except (TypeError, ValueError):
                tsm = 0
            # Never clobber a positive measured time with a default/zero.
            if tsm > 0 or completion.time_spent_minutes == 0:
                completion.time_spent_minutes = tsm
        if completion.time_spent_minutes == 0:
            completion.time_spent_minutes = 30  # backward-compat default
        completion.save()  # fires the gamification signal exactly once

    # Advance the resume pointer to the first still-incomplete lesson (self-
    # correcting regardless of completion order) so "Continue" lands correctly.
    _advance_current_lesson(enrollment)

    after = UserAchievement.objects.filter(user=user).select_related("achievement")
    newly_earned = [
        {"name": ua.achievement.name, "icon_url": ua.achievement.icon_url,
         "xp_reward": ua.achievement.xp_reward}
        for ua in after if ua.achievement_id not in before_ids
    ]
    return {
        "completion": completion,
        "already_completed": False,
        "newly_earned_achievements": newly_earned,
    }
