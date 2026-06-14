"""Internal admin pathway operations (service-key gated).

Students cannot reach these — the regeneration permission boundary is enforced
server-side. The Django admin-only endpoint proxies here with the service key.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pathway-admin", tags=["Pathway Admin"])


def _require_service_key(x_service_key: Optional[str]) -> None:
    expected = os.getenv("INTERNAL_SERVICE_KEY", "")
    if not expected or x_service_key != expected:
        raise HTTPException(status_code=403, detail="Service key required.")


class RegenerateRequest(BaseModel):
    student_id: str
    course_id: str


@router.post("/regenerate")
async def admin_regenerate(
    req: RegenerateRequest,
    x_service_key: Optional[str] = Header(default=None),
):
    """Force a new plan version for a student from their stored context (admin)."""
    _require_service_key(x_service_key)
    from services.pathway_trigger import regenerate_for_student

    ok, detail = await asyncio.to_thread(
        regenerate_for_student, req.student_id, req.course_id,
    )
    if not ok:
        raise HTTPException(status_code=422, detail=detail)
    return {"success": True, "detail": detail}
