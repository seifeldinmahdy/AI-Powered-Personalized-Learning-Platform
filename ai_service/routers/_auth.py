"""Verified-identity dependency for per-student AI-service endpoints (Track 1).

Approach A: the browser no longer calls these endpoints directly. Django is the
single authenticated front door — it verifies the student's JWT, then calls the
AI service with:

    X-Service-Key: <INTERNAL_SERVICE_KEY>   (proves the caller is Django)
    X-Student-ID:  <request.user.id>        (the verified identity)

Endpoints inject ``student_id = Depends(verified_student_id)`` and read the
student identity ONLY from here. The previous path/query/body ``student_id`` is
removed entirely — the verified id REPLACES it, it does not sit beside it. There
is deliberately no fallback to a client-supplied id: a missing/invalid service
key is a hard 403, never a downgrade to trusting the request.
"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException


def verified_student_id(
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
    x_student_id: str | None = Header(default=None, alias="X-Student-ID"),
) -> str:
    """Return the student id from the verified service header, or reject.

    Rejects any caller that does not present the internal service key (i.e. the
    browser), and any service call that omits the student id. The returned value
    is the ONLY trusted source of student identity for the endpoint.
    """
    expected = os.getenv("INTERNAL_SERVICE_KEY", "")
    if not expected or x_service_key != expected:
        raise HTTPException(
            status_code=403,
            detail="This endpoint is internal-only; call it through Django.",
        )
    if not x_student_id:
        raise HTTPException(
            status_code=401,
            detail="X-Student-ID is required (set by Django from the authenticated user).",
        )
    return str(x_student_id)
