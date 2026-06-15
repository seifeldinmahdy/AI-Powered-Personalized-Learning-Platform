"""
Emotion data-governance endpoints (Batch 11b).

- POST /emotion/purge: delete a student's retained RAW emotion from the durable
  session log. Called by Django when consent is withdrawn (service-key auth). The
  derived qualitative profile claim is NOT raw biometric and is unaffected.
- POST /emotion/retention-sweep: consolidate abandoned sessions then TTL-purge
  raw emotion (for cron). Consolidate-before-purge — never costs a session its
  partial profile.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/emotion", tags=["emotion-governance"])


def _require_service_key(x_service_key: str | None) -> None:
    expected = os.getenv("INTERNAL_SERVICE_KEY", "")
    if not expected or x_service_key != expected:
        raise HTTPException(status_code=403, detail="Service key required")


class PurgeRequest(BaseModel):
    student_id: str


@router.post("/purge")
async def purge_student_emotion(req: PurgeRequest, x_service_key: str | None = Header(default=None)):
    """Purge a student's retained raw emotion (consent withdrawal)."""
    _require_service_key(x_service_key)
    from services.session_event_log import get_session_event_log
    from services.emotion_consent import invalidate

    purged = get_session_event_log().purge_student_emotion(req.student_id)
    invalidate(req.student_id)  # drop any cached "granted" decision immediately
    return {"status": "ok", "purged": purged}


@router.post("/retention-sweep")
async def retention_sweep(x_service_key: str | None = Header(default=None)):
    """Consolidate abandoned sessions, then TTL-purge raw emotion (cron)."""
    _require_service_key(x_service_key)
    from services.profiler_service import purge_emotion_retention
    ttl = int(os.getenv("EMOTION_RAW_RETENTION_TTL", str(24 * 3600)))
    return await purge_emotion_retention(ttl)
