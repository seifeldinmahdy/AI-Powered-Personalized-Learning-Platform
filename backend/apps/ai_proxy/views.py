"""Authenticated front door for per-student AI-service endpoints (Track 1).

Every view here is the JWT boundary: the student authenticates to Django, and
Django — and ONLY Django — tells the AI service who the caller is, via the
``X-Student-ID`` header derived from ``request.user``. The AI-service endpoints
are service-key gated (see ``ai_service/routers/_auth.py``), so the browser can
no longer reach them directly with a chosen ``student_id``.

Hard rule (the Track 1 pass criterion): the student identity sent downstream is
ALWAYS ``request.user.id``. We never read ``student_id`` from the request body,
query, or URL and forward it — any such value from the browser is ignored.
"""

from __future__ import annotations

import os

import requests
from django.conf import settings
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response


def _ai_url() -> str:
    return (
        getattr(settings, "AI_SERVICE_URL", None)
        or os.getenv("AI_SERVICE_URL", "http://localhost:8001")
    ).rstrip("/")


def _headers(request) -> dict:
    """Service key + the VERIFIED student id (from the authenticated user)."""
    return {
        "X-Service-Key": os.getenv("INTERNAL_SERVICE_KEY", ""),
        "X-Student-ID": str(request.user.id),
    }


def _relay(resp: requests.Response) -> Response:
    """Pass the AI response through, preserving status; JSON when possible."""
    try:
        return Response(resp.json(), status=resp.status_code)
    except ValueError:
        return Response({"detail": resp.text}, status=resp.status_code)


def _forward(request, method: str, path: str, *, params=None, json=None,
             timeout: int = 60) -> Response:
    """Forward to the AI service with the verified identity header."""
    url = f"{_ai_url()}{path}"
    try:
        resp = requests.request(
            method, url, params=params, json=json,
            headers=_headers(request), timeout=timeout,
        )
        return _relay(resp)
    except requests.exceptions.ConnectionError:
        return Response({"error": "AI service offline"},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception as exc:  # noqa: BLE001 - surface as bad gateway
        return Response({"error": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)


def _body_without_student_id(request) -> dict:
    """The request body with any browser-supplied ``student_id`` stripped."""
    data = request.data if isinstance(request.data, dict) else {}
    return {k: v for k, v in data.items() if k != "student_id"}


# ── Group A: student-context ─────────────────────────────────────


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def student_context(request, course_id: str):
    """GET the authenticated student's context for a course."""
    return _forward(request, "GET", f"/student-context/{course_id}")


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def update_performance(request, course_id: str):
    """POST an in-session performance update for the authenticated student."""
    return _forward(
        request, "POST", f"/student-context/{course_id}/update-performance",
        json=_body_without_student_id(request),
    )


# ── Group C: profiler (closes the profile_audit store's surface) ─


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def profiler_run_session(request):
    """POST session-end profiling for the authenticated student."""
    return _forward(
        request, "POST", "/profiler/run-session",
        json=_body_without_student_id(request), timeout=120,
    )


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def profiler_fuse_emotions(request):
    """POST FER/SER fusion for the authenticated student (live session)."""
    return _forward(
        request, "POST", "/profiler/fuse-emotions",
        json=_body_without_student_id(request), timeout=30,
    )


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def profiler_audit_log(request):
    """GET the authenticated student's own profiling-claim audit log."""
    limit = request.query_params.get("limit", "50")
    return _forward(request, "GET", "/profiler/audit-log", params={"limit": limit})


# ── Group B: pathway reads + slides ──────────────────────────────


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def pathway_current(request, course_id: str):
    """GET the authenticated student's current pathway plan for a course."""
    return _forward(request, "GET", "/pathway/current",
                    params={"course_id": course_id})


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def pathway_mine(request):
    """GET all of the authenticated student's cached pathway plans."""
    return _forward(request, "GET", "/pathway/mine")


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def pathway_provenance(request, course_id: str):
    """GET per-session concept/CLO provenance for the authenticated student."""
    return _forward(request, "GET", f"/pathway/{course_id}/provenance")


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def pathway_session_chunks(request):
    """POST: fetch the raw chunks for a session of the student's cached plan."""
    return _forward(request, "POST", "/pathway/session-chunks",
                    json=_body_without_student_id(request), timeout=90)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def slides_generate(request):
    """POST: generate a slide deck for the authenticated student."""
    return _forward(request, "POST", "/slides/generate",
                    json=_body_without_student_id(request), timeout=300)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def slides_persisted(request, course_id: str):
    """GET a previously persisted deck for the authenticated student (resume)."""
    params = {"course_id": course_id}
    for k in ("session_number", "plan_version"):
        v = request.query_params.get(k)
        if v is not None:
            params[k] = v
    return _forward(request, "GET", "/slides/persisted", params=params)


# ── In-session MCQ knowledge checkpoints ─────────────────────────


def _body_with_verified_student_id(request) -> dict:
    """Body with the verified student id injected at top level AND inside any
    nested ``context`` block — the MCQ session endpoint requires the two to match
    and reads identity from the body (it is not header-gated)."""
    sid = str(request.user.id)
    body = {**_body_without_student_id(request), "student_id": sid}
    ctx = body.get("context")
    if isinstance(ctx, dict):
        body["context"] = {**ctx, "student_id": sid}
    return body


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def assessments_session(request):
    """POST: generate an in-session MCQ knowledge checkpoint for the student.

    Generation runs the local QG/DG models per question, so this can be slow —
    a generous timeout keeps the request from being severed mid-generation.
    """
    return _forward(request, "POST", "/assessments/session",
                    json=_body_with_verified_student_id(request), timeout=300)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def assessments_submit(request):
    """POST: score an in-session MCQ checkpoint and record concept mastery."""
    return _forward(request, "POST", "/assessments/submit",
                    json=_body_with_verified_student_id(request), timeout=60)
