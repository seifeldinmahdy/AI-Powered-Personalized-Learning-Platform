"""
Profiler Router — profile rewriting and emotion fusion endpoints.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from services.profiler_service import update_profile, fuse_emotions
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/profiler",
    tags=["Profiler"],
)


# ─── Request schemas ─────────────────────────────────────────────


class EmotionEventInput(BaseModel):
    timestamp: str
    slide_index: int = 0
    slide_title: Optional[str] = None
    subtopic: Optional[str] = None
    fer_emotion: Optional[str] = None
    fer_confidence: Optional[float] = None
    ser_emotion: Optional[str] = None
    ser_confidence: Optional[float] = None
    fused_emotion: Optional[str] = None
    event_type: str = "passive"
    question_transcript: Optional[str] = None
    dr_nova_response_summary: Optional[str] = None




class UpdateProfileRequest(BaseModel):
    student_id: int = Field(..., description="Student user ID")
    lesson_title: str = Field(default="", description="Lesson title just completed")
    session_log: List[EmotionEventInput] = Field(
        default_factory=list, description="Full EmotionEvent array from the session"
    )
    existing_profile_summary: str = Field(
        default="", description="Current profile_summary from DB (empty if first session)"
    )
    existing_profile_data: Dict = Field(
        default_factory=dict, description="Current profile_data from DB (empty if first session)"
    )


class FuseEmotionsRequest(BaseModel):
    fer_emotion: str = Field(..., description="FER emotion label")
    fer_confidence: float = Field(default=0.0, description="FER confidence 0-1")
    ser_emotion: str = Field(..., description="SER emotion label")
    ser_confidence: float = Field(default=0.0, description="SER confidence 0-1")
    slide_index: int = Field(default=0)
    slide_title: str = Field(default="")
    subtopic: str = Field(default="")


# ─── Endpoints ───────────────────────────────────────────────────




@router.post("/update")
async def update(request: UpdateProfileRequest):
    """
    Rewrite the student's persistent learning profile.

    Takes the existing profile + new session data and returns a synthesized
    new profile (profile_summary + profile_data) to be saved to Django.
    """
    try:
        log_dicts = [e.model_dump() for e in request.session_log]
        result = await update_profile(
            student_id=request.student_id,
            lesson_title=request.lesson_title,
            session_log=log_dicts,
            existing_profile_summary=request.existing_profile_summary,
            existing_profile_data=request.existing_profile_data,
        )
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Profile update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fuse-emotions")
async def fuse(request: FuseEmotionsRequest):
    """
    Resolve conflicting FER and SER emotions using LLM arbitration.

    Returns { fused_emotion, reasoning }.
    """
    try:
        result = await fuse_emotions(
            fer_emotion=request.fer_emotion,
            fer_confidence=request.fer_confidence,
            ser_emotion=request.ser_emotion,
            ser_confidence=request.ser_confidence,
            slide_index=request.slide_index,
            slide_title=request.slide_title,
            subtopic=request.subtopic,
        )
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Emotion fusion error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
