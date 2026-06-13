"""CLO (Course Learning Outcome) suggestion router."""

from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException

from schemas.clos import CLOSuggestRequest, CLOSuggestResponse
from services.clo_service import suggest_clos

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clos", tags=["clos"])


@router.post("/suggest", response_model=CLOSuggestResponse)
async def suggest_course_clos(request: CLOSuggestRequest):
    """Generate draft CLOs for a course given its outline and available concepts."""
    try:
        return await suggest_clos(request)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error("CLO suggestion failed: %s", e)
        raise HTTPException(status_code=500, detail=f"CLO suggestion failed: {e}")
