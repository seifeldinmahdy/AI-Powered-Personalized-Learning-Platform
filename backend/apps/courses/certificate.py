"""
Course completion certificate.

Issued only when BOTH gates are satisfied:
  (a) the course is complete  — a PASSED capstone for courses that have one,
      else material at 100%   (apps.courses.completion.is_course_complete), AND
  (b) the post-course survey has been submitted for this enrollment.

Two endpoints:
  GET .../certificate/      → JSON for the on-page certificate render.
  GET .../certificate/pdf/  → a generated PDF (reportlab), on demand, nothing stored.
"""

from __future__ import annotations

import io

from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

CLO_ATTAINMENT_THRESHOLD = 0.6  # a CLO is "attained" at/above this mastery


def _clos_attained(course, student_id: int) -> list[dict]:
    """CLOs whose mean linked-concept mastery is at/above the threshold."""
    from apps.progress.models import StudentLearningProfile
    from .models import CourseLearningOutcome

    profile = StudentLearningProfile.objects.filter(student_id=student_id).first()
    cm = (profile.concept_mastery or {}) if profile else {}

    attained = []
    clos = CourseLearningOutcome.objects.filter(course=course).prefetch_related("concepts")
    for clo in clos:
        scores = [
            cm[str(c.id)]["score"]
            for c in clo.concepts.all()
            if str(c.id) in cm and isinstance(cm[str(c.id)], dict)
        ]
        if scores and (sum(scores) / len(scores)) >= CLO_ATTAINMENT_THRESHOLD:
            attained.append({"code": clo.code, "text": clo.text})
    return attained


def _resolve_eligibility(user, course_id):
    """
    Return (enrollment, error_response). error_response is None when the student
    may receive a certificate (course complete AND survey submitted).
    """
    from .models import Enrollment
    from .completion import is_course_complete, mark_complete_if_eligible
    from apps.feedback.models import SurveyResponse

    try:
        enrollment = Enrollment.objects.select_related("course", "student").get(
            course_id=course_id, student=user
        )
    except Enrollment.DoesNotExist:
        return None, Response({"error": "Not enrolled in this course."},
                              status=status.HTTP_404_NOT_FOUND)

    mark_complete_if_eligible(enrollment)
    if not is_course_complete(enrollment):
        return None, Response(
            {"error": "Course not complete yet.",
             "reason": "Pass the capstone to complete the course."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if not SurveyResponse.objects.filter(enrollment=enrollment).exists():
        return None, Response(
            {"error": "Survey required before the certificate unlocks.",
             "reason": "survey_required"},
            status=status.HTTP_403_FORBIDDEN,
        )

    return enrollment, None


def _certificate_payload(enrollment) -> dict:
    """Shared certificate fields used by both the JSON and PDF endpoints."""
    from apps.capstone.models import CapstoneSubmission

    student = enrollment.student
    student_name = student.get_full_name() or student.username
    completed_at = enrollment.completed_at

    sub = (
        CapstoneSubmission.objects
        .filter(enrollment=enrollment, verdict="pass")
        .order_by("-evaluated_at")
        .first()
    )

    return {
        "student_name": student_name,
        "course_title": enrollment.course.title,
        "completion_date": completed_at.date().isoformat() if completed_at else None,
        "clos_attained": _clos_attained(enrollment.course, student.id),
        "score": sub.score if sub else None,
        # Verification id ties the certificate to a concrete enrollment(+submission).
        "verification_id": f"CERT-{enrollment.id}" + (f"-{sub.id}" if sub else ""),
    }


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def certificate_data(request, course_id):
    """GET /api/courses/courses/<course_id>/certificate/ — JSON for on-page render."""
    enrollment, err = _resolve_eligibility(request.user, course_id)
    if err:
        return err
    return Response(_certificate_payload(enrollment))


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def certificate_pdf(request, course_id):
    """GET /api/courses/courses/<course_id>/certificate/pdf/ — generated on demand."""
    from django.http import HttpResponse

    enrollment, err = _resolve_eligibility(request.user, course_id)
    if err:
        return err
    data = _certificate_payload(enrollment)

    try:
        pdf_bytes = _render_pdf(data)
    except Exception:  # pragma: no cover - depends on reportlab at runtime
        import logging
        logging.getLogger(__name__).exception("certificate PDF generation failed")
        return Response({"error": "Could not generate certificate PDF."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    resp = HttpResponse(pdf_bytes, content_type="application/pdf")
    safe_course = "".join(c for c in data["course_title"] if c.isalnum() or c in " -_").strip() or "course"
    resp["Content-Disposition"] = f'attachment; filename="certificate-{safe_course}.pdf"'
    return resp


def _render_pdf(data: dict) -> bytes:
    """Render a clean, printable landscape certificate with reportlab."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    width, height = landscape(A4)
    c = canvas.Canvas(buf, pagesize=landscape(A4))

    ink = HexColor("#1f2937")
    accent = HexColor("#4f46e5")
    muted = HexColor("#6b7280")

    # Outer + inner border
    c.setStrokeColor(accent)
    c.setLineWidth(3)
    c.rect(12 * mm, 12 * mm, width - 24 * mm, height - 24 * mm)
    c.setStrokeColor(HexColor("#c7d2fe"))
    c.setLineWidth(1)
    c.rect(16 * mm, 16 * mm, width - 32 * mm, height - 32 * mm)

    cx = width / 2

    c.setFillColor(accent)
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(cx, height - 45 * mm, "Certificate of Completion")

    c.setFillColor(muted)
    c.setFont("Helvetica", 13)
    c.drawCentredString(cx, height - 58 * mm, "This certifies that")

    c.setFillColor(ink)
    c.setFont("Helvetica-Bold", 26)
    c.drawCentredString(cx, height - 75 * mm, data["student_name"])

    c.setFillColor(muted)
    c.setFont("Helvetica", 13)
    c.drawCentredString(cx, height - 88 * mm, "has successfully completed")

    c.setFillColor(ink)
    c.setFont("Helvetica-Bold", 18)
    c.drawCentredString(cx, height - 100 * mm, data["course_title"])

    # CLOs attained
    y = height - 116 * mm
    clos = data.get("clos_attained") or []
    if clos:
        c.setFillColor(accent)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(cx, y, "Learning outcomes attained")
        y -= 7 * mm
        c.setFillColor(ink)
        c.setFont("Helvetica", 10)
        for clo in clos[:6]:
            line = f"• {clo['code']}: {clo['text']}"
            if len(line) > 110:
                line = line[:107] + "…"
            c.drawCentredString(cx, y, line)
            y -= 6 * mm

    # Footer: date + verification id
    c.setFillColor(muted)
    c.setFont("Helvetica", 10)
    if data.get("completion_date"):
        c.drawString(24 * mm, 26 * mm, f"Date: {data['completion_date']}")
    c.drawRightString(width - 24 * mm, 26 * mm, f"Verification ID: {data['verification_id']}")
    if data.get("score") is not None:
        c.drawCentredString(cx, 26 * mm, f"Capstone score: {data['score']}%")

    c.showPage()
    c.save()
    return buf.getvalue()
