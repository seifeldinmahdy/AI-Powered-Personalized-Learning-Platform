"""
Artifact storage endpoints (Batch 10a backbone).

Callers: the AI service (service-key + X-Student-ID, resolved to request.user by
InternalServiceAuthentication) and the frontend (JWT). ACCESS RULE: every read
and write authorizes ownership (artifact.student == request.user) BEFORE doing
anything. Key obscurity is not access control.

The submit hot path is two round-trips, not N: one GET resolves the problem set
(content + hint_tracking + generation), one POST appends the attempt.
"""

import logging

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.courses.models import Course, Enrollment
from .models import PlacementAttempt, StudentArtifact, ProblemSet, ProblemSetAttempt
from .serializers import (
    PlacementAttemptSerializer, StudentArtifactSerializer,
    StudentArtifactIndexSerializer, ProblemSetSerializer, ProblemSetAttemptSerializer,
)
from .scoring import best_session_score

logger = logging.getLogger(__name__)

# Student-initiated problem-set regenerations allowed per (enrollment, session_number,
# plan_version). Resets when plan_version changes: a new plan version is a
# genuinely different course and shouldn't carry the old penalty.
MAX_PROBLEM_SET_REGENERATIONS = 3


def _resolve_enrollment(user, course_id):
    """Resolve the caller's enrollment for a course, or None."""
    return Enrollment.objects.filter(student=user, course_id=course_id).first()


