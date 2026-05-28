"""
Profiler Router — profile rewriting and emotion fusion endpoints.

Integrates with SharedSessionStore: when ``session_id`` is provided,
``slide_title`` and ``subtopic`` are auto-read from the shared store
(removing the need for the frontend to pass them manually), and after
fusion the ``fused_emotion`` and ``confidence`` are written back.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from services.profiler_service import update_profile, fuse_emotions
from services.session_store import get_session_store
from schemas.student_context import UnifiedStudentContext
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
    intent_classification: Optional[str] = None
    question_transcript: Optional[str] = None
    dr_nova_response_summary: Optional[str] = None




class UpdateProfileRequest(BaseModel):
    student_id: int = Field(..., description="Student user ID")
    lesson_title: str = Field(default="", description="Lesson title just completed")
    session_id: Optional[str] = Field(default=None, description="Backend session ID to read logs from")
    session_log: List[EmotionEventInput] = Field(
        default_factory=list, description="Fallback EmotionEvent array if session_id is not provided"
    )
    existing_profile_summary: str = Field(
        default="", description="Current profile_summary from DB (empty if first session)"
    )
    existing_profile_data: Dict = Field(
        default_factory=dict, description="Current profile_data from DB (empty if first session)"
    )
    student_context: Optional[UnifiedStudentContext] = None


class FuseEmotionsRequest(BaseModel):
    fer_emotion: str = Field(..., description="FER emotion label")
    fer_confidence: float = Field(default=0.0, description="FER confidence 0-1")
    ser_emotion: str = Field(..., description="SER emotion label")
    ser_confidence: float = Field(default=0.0, description="SER confidence 0-1")
    slide_index: int = Field(default=0)
    slide_title: str = Field(default="")
    subtopic: str = Field(default="")
    session_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional session ID.  When provided and slide_title / subtopic "
            "are empty, values are auto-read from SharedSessionStore.  "
            "After fusion, fused_emotion, confidence, and the emotion signal are written back."
        ),
    )


# ─── Endpoints ───────────────────────────────────────────────────


@router.post("/update")
async def update(request: UpdateProfileRequest):
    """
    Rewrite the student's persistent learning profile.

    Takes the existing profile + new session data (optionally pulled directly
    from SharedSessionStore via session_id) and returns a synthesized
    new profile (profile_summary + profile_data) to be saved to Django.
    """
    try:
        log_dicts = [e.model_dump() for e in request.session_log]
        
        # Override with backend-tracked session state if session_id is provided
        if request.session_id:
            from services.session_store import get_session_store
            store = get_session_store()
            session_data = store.get_session(request.session_id)
            if session_data:
                # Use emotion signals as the base interaction log
                backend_logs = list(session_data.live.emotion_signals)
                
                # Merge tutor events into the log
                for event in session_data.live.tutor_events:
                    backend_logs.append({
                        "timestamp": event.get("timestamp", ""),
                        "slide_index": event.get("slide_index", 0),
                        "event_type": "tutor_" + event.get("event_type", "event"),
                        "dr_nova_response_summary": event.get("text", "")
                    })
                
                if backend_logs:
                    log_dicts = backend_logs
                    logger.info("Profiler /update: Pulled %d interaction logs from SharedSessionStore for session %s", len(log_dicts), request.session_id)

        result = await update_profile(
            student_id=request.student_id,
            lesson_title=request.lesson_title,
            session_log=log_dicts,
            existing_profile_summary=request.existing_profile_summary,
            existing_profile_data=request.existing_profile_data,
            student_context=request.student_context,
        )
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Profile update error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fuse-emotions")
async def fuse(request: FuseEmotionsRequest):
    """
    Resolve conflicting FER and SER emotions using LLM arbitration.

    When ``session_id`` is provided:
    - ``slide_title`` and ``subtopic`` are auto-populated from the store
      if they were not sent in the request body.
    - After fusion, ``fused_emotion`` and ``confidence`` are written back
      to the store so other subsystems can read the latest emotion state.

    Returns { fused_emotion, reasoning }.
    """
    try:
        slide_title = request.slide_title
        subtopic = request.subtopic
        slide_index = request.slide_index

        # ── Auto-read from SharedSessionStore ───────────────────
        if request.session_id:
            store = get_session_store()
            session_data = store.get_session(request.session_id)
            if session_data:
                if not slide_title:
                    slide_title = session_data.live.current_slide_title
                if not subtopic:
                    subtopic = session_data.live.current_subtopic
                if slide_index == 0:
                    slide_index = session_data.live.current_slide_index
                logger.info(
                    "Profiler /fuse-emotions: auto-populated slide_title=%r, "
                    "subtopic=%r from SharedSessionStore for session %s",
                    slide_title,
                    subtopic,
                    request.session_id,
                )

        result = await fuse_emotions(
            fer_emotion=request.fer_emotion,
            fer_confidence=request.fer_confidence,
            ser_emotion=request.ser_emotion,
            ser_confidence=request.ser_confidence,
            slide_index=slide_index,
            slide_title=slide_title,
            subtopic=subtopic,
        )

        # ── Write fusion result back to SharedSessionStore ──────
        if request.session_id:
            try:
                store = get_session_store()
                fused = result.get("fused_emotion", "")
                conf = max(request.fer_confidence, request.ser_confidence)
                
                session_data = store.get_session(request.session_id)
                if session_data:
                    signals = list(session_data.live.emotion_signals)
                    
                    import datetime
                    new_signal = {
                        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
                        "slide_index": slide_index,
                        "slide_title": slide_title,
                        "subtopic": subtopic,
                        "fer_emotion": request.fer_emotion,
                        "fer_confidence": request.fer_confidence,
                        "ser_emotion": request.ser_emotion,
                        "ser_confidence": request.ser_confidence,
                        "fused_emotion": fused,
                        "event_type": "passive"
                    }
                    signals.append(new_signal)
                    
                    store.update_session(
                        request.session_id,
                        live_kwargs={
                            "fused_emotion": fused,
                            "fused_emotion_confidence": conf,
                            "emotion_signals": signals
                        }
                    )
                    logger.info(
                        "Profiler /fuse-emotions: wrote fused_emotion=%r, "
                        "confidence=%.2f back to SharedSessionStore for session %s",
                        fused,
                        conf,
                        request.session_id,
                    )
            except Exception as exc:
                logger.warning(
                    "Failed to write fusion result to SharedSessionStore: %s",
                    exc,
                )

        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Emotion fusion error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/evidence-ledger/{student_id}")
async def get_evidence_ledger(student_id: str):
    """
    Return the full evidence ledger for a student.
    For debugging and auditing only — shows why the profiler
    concluded what it did. Intended for instructor/admin use.
    """
    try:
        from services.evidence_ledger_store import get_evidence_ledger_store
        ledger_store = get_evidence_ledger_store()
        ledger = ledger_store.load(student_id)
        return {"success": True, "ledger": ledger}
    except Exception as e:
        logger.error(f"Evidence ledger fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

