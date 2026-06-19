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


def jwt_verified_student_id(
    authorization: str | None = Header(default=None),
    x_service_key: str | None = Header(default=None, alias="X-Service-Key"),
    x_student_id: str | None = Header(default=None, alias="X-Student-ID"),
) -> str:
    """Verify the student identity for the tutor SSE / live-session endpoints (Track 2).

    Approach B — the browser streams directly to the AI service (SSE uses ``fetch``
    + a reader, not Django), so we verify the student's Django JWT *locally* with
    the shared ``DJANGO_SECRET_KEY`` instead of routing the stream through Django.
    The verified ``user_id`` REPLACES any browser-supplied student id; there is no
    fallback to a request-body id.

    Two accepted callers, in priority order:

    1. Django proxy (``X-Service-Key`` matches ``INTERNAL_SERVICE_KEY``) → trust the
       ``X-Student-ID`` Django set from ``request.user`` — identical to
       :func:`verified_student_id`. Keeps these endpoints usable from server-side.
    2. The browser, presenting ``Authorization: Bearer <access JWT>`` → verified
       here with HS256 + ``DJANGO_SECRET_KEY``; the ``user_id`` claim is the id.

    Any other caller (no service key, no/!invalid token) is rejected fail-closed.
    """
    # Path 1 — internal Django proxy call.
    if x_service_key:
        expected = os.getenv("INTERNAL_SERVICE_KEY", "")
        if not expected or x_service_key != expected:
            raise HTTPException(status_code=403, detail="Invalid internal service key.")
        if not x_student_id:
            raise HTTPException(
                status_code=401,
                detail="X-Student-ID is required (set by Django from the authenticated user).",
            )
        return str(x_student_id)

    # Path 2 — direct browser call carrying the student's Django access token.
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Authorization: Bearer <token> required.",
        )
    token = authorization.split(" ", 1)[1].strip()
    secret = os.getenv("DJANGO_SECRET_KEY", "")
    if not secret:
        # Misconfiguration, not the caller's fault — surface clearly rather than
        # silently trusting an unverifiable token.
        raise HTTPException(
            status_code=500,
            detail="AI service is missing DJANGO_SECRET_KEY; cannot verify tokens.",
        )
    try:
        import jwt  # PyJWT
    except Exception:  # pragma: no cover - dependency guard
        raise HTTPException(
            status_code=500,
            detail="AI service is missing the PyJWT dependency; cannot verify tokens.",
        )
    try:
        payload = jwt.decode(
            token, secret, algorithms=["HS256"], options={"verify_aud": False}
        )
    except Exception:
        # Covers bad signature, expired token, malformed token — all → 401 so the
        # frontend can refresh-and-retry.
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    # SimpleJWT stamps refresh tokens too with the same key; only accept access.
    if payload.get("token_type") not in (None, "access"):
        raise HTTPException(status_code=401, detail="Not an access token.")
    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Token missing user_id claim.")
    return str(user_id)


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
