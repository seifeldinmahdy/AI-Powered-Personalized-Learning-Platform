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
from services.profiler_service import run_session_profiler, fuse_emotions
from services.session_store import get_session_store
from schemas.student_context import UnifiedStudentContext
import collections
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




class RunSessionRequest(BaseModel):
    """Trigger server-side session profiling from the DURABLE log.

    No profile is read or merged by the caller — the server consolidates the
    durable session-event log and applies claims via the single writer. The
    frontend just fires this at session end (fire-and-forget).
    """
    session_id: str = Field(..., description="Backend session ID (durable-log key)")
    student_id: int = Field(..., description="Student user ID")
    lesson_title: str = Field(default="", description="Lesson title just completed")


class FuseEmotionsRequest(BaseModel):
    # Required for consent enforcement + attributable retention (Batch 11b).
    student_id: str = Field(default="", description="Student user ID (consent + attribution)")
    course_id: str = Field(default="", description="Course ID (attribution)")
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


# ─── Helpers ─────────────────────────────────────────────────────


def _group_session_log_by_slide(session_data) -> list[dict]:
    """Group emotion signals and tutor events by slide_index into one entry per slide."""
    slides: dict[int, dict] = {}

    def _init_slide(idx: int) -> dict:
        return {
            "slide_index": idx,
            "slide_title": "",
            "slide_content": "",
            "all_emotions": [],
            "student_questions": [],
            "tutor_responses": [],
            "notable_events": [],
        }

    # Pass 1: emotion signals
    for signal in session_data.live.emotion_signals:
        idx = signal.get("slide_index", 0)
        if idx not in slides:
            slides[idx] = _init_slide(idx)
        entry = slides[idx]

        # Fill slide_title / slide_content if missing from this entry
        if not entry["slide_title"] and signal.get("slide_title"):
            entry["slide_title"] = signal["slide_title"]
        if not entry["slide_content"] and signal.get("slide_content"):
            entry["slide_content"] = signal["slide_content"]

        fused = signal.get("fused_emotion")
        if fused:
            entry["all_emotions"].append(fused)

        event_type = signal.get("event_type", "")
        qt = signal.get("question_transcript", "")
        if "question" in event_type or qt:
            if qt:
                entry["student_questions"].append(qt)

    # Pass 2: tutor events
    for event in session_data.live.tutor_events:
        idx = event.get("slide_index", 0)
        if idx not in slides:
            slides[idx] = _init_slide(idx)
        entry = slides[idx]

        if not entry["slide_title"] and event.get("slide_title"):
            entry["slide_title"] = event["slide_title"]
        if not entry["slide_content"] and event.get("slide_content"):
            entry["slide_content"] = event["slide_content"]

        text = event.get("dr_nova_response_summary") or event.get("text", "")
        if text:
            entry["tutor_responses"].append(text)

        event_type = event.get("event_type", "")
        if event_type and event_type != "passive":
            entry["notable_events"].append(event_type)

    # Compute derived fields
    for idx, entry in slides.items():
        if entry["all_emotions"]:
            counter = collections.Counter(entry["all_emotions"])
            entry["dominant_emotion"] = counter.most_common(1)[0][0]
        else:
            entry["dominant_emotion"] = "neutral"

        entry["time_spent_seconds"] = session_data.live.time_spent_per_slide.get(
            str(idx), 0
        )

    # Filter out slides with no meaningful signal
    result = [
        entry for entry in slides.values()
        if entry["all_emotions"] or entry["student_questions"] or entry["tutor_responses"]
    ]

    # Sort by slide_index
    result.sort(key=lambda e: e["slide_index"])

    # Fallback: if nothing meaningful, return raw emotion signals
    if not result:
        return list(session_data.live.emotion_signals)

    return result


# ─── Endpoints ───────────────────────────────────────────────────


@router.post("/run-session")
async def run_session(request: RunSessionRequest):
    """Server-side session profiling from the DURABLE log (no client merge).

    Consolidates the session's durable event log into claims and applies them via
    the single writer. Idempotent: consumed events aren't re-applied, so the
    explicit end-call and the sweeper can't double-apply. Works after an
    AI-service restart because it reads the durable log, not memory.
    """
    try:
        result = await run_session_profiler(
            session_id=request.session_id,
            student_id=str(request.student_id),
            lesson_title=request.lesson_title,
        )
        return {"success": True, **result}
    except Exception as e:
        logger.error(f"Session profiler error: {e}")
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
        # ── Consent gate (Batch 11b) — FAIL CLOSED ──────────────
        # No emotion is fused, persisted, or used unless the student has
        # explicitly consented. Any uncertainty (no consent, lookup error/
        # timeout) drops the emotion and treats it as the existing "uncertain =
        # missing" state. Nothing downstream depends on emotion existing.
        from services.emotion_consent import consent_granted
        if not await consent_granted(request.student_id):
            logger.info(
                "Profiler /fuse-emotions: no consent (or unavailable) for student=%r — "
                "emotion dropped, not persisted", request.student_id,
            )
            return {"fused_emotion": "uncertain",
                    "reasoning": "Emotion capture not consented — signal dropped (treated as missing)."}

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
                        "slide_content": session_data.live.current_slide_content or "",
                        "subtopic": subtopic,
                        "fer_emotion": request.fer_emotion,
                        "fer_confidence": request.fer_confidence,
                        "ser_emotion": request.ser_emotion,
                        "ser_confidence": request.ser_confidence,
                        "fused_emotion": fused,
                        "event_type": "passive",
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
                    # Also stream to the DURABLE log so the signal survives an
                    # abandoned session / AI-service restart.
                    try:
                        from services.session_event_log import get_session_event_log
                        get_session_event_log().append(
                            request.session_id, "emotion", new_signal,
                            student_id=request.student_id, course_id=request.course_id,
                        )
                    except Exception:
                        pass
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


@router.get("/audit-log/{student_id}")
async def get_audit_log_endpoint(student_id: str, limit: int = 50):
    try:
        from services.profiler_service import get_audit_log
        entries = get_audit_log(student_id, limit=limit)
        return {"success": True, "audit_log": entries}
    except Exception as e:
        logger.error(f"Audit log fetch error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
