"""
Capstone-aware course completion.

Single source of truth for "is this course complete for this enrollment?".

Rules (additive — nothing here changes how `progress_percentage` is computed):
  • Course WITHOUT a capstone  → complete when material reaches 100%.
  • Course WITH a capstone      → complete only when the capstone is PASSED,
    regardless of whether material is at 100%. The capstone is the terminal gate.

`mark_complete_if_eligible` stamps `Enrollment.completed_at` exactly once, the
first time completion is observed, so the certificate has a stable date.
"""

from __future__ import annotations

from django.utils import timezone


def course_requires_capstone(course) -> bool:
    """True if the course has a live (active/completed) capstone."""
    from apps.capstone.models import Capstone
    return Capstone.objects.filter(
        course=course, status__in=["active", "completed"]
    ).exists()


def capstone_passed(enrollment) -> bool:
    """True if this enrollment has a capstone submission with a PASS verdict."""
    from apps.capstone.models import CapstoneSubmission
    return CapstoneSubmission.objects.filter(
        enrollment=enrollment, verdict="pass"
    ).exists()


def material_complete(enrollment) -> bool:
    """True if the course material (lessons/labs/problem-sets) is at 100%."""
    try:
        return float(enrollment.progress_percentage or 0) >= 100
    except (TypeError, ValueError):
        return False


def is_course_complete(enrollment) -> bool:
    """Capstone-aware completion check (the terminal gate)."""
    if course_requires_capstone(enrollment.course):
        return capstone_passed(enrollment)
    return material_complete(enrollment)


def mark_complete_if_eligible(enrollment):
    """
    Stamp completed_at the first time the course is complete. Idempotent:
    returns the existing timestamp if already set, the new one if just set,
    or None if not yet complete.
    """
    if enrollment.completed_at:
        return enrollment.completed_at
    if not is_course_complete(enrollment):
        return None
    enrollment.completed_at = timezone.now()
    enrollment.save(update_fields=["completed_at"])
    return enrollment.completed_at
