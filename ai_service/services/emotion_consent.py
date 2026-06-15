"""
Emotion-consent enforcement (Batch 11b) — the AI-side gate.

Before any emotion is fused or written to the durable log, the AI service checks
the student's consent (system of record: Django). FAIL CLOSED: if the lookup
errors, times out, or is ambiguous, treat the student as NOT consented and drop
the emotion. For biometric data, "we're not sure" means "don't capture."

Successful lookups are cached briefly to keep the 25s capture loop off Django's
HTTP path; failures are NOT cached (the next call retries), so a transient error
fails closed for exactly one call rather than locking a consented student out.
"""

from __future__ import annotations

import os
import time

import httpx
import structlog

logger = structlog.get_logger(__name__)

DJANGO_API_URL = os.getenv("DJANGO_API_URL", "http://localhost:8000/api")
_CACHE_TTL_SECONDS = 60
_cache: dict[str, tuple[bool, float]] = {}


async def consent_granted(student_id: str) -> bool:
    """True only if the student has explicitly granted emotion-capture consent.

    Returns False on any uncertainty (no consent, lookup error/timeout, missing
    student) — fail closed.
    """
    sid = str(student_id or "")
    if not sid:
        return False

    cached = _cache.get(sid)
    if cached and cached[1] > time.monotonic():
        return cached[0]

    service_key = os.getenv("INTERNAL_SERVICE_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{DJANGO_API_URL}/progress/emotion-consent/",
                headers={"X-Student-ID": sid, "X-Service-Key": service_key},
            )
        if resp.status_code == 200:
            granted = bool(resp.json().get("granted", False))
            _cache[sid] = (granted, time.monotonic() + _CACHE_TTL_SECONDS)  # cache successes only
            return granted
        logger.warning("emotion_consent_lookup_status", student_id=sid, status=resp.status_code)
    except Exception as exc:
        logger.warning("emotion_consent_lookup_failed", student_id=sid, error=str(exc))
    # Fail closed on any non-200 / error — do NOT cache, so recovery is immediate.
    return False


def invalidate(student_id: str) -> None:
    """Drop a cached consent decision (e.g. right after withdrawal)."""
    _cache.pop(str(student_id or ""), None)
