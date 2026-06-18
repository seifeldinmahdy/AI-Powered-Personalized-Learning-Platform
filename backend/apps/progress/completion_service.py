"""Server-side session completion — the single place a session becomes "Completed".

A session is genuinely finished only after its problem set runs. The
completion transition is triggered server-side from the problem-set
completion event (AI service → /progress/complete-session/).

`complete_session` is idempotent.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.courses.models import Enrollment
from .models import SessionCompletion

logger = logging.getLogger(__name__)


def _advance_current_session(enrollment, completed_session_number):
    """Advance enrollment.current_session_number if the student completed the current one."""
    update_fields = []
    if enrollment.current_session_number <= completed_session_number:
        enrollment.current_session_number = completed_session_number + 1
        update_fields.append("current_session_number")

    # Recalculate progress_percentage
    completed_count = SessionCompletion.objects.filter(
        enrollment=enrollment, status="Completed"
    ).count()
    
    total_sessions = 0
    if enrollment.current_pathway and isinstance(enrollment.current_pathway, dict) and enrollment.current_pathway.get("total_sessions"):
        total_sessions = enrollment.current_pathway.get("total_sessions")
    else:
        try:
            from apps.courses.views import _fetch_current_plan
            plan = _fetch_current_plan(enrollment.student_id, enrollment.course_id)
            if plan and plan.get("total_sessions"):
                total_sessions = int(plan.get("total_sessions"))
        except Exception:
            pass
        
    if total_sessions > 0:
        new_pct = min(100.0, (completed_count / float(total_sessions)) * 100.0)
        if enrollment.progress_percentage != new_pct:
            enrollment.progress_percentage = new_pct
            update_fields.append("progress_percentage")
            
    if update_fields:
        enrollment.save(update_fields=update_fields)


def complete_session(user, course, session_number, *, time_spent_minutes=None, score=None):
    """Idempotently mark `session_number` Completed for `user`. Returns a dict:

        {"completion": SessionCompletion, "already_completed": bool,
         "newly_earned_achievements": [{name, icon_url, xp_reward}, ...]}

    Returns ``None`` if the student has no enrollment in the course.
    """
    from apps.gamification.models import UserAchievement

    enrollment = Enrollment.objects.filter(student=user, course=course).first()
    if not enrollment:
        logger.warning(
            "complete_session: no enrollment for student=%s course=%s session=%s",
            user.id, course.id, session_number,
        )
        return None

    before_ids = set(
        UserAchievement.objects.filter(user=user).values_list("achievement_id", flat=True)
    )

    with transaction.atomic():
        completion, _created = (
            SessionCompletion.objects.select_for_update().get_or_create(
                enrollment=enrollment,
                session_number=session_number,
                defaults={"status": "In Progress"},
            )
        )

        already = completion.status == "Completed" and completion.completed_at is not None
        if already:
            _advance_current_session(enrollment, session_number)
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
            if tsm > 0 or completion.time_spent_minutes == 0:
                completion.time_spent_minutes = tsm
        if completion.time_spent_minutes == 0:
            completion.time_spent_minutes = 30
        completion.save()

    _advance_current_session(enrollment, session_number)

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
