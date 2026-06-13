"""Post-course survey summarization router."""

from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException

from schemas.surveys import SurveySummarizeRequest, SurveySummaryResult
from services.survey_summary_service import summarize_survey

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/surveys", tags=["surveys"])


@router.post("/summarize", response_model=SurveySummaryResult)
async def summarize_course_survey(request: SurveySummarizeRequest):
    """Aggregate and summarize post-course survey responses using the strong LLM."""
    try:
        return await summarize_survey(request)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error("Survey summarization failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Survey summarization failed: {e}")
