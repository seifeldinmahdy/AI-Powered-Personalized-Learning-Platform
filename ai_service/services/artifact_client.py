"""
Async HTTP client for the durable artifact store (Batch 10a, stage 2).

This is the AI service's single gateway to the Django artifact backbone
(apps.artifacts). It mirrors the established service-to-service pattern used by
services/mastery.py: ``X-Service-Key`` + ``X-Student-ID`` against
``DJANGO_API_URL``. The store classes (problem set / lab / context) are rewired
onto this client per-domain in later stages; their call sites change minimally.

Design notes
------------
- All methods are ``async`` — these run inside FastAPI request handlers, so a
  blocking sync HTTP call would stall the event loop.
- Every call carries ``X-Student-ID``; Django authorizes ownership server-side
  before returning anything.
- Writes are best-effort from here (failures are logged and surfaced as a falsy
  result) — Django is the transactional source of truth.
- One private ``_request`` centralizes URL/header building + error handling so the
  public methods stay declarative and unit-testable.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


def _base() -> str:
    return os.getenv("DJANGO_API_URL", "http://localhost:8000/api").rstrip("/")


def _headers(student_id: str) -> dict[str, str]:
    return {
        "X-Service-Key": os.getenv("INTERNAL_SERVICE_KEY", ""),
        "X-Student-ID": str(student_id),
    }


async def _request(
    method: str,
    path: str,
    *,
    student_id: str,
    json: Optional[dict] = None,
    params: Optional[dict] = None,
    expected: tuple[int, ...] = (200, 201),
    timeout: float = 15.0,
) -> tuple[bool, Any]:
    """Perform one artifact-store request. Returns ``(ok, data)``.

    ``ok`` is False (and ``data`` None) on any transport error or unexpected
    status — callers treat the store as best-effort and degrade gracefully.
    """
    url = f"{_base()}/artifacts{path}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(
                method, url, json=json, params=params, headers=_headers(student_id),
            )
        if resp.status_code in expected:
            try:
                return True, resp.json()
            except Exception:
                return True, None
        logger.warning("artifact_store %s %s -> %s (student=%s)",
                       method, path, resp.status_code, student_id)
        return False, None
    except Exception as exc:
        logger.warning("artifact_store %s %s failed (student=%s): %s",
                       method, path, student_id, exc)
        return False, None


# ── Placement attempts (events) ──────────────────────────────────────────────

async def post_placement_attempt(student_id: str, course_id: str, *, answers: list,
                                 per_question: list, score: int,
                                 concept_results: dict) -> Optional[dict]:
    ok, data = await _request(
        "POST", "/placement-attempts/", student_id=student_id,
        json={"course_id": course_id, "answers": answers, "per_question": per_question,
              "score": score, "concept_results": concept_results},
    )
    return data if ok else None


async def get_latest_placement(student_id: str, course_id: str) -> Optional[dict]:
    ok, data = await _request(
        "GET", "/placement-attempts/latest/", student_id=student_id,
        params={"course": course_id},
    )
    return data if ok else None


# ── Slides + labs (index + inline content) ───────────────────────────────────

async def upsert_artifact(student_id: str, course_id: str, artifact_type: str, *,
                          plan_version: int, content_json: dict,
                          session_number: Optional[int] = None,
                          lesson_id: Optional[int] = None,
                          generation_index: int = 0, status: str = "generated",
                          score: Optional[float] = None) -> Optional[dict]:
    ok, data = await _request(
        "POST", "/", student_id=student_id,
        json={
            "artifact_type": artifact_type, "course_id": course_id,
            "session_number": session_number, "lesson_id": lesson_id,
            "plan_version": plan_version, "generation_index": generation_index,
            "content_json": content_json, "status": status, "score": score,
        },
    )
    return data if ok else None


async def get_artifact_index(student_id: str, **filters) -> list:
    params = {k: v for k, v in filters.items() if v not in (None, "")}
    ok, data = await _request("GET", "/index/", student_id=student_id, params=params)
    return data if ok and isinstance(data, list) else []


async def get_artifact_content(student_id: str, artifact_id: int) -> Optional[dict]:
    ok, data = await _request("GET", f"/{artifact_id}/content/", student_id=student_id)
    return data if ok else None


async def get_slides_artifact(student_id: str, *, course_id: str, session_number: int,
                              plan_version: int) -> Optional[dict]:
    """Resolve a persisted slides deck for resume (index lookup → content fetch).

    Returns the stored content_json (the SlideGenerateResponse dump), or None.

    ``course_id`` is REQUIRED: a student in two courses can have decks with the
    same (session_number, plan_version), so without it the index could return
    another course's deck (cross-course leak).
    """
    index = await get_artifact_index(
        student_id, type="slides", course=course_id,
        session=session_number, plan_version=plan_version,
    )
    if not index:
        return None
    content = await get_artifact_content(student_id, index[0]["id"])
    return (content or {}).get("content_json") if content else None


# ── Problem sets (index) + attempts (events) ─────────────────────────────────

async def create_problem_set(student_id: str, course_id: str, lesson_id: str, *,
                             plan_version: int, ps_uid: str, content_json: dict,
                             regenerate: bool = False) -> Optional[dict]:
    ok, data = await _request(
        "POST", "/problem-sets/", student_id=student_id,
        json={"course_id": course_id, "session_number": lesson_id, "plan_version": plan_version,
              "ps_uid": ps_uid, "content_json": content_json, "regenerate": regenerate},
        expected=(201,),
    )
    return data if ok else None


async def get_problem_set(student_id: str, ps_uid: str) -> Optional[dict]:
    """Resolve a problem set by uid — the single GET of the submit hot path
    (returns content + hint_tracking + generation_index)."""
    ok, data = await _request("GET", f"/problem-sets/{ps_uid}/", student_id=student_id)
    return data if ok else None


async def get_problem_sets(student_id: str, lesson_id: str) -> list[dict]:
    """Get all problem sets for a student and lesson."""
    ok, data = await _request(
        "GET", "/problem-sets/list/", student_id=student_id,
        params={"session_number": lesson_id},
    )
    return data if ok and isinstance(data, list) else []


async def append_attempt(student_id: str, ps_uid: str, *, question_id: str, code: str,
                         evaluated_rubric: list, hints_used: int,
                         score: int) -> Optional[dict]:
    """Append an attempt — the single POST of the submit hot path."""
    ok, data = await _request(
        "POST", f"/problem-sets/{ps_uid}/attempts/", student_id=student_id,
        json={"question_id": question_id, "code": code, "evaluated_rubric": evaluated_rubric,
              "hints_used": hints_used, "score": score},
        expected=(201,),
    )
    return data if ok else None


async def patch_hint_tracking(student_id: str, ps_uid: str, hint_tracking: dict) -> Optional[dict]:
    ok, data = await _request(
        "PATCH", f"/problem-sets/{ps_uid}/hint-tracking/", student_id=student_id,
        json={"hint_tracking": hint_tracking},
    )
    return data if ok else None


async def get_regen_count(student_id: str, course_id: str, lesson_id: str,
                          plan_version: int) -> Optional[dict]:
    ok, data = await _request(
        "GET", "/problem-sets/regen-count/", student_id=student_id,
        params={"course": course_id, "session_number": lesson_id, "plan_version": plan_version},
    )
    return data if ok else None


async def get_best_score(student_id: str, course_id: str, lesson_id: str,
                         plan_version: Optional[int] = None) -> Optional[float]:
    params = {"course": course_id, "session_number": lesson_id}
    if plan_version is not None:
        params["plan_version"] = plan_version
    ok, data = await _request(
        "GET", "/problem-sets/score/", student_id=student_id, params=params,
    )
    return (data or {}).get("best_score") if ok else None
