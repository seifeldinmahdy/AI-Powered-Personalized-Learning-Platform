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


async def post_lesson_complete(student_id: str, lesson_id: str) -> dict:
    """POST the completion trigger to the single Django writer.

    Idempotent on the Django side (the gamified transition fires once per
    lesson). Returns the response JSON on success, or ``{}`` on any failure —
    completion is best-effort from here, but Django guarantees exactly-once.
    """
    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{DJANGO_API_URL}/progress/complete-lesson/",
                json={"lesson_id": lesson_id},
                headers={"X-Student-ID": str(student_id), "X-Service-Key": service_key},
            )
            if resp.status_code in (200, 201):
                return resp.json()
            logger.warning(
                "complete-lesson returned %d for student=%s lesson=%s",
                resp.status_code, student_id, lesson_id,
            )
    except Exception as e:
        logger.warning(
            "Could not POST lesson completion for student=%s lesson=%s: %s",
            student_id, lesson_id, e,
        )
    return {}
