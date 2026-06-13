import os
import requests
from django.db import IntegrityError
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import SurveyTemplate, SurveyQuestion, SurveyResponse, SurveySummary
from .serializers import (
    SurveyTemplateSerializer, SurveyQuestionSerializer,
    SurveyResponseSerializer, SurveySummarySerializer,
)

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8001")


def _is_admin(user):
    return getattr(user, "role", None) == "admin"


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def survey_status(request):
    """GET /api/feedback/surveys/status/?enrollment=<id>
    Returns whether the student still needs to submit a survey for that enrollment.
    """
    enrollment_id = request.query_params.get("enrollment")
    if not enrollment_id:
        return Response({"error": "enrollment param required"}, status=status.HTTP_400_BAD_REQUEST)

    already_submitted = SurveyResponse.objects.filter(enrollment_id=enrollment_id).exists()
    if already_submitted:
        return Response({"pending": False, "template_id": None})

    from apps.courses.models import Enrollment
    from apps.courses.completion import is_course_complete, mark_complete_if_eligible
    try:
        enrollment = Enrollment.objects.select_related("course").get(
            pk=enrollment_id, student=request.user
        )
    except Enrollment.DoesNotExist:
        return Response({"error": "enrollment not found"}, status=status.HTTP_404_NOT_FOUND)

    # Survey fires on genuine course completion: a PASSED capstone for courses
    # that have one, else material at 100%. (Was: material 100% only.)
    mark_complete_if_eligible(enrollment)
    if not is_course_complete(enrollment):
        return Response({"pending": False, "template_id": None})

    # Find a template: course-specific first, then default
    template = (
        SurveyTemplate.objects.filter(course=enrollment.course).first()
        or SurveyTemplate.objects.filter(is_default=True).first()
    )
    return Response({
        "pending": bool(template),
        "template_id": template.id if template else None,
    })


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def survey_questions(request, course_id):
    """GET /api/feedback/surveys/<course_id>/questions/
    Returns the survey template questions for a course.
    """
    from apps.courses.models import Course
    try:
        course = Course.objects.get(pk=course_id)
    except Course.DoesNotExist:
        return Response({"error": "Course not found"}, status=status.HTTP_404_NOT_FOUND)

    template = (
        SurveyTemplate.objects.filter(course=course).first()
        or SurveyTemplate.objects.filter(is_default=True).first()
    )
    if not template:
        return Response({"error": "No survey template for this course"}, status=status.HTTP_404_NOT_FOUND)

    serializer = SurveyTemplateSerializer(template)
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def survey_respond(request):
    """POST /api/feedback/surveys/respond/
    Body: {enrollment_id, template_id, answers: {question_id: value}}
    Enforces one response per enrollment via OneToOneField.
    """
    enrollment_id = request.data.get("enrollment_id")
    template_id = request.data.get("template_id")
    answers = request.data.get("answers", {})

    if not enrollment_id or not template_id:
        return Response({"error": "enrollment_id and template_id required"}, status=400)

    from apps.courses.models import Enrollment
    try:
        enrollment = Enrollment.objects.get(pk=enrollment_id, student=request.user)
    except Enrollment.DoesNotExist:
        return Response({"error": "Enrollment not found"}, status=404)

    try:
        template = SurveyTemplate.objects.get(pk=template_id)
    except SurveyTemplate.DoesNotExist:
        return Response({"error": "Template not found"}, status=404)

    try:
        response_obj = SurveyResponse.objects.create(
            enrollment=enrollment,
            template=template,
            answers=answers,
        )
    except IntegrityError:
        return Response({"error": "Survey already submitted for this enrollment"}, status=409)

    # Check if we should auto-regenerate summary (every 5 new responses)
    total = SurveyResponse.objects.filter(template__course=enrollment.course).count()
    summary, _ = SurveySummary.objects.get_or_create(
        course=enrollment.course,
        defaults={"summary_json": {}, "response_count": 0},
    )
    if total - summary.response_count >= 5:
        # Kick off summary refresh in the background (non-blocking fire-and-forget)
        import threading
        threading.Thread(
            target=_refresh_summary_sync,
            args=(enrollment.course_id,),
            daemon=True,
        ).start()

    return Response(SurveyResponseSerializer(response_obj).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def survey_summary_view(request, course_id):
    """GET /api/feedback/surveys/<course_id>/summary/  (admin only)"""
    if not _is_admin(request.user):
        return Response({"error": "Admin only"}, status=403)

    try:
        summary = SurveySummary.objects.get(course_id=course_id)
    except SurveySummary.DoesNotExist:
        return Response({"error": "No summary generated yet"}, status=404)

    return Response(SurveySummarySerializer(summary).data)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def survey_refresh(request, course_id):
    """POST /api/feedback/surveys/<course_id>/refresh/  (admin only)
    Forces AI summary regeneration for the course.
    """
    if not _is_admin(request.user):
        return Response({"error": "Admin only"}, status=403)

    result = _refresh_summary_sync(course_id)
    if result is None:
        return Response({"error": "Not enough responses to summarize"}, status=400)
    return Response(result)


def _refresh_summary_sync(course_id: int):
    """Fetch all responses for a course, call AI service, save SurveySummary."""
    from apps.courses.models import Course, CourseLearningOutcome

    try:
        course = Course.objects.get(pk=course_id)
    except Course.DoesNotExist:
        return None

    responses = SurveyResponse.objects.filter(
        enrollment__course_id=course_id
    ).select_related("template")

    if not responses.exists():
        return None

    # Aggregate text answers and Likert distributions
    text_answers = []
    likert_distributions: dict[str, dict] = {}
    questions_cache: dict[int, SurveyQuestion] = {}

    for resp in responses:
        for q_id_str, answer in resp.answers.items():
            try:
                q_id = int(q_id_str)
            except (ValueError, TypeError):
                continue

            if q_id not in questions_cache:
                try:
                    questions_cache[q_id] = SurveyQuestion.objects.get(pk=q_id)
                except SurveyQuestion.DoesNotExist:
                    continue

            q = questions_cache[q_id]
            if q.kind == "text" and isinstance(answer, str) and answer.strip():
                text_answers.append(answer.strip())
            elif q.kind == "likert":
                dist = likert_distributions.setdefault(q.prompt, {1: 0, 2: 0, 3: 0, 4: 0, 5: 0})
                try:
                    score = int(answer)
                    if 1 <= score <= 5:
                        dist[score] = dist.get(score, 0) + 1
                except (TypeError, ValueError):
                    pass

    clo_labels = list(
        CourseLearningOutcome.objects.filter(course_id=course_id).values_list("text", flat=True)
    )

    try:
        ai_resp = requests.post(
            f"{AI_SERVICE_URL}/surveys/summarize",
            json={
                "course_id": course_id,
                "text_answers": text_answers,
                "likert_distributions": {k: v for k, v in likert_distributions.items()},
                "clo_labels": clo_labels,
            },
            timeout=120,
        )
        ai_resp.raise_for_status()
        summary_data = ai_resp.json()
    except Exception:
        summary_data = {}

    total = responses.count()
    summary, _ = SurveySummary.objects.update_or_create(
        course=course,
        defaults={"summary_json": summary_data, "response_count": total},
    )
    return SurveySummarySerializer(summary).data
