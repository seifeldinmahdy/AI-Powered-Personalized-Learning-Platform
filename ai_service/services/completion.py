"""Server-side lesson-completion trigger (AI service → Django).

The problem set is the final, mastery-writing step of a lesson. When the student
finishes it, THIS service tells Django to mark the lesson complete — so completion
(and the XP/streak/progress it drives) is recorded server-side and survives a tab
that closes the instant the problem set ends. The frontend never decides
completion happened; it only signals "the problem set finished".
"""

from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

DJANGO_API_URL = os.getenv("DJANGO_API_URL", "http://localhost:8000/api")


async def post_lesson_complete(
    student_id: str, course_id: str, session_number, *, time_spent_minutes=None
) -> dict:
    """POST the completion trigger to the single Django writer.

    A "lesson" is a pathway SESSION; Django records completion keyed by
    ``(course_id, session_number)`` at ``/progress/complete-session/``
    (see apps.progress.views.internal_complete_session). Idempotent on the Django
    side (the gamified transition fires once per session). Returns the response
    JSON on success, or ``{}`` on any failure — completion is best-effort from
    here, but Django guarantees exactly-once.
    """
    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    body: dict = {"course_id": course_id, "session_number": session_number}
    if time_spent_minutes is not None:
        body["time_spent_minutes"] = time_spent_minutes
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{DJANGO_API_URL}/progress/complete-session/",
                json=body,
                headers={"X-Student-ID": str(student_id), "X-Service-Key": service_key},
            )
            if resp.status_code in (200, 201):
                return resp.json()
            logger.warning(
                "complete-session returned %d for student=%s course=%s session=%s",
                resp.status_code, student_id, course_id, session_number,
            )
    except Exception as e:
        logger.warning(
            "Could not POST session completion for student=%s course=%s session=%s: %s",
            student_id, course_id, session_number, e,
        )
    return {}