# ── Placement attempts (EVENT) ───────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def placement_attempt_create(request):
    """Append a PlacementAttempt (immutable). A re-take is a new row."""
    course_id = request.data.get("course_id")
    enrollment = _resolve_enrollment(request.user, course_id)
    if not enrollment:
        return Response({"error": "Not enrolled in this course."}, status=status.HTTP_403_FORBIDDEN)

    attempt = PlacementAttempt.objects.create(
        enrollment=enrollment,
        student=request.user,
        course_id=course_id,
        answers=request.data.get("answers", []),
        per_question=request.data.get("per_question", []),
        score=int(request.data.get("score", 0) or 0),
        concept_results=request.data.get("concept_results", {}),
    )
    return Response(PlacementAttemptSerializer(attempt).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def placement_attempt_latest(request):
    """Latest placement attempt for the caller + course (drives the snapshot)."""
    course_id = request.query_params.get("course")
    attempt = (
        PlacementAttempt.objects
        .filter(student=request.user, course_id=course_id)
        .order_by("-created_at", "-id")
        .first()
    )
    if not attempt:
        return Response({"detail": "No placement attempt."}, status=status.HTTP_404_NOT_FOUND)
    return Response(PlacementAttemptSerializer(attempt).data)


# ── Student artifacts: slides + labs (INDEX + inline content) ─────────────────

@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def artifact_upsert(request):
    """Create or update a slides/lab artifact by its unique index key.

    Upsert (not append) — re-generating the same (type, session,
    plan_version, generation_index) overwrites the stored content. Slides persist
    here at generation time (net-new; previously slides were never saved).
    """
    course_id = request.data.get("course_id")
    enrollment = _resolve_enrollment(request.user, course_id)
    if not enrollment:
        return Response({"error": "Not enrolled in this course."}, status=status.HTTP_403_FORBIDDEN)

    artifact_type = request.data.get("artifact_type")
    if artifact_type not in (StudentArtifact.SLIDES, StudentArtifact.LAB):
        return Response({"error": "artifact_type must be slides|lab."}, status=status.HTTP_400_BAD_REQUEST)

    defaults = {
        "student": request.user,
        "course_id": course_id,
        "content_json": request.data.get("content_json", {}),
        "status": request.data.get("status", "generated"),
        "score": request.data.get("score"),
    }
    obj, created = StudentArtifact.objects.update_or_create(
        enrollment=enrollment,
        artifact_type=artifact_type,
        session_number=request.data.get("session_number"),
        plan_version=request.data.get("plan_version"),
        generation_index=request.data.get("generation_index", 0),
        defaults=defaults,
    )
    return Response(
        StudentArtifactSerializer(obj).data,
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def artifact_index(request):
    """List the caller's artifacts (metadata only). Filters: type, session,
    plan_version. Content is fetched per-row via artifact_content."""
    qs = StudentArtifact.objects.filter(student=request.user)
    for param, field in (("type", "artifact_type"), ("session", "session_number"),
                         ("plan_version", "plan_version")):
        val = request.query_params.get(param)
        if val not in (None, ""):
            qs = qs.filter(**{field: val})
    return Response(StudentArtifactIndexSerializer(qs, many=True).data)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def artifact_content(request, pk):
    """Fetch one artifact's content — OWNERSHIP CHECKED before returning."""
    artifact = get_object_or_404(StudentArtifact, pk=pk)
    if artifact.student_id != request.user.id:
        return Response({"error": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
    return Response(StudentArtifactSerializer(artifact).data)


# ── Problem sets (INDEX) + attempts (EVENT) ───────────────────────────────────

def _regen_state(enrollment_id, session_number, plan_version):
    """Return (max_generation_index, set_count) for a regen key (-1 if none)."""
    qs = ProblemSet.objects.filter(
        enrollment_id=enrollment_id, session_number=session_number, plan_version=plan_version
    )
    count = qs.count()
    if count == 0:
        return -1, 0
    max_idx = max(ps.generation_index for ps in qs)
    return max_idx, count


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def problem_set_create(request):
    """Create a problem-set generation.

    First generation: generation_index=0. ``regenerate=true`` bumps the index,
    supersedes (retains) prior generations, and enforces the regen cap per
    (enrollment, session_number, plan_version) — which resets when plan_version changes.
    """
    course_id = request.data.get("course_id")
    enrollment = _resolve_enrollment(request.user, course_id)
    if not enrollment:
        return Response({"error": "Not enrolled in this course."}, status=status.HTTP_403_FORBIDDEN)

    session_number = request.data.get("session_number")
    plan_version = request.data.get("plan_version")
    regenerate = bool(request.data.get("regenerate", False))

    with transaction.atomic():
        max_idx, _ = _regen_state(enrollment.id, session_number, plan_version)

        if regenerate:
            next_index = max_idx + 1
            if next_index > MAX_PROBLEM_SET_REGENERATIONS:
                return Response(
                    {"error": f"Regeneration limit reached ({MAX_PROBLEM_SET_REGENERATIONS}) "
                              "for this session and plan version.",
                     "regenerations_used": max_idx, "max": MAX_PROBLEM_SET_REGENERATIONS},
                    status=status.HTTP_409_CONFLICT,
                )
            ProblemSet.objects.filter(
                enrollment=enrollment, session_number=session_number, plan_version=plan_version
            ).update(superseded=True)
        else:
            # A plain create after an existing generation is treated as gen 0 only
            # when none exists; otherwise it is the current latest (idempotent-ish).
            next_index = max_idx + 1 if max_idx >= 0 else 0
            if max_idx >= 0:
                ProblemSet.objects.filter(
                    enrollment=enrollment, session_number=session_number, plan_version=plan_version
                ).update(superseded=True)

        content_json = request.data.get("content_json", {})
        ps = ProblemSet.objects.create(
            enrollment=enrollment,
            student=request.user,
            course_id=course_id,
            session_number=session_number,
            plan_version=plan_version,
            generation_index=next_index,
            ps_uid=request.data["ps_uid"],
            content_json=content_json,
            num_questions=len(content_json.get("questions", []) or []),
            superseded=False,
        )
    return Response(ProblemSetSerializer(ps).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def problem_set_list(request):
    """List problem sets for a student, optionally filtered by session_number."""
    session_number = request.query_params.get("session_number")
    course_id = request.query_params.get("course_id")
    
    qs = ProblemSet.objects.filter(student=request.user)
    if session_number:
        qs = qs.filter(session_number=session_number)
    if course_id:
        qs = qs.filter(course_id=course_id)
        
    return Response(ProblemSetSerializer(qs, many=True).data)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def problem_set_detail(request, ps_uid):
    """Resolve a problem set by uid — the SINGLE GET of the submit hot path.

    Returns content + hint_tracking + generation_index so the evaluator needs no
    further reads before appending the attempt. Ownership checked.
    """
    ps = get_object_or_404(ProblemSet, ps_uid=ps_uid)
    if ps.student_id != request.user.id:
        return Response({"error": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
    return Response(ProblemSetSerializer(ps).data)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def problem_set_attempt_create(request, ps_uid):
    """Append a ProblemSetAttempt (immutable) — the SINGLE POST of submit.

    ``source`` is derived from the generation (original vs regenerated) so Batch
    6's mastery writer can down-weight regenerated-set attempts.
    """
    ps = get_object_or_404(ProblemSet, ps_uid=ps_uid)
    if ps.student_id != request.user.id:
        return Response({"error": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    source = ProblemSetAttempt.ORIGINAL if ps.generation_index == 0 else ProblemSetAttempt.REGENERATED
    attempt = ProblemSetAttempt.objects.create(
        problem_set=ps,
        question_id=request.data.get("question_id", ""),
        code=request.data.get("code", ""),
        evaluated_rubric=request.data.get("evaluated_rubric", []),
        hints_used=int(request.data.get("hints_used", 0) or 0),
        score=int(request.data.get("score", 0) or 0),
        source=source,
    )
    return Response(ProblemSetAttemptSerializer(attempt).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def problem_set_attempt_history(request, ps_uid):
    """Read-only attempt history + best score for a problem set (ownership checked).

    Drives the past-problem-set view: every submission in order, plus the
    derived best score for the session.
    """
    ps = get_object_or_404(ProblemSet, ps_uid=ps_uid)
    if ps.student_id != request.user.id:
        return Response({"error": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
    attempts = ps.attempts.all()  # ordered by created_at, id (submission order)
    return Response({
        "ps_uid": ps.ps_uid,
        "session_number": ps.session_number,
        "generation_index": ps.generation_index,
        "superseded": ps.superseded,
        "best_score": best_session_score(ps.enrollment_id, ps.session_number, ps.plan_version),
        "attempts": ProblemSetAttemptSerializer(attempts, many=True).data,
    })


@api_view(["PATCH"])
@permission_classes([permissions.IsAuthenticated])
def problem_set_hint_tracking(request, ps_uid):
    """Merge pre-submission hint working-state into the set (not an attempt)."""
    ps = get_object_or_404(ProblemSet, ps_uid=ps_uid)
    if ps.student_id != request.user.id:
        return Response({"error": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
    tracking = ps.hint_tracking or {}
    tracking.update(request.data.get("hint_tracking", {}))
    ps.hint_tracking = tracking
    ps.save(update_fields=["hint_tracking"])
    return Response(ProblemSetSerializer(ps).data)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def problem_set_regen_count(request):
    """Regeneration counter for (enrollment, session_number, plan_version)."""
    course_id = request.query_params.get("course")
    enrollment = _resolve_enrollment(request.user, course_id)
    if not enrollment:
        return Response({"error": "Not enrolled."}, status=status.HTTP_403_FORBIDDEN)
    session_number = request.query_params.get("session_number")
    plan_version = request.query_params.get("plan_version")
    max_idx, _ = _regen_state(enrollment.id, session_number, plan_version)
    used = max(max_idx, 0)
    return Response({
        "regenerations_used": used,
        "remaining": max(0, MAX_PROBLEM_SET_REGENERATIONS - used),
        "max": MAX_PROBLEM_SET_REGENERATIONS,
    })


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def problem_set_score(request):
    """Student-facing best session score (derived from attempts, never stored)."""
    course_id = request.query_params.get("course")
    enrollment = _resolve_enrollment(request.user, course_id)
    if not enrollment:
        return Response({"error": "Not enrolled."}, status=status.HTTP_403_FORBIDDEN)
    session_number = request.query_params.get("session_number")
    plan_version = request.query_params.get("plan_version")
    pv = int(plan_version) if plan_version not in (None, "") else None
    best = best_session_score(enrollment.id, session_number, pv)
    return Response({"best_score": best})
