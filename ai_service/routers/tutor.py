"""
Tutor Router — AI tutoring session endpoints.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from services.tutor_service import (
    create_session,
    get_session,
    generate_lecture_chunk,
    answer_question,
    repeat_lecture_chunk,
    stop_session,
    get_session_state,
    check_relevance,
)
from services.tts_service import get_tts_service
import base64
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tutor",
    tags=["Tutor"],
)


# ─── Request / Response schemas ──────────────────────────────────


class TopicInput(BaseModel):
    name: str = Field(..., description="Topic name")
    subtopics: List[str] = Field(default_factory=list, description="Ordered subtopics")


class StartSessionRequest(BaseModel):
    topics: List[TopicInput] = Field(..., min_length=1, description="List of topics to cover")
    session_id: Optional[str] = Field(default=None, description="Optional custom session ID")
    voice: str = Field(default="en-US-GuyNeural", description="TTS voice name")
    student_profile_summary: Optional[str] = Field(default=None, description="Student's learning profile summary for personalization")
    student_profile_data: Optional[dict] = Field(default=None, description="Profiler engagement patterns and recommended approaches for personalization")
    student_id: Optional[str] = Field(default=None, description="Student ID for automatic profile fetch if profile data not provided")


class ContinueRequest(BaseModel):
    session_id: str = Field(..., description="Session ID")
    include_audio: bool = Field(default=True, description="Include TTS audio in response")
    student_emotion: Optional[str] = Field(default=None, description="Current student emotional state for tone adaptation")


class AskQuestionRequest(BaseModel):
    session_id: str = Field(..., description="Session ID")
    question: str = Field(..., min_length=1, description="Student's question")
    include_audio: bool = Field(default=True, description="Include TTS audio in response")
    student_emotion: Optional[str] = Field(default=None, description="Student's emotional state during the question")


class StopRequest(BaseModel):
    session_id: str = Field(..., description="Session ID")


# ─── Endpoints ───────────────────────────────────────────────────


@router.post("/start")
async def start_session(request: StartSessionRequest):
    """
    Start a new AI tutoring session.

    Provide a list of topics (with optional subtopics). The tutor will
    lecture through them in order, recursively summarizing context.
    """
    try:
        topics = [t.model_dump() for t in request.topics]
        session = create_session(
            topics=topics,
            voice=request.voice,
            session_id=request.session_id,
            student_profile_summary=request.student_profile_summary,
            student_profile_data=request.student_profile_data,
            student_id=request.student_id,
        )
        return {
            "success": True,
            "session_id": session.session_id,
            "topics_count": len(session.topics),
            "total_items": session.total_items,
            "status": session.status,
            "voice": session.voice,
        }
    except Exception as e:
        logger.error(f"Failed to start session: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/continue")
async def continue_session(request: ContinueRequest):
    """
    Generate the next lecture chunk.

    Call this in a loop — the tutor will advance through topics/subtopics
    and return is_finished=true when the lecture is complete.
    Each call triggers:
    1. LLM generates lecture text for the current subtopic
    2. Running summary is recursively compressed
    3. Topic pointer advances to the next item
    4. Optionally, TTS audio is generated and returned as base64
    """
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        result = await generate_lecture_chunk(request.session_id, student_emotion=request.student_emotion)

        # Generate TTS audio if requested and there's text
        audio_base64 = None
        blendshapes = None
        if request.include_audio and result["text"]:
            audio_base64 = await _synthesize_audio(
                result["text"], 
                session.voice, 
                request.student_emotion,
                request.session_id
            )
            # Generate A2F blendshapes (falls back to None if unavailable)
            blendshapes = await _generate_blendshapes(
                result["text"], session.voice,
                request.student_emotion, request.session_id,
            )

        return {
            "success": True,
            "session_id": request.session_id,
            "text": result["text"],
            "audio_base64": audio_base64,
            "blendshapes": blendshapes,
            "topic": result["topic"],
            "subtopic": result["subtopic"],
            "progress": result["progress"],
            "is_finished": result["is_finished"],
            "status": result["status"],
            "inference_time": result.get("inference_time"),
        }
    except Exception as e:
        logger.error(f"Continue session error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ask")
async def ask(request: AskQuestionRequest):
    """
    Ask a question mid-lecture.

    The tutor pauses the lecture flow, answers the question using
    the full accumulated context, then resumes.
    """
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        result = await answer_question(request.session_id, request.question, student_emotion=request.student_emotion)

        audio_base64 = None
        blendshapes = None
        if request.include_audio and result["answer"]:
            audio_base64 = await _synthesize_audio(
                result["answer"], 
                session.voice, 
                request.student_emotion,
                request.session_id
            )
            # Generate A2F blendshapes (falls back to None if unavailable)
            blendshapes = await _generate_blendshapes(
                result["answer"], session.voice,
                request.student_emotion, request.session_id,
            )

        return {
            "success": True,
            "session_id": request.session_id,
            "answer": result["answer"],
            "audio_base64": audio_base64,
            "blendshapes": blendshapes,
            "topic": result["topic"],
            "subtopic": result["subtopic"],
            "progress": result["progress"],
            "is_finished": result["is_finished"],
            "status": result["status"],
            "inference_time": result.get("inference_time"),
        }
    except Exception as e:
        logger.error(f"Ask question error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def session_status(session_id: str):
    """Get the current state of a tutoring session."""
    state = get_session_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"success": True, **state}


class RelevanceRequest(BaseModel):
    question: str
    lesson_title: str


@router.post("/relevance")
async def relevance_check(request: RelevanceRequest):
    """Check if a student's question is relevant to the current lesson."""
    try:
        is_relevant = await check_relevance(request.question, request.lesson_title)
        return {"relevant": is_relevant}
    except Exception as e:
        logger.error(f"Relevance check error: {e}")
        return {"relevant": True}  # fail open


@router.post("/stop")
async def stop(request: StopRequest):
    """End a tutoring session early."""
    success = stop_session(request.session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"success": True, "session_id": request.session_id, "status": "finished"}


class SetPaceRequest(BaseModel):
    session_id: str = Field(..., description="Session ID")
    pace: str = Field(..., description="Requested pace ('slow', 'normal', 'fast')")


@router.post("/set-pace")
async def set_pace(request: SetPaceRequest):
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    if request.pace == "slow":
        session.pace_modifier -= 10
    elif request.pace == "fast":
        session.pace_modifier += 10
    elif request.pace == "normal":
        session.pace_modifier = 0
        
    return {"success": True, "pace": request.pace, "pace_modifier": session.pace_modifier}


class TutorSynthesizeAudioRequest(BaseModel):
    session_id: str = Field(..., description="Session ID")
    text: str = Field(..., description="Text to synthesize")
    student_emotion: Optional[str] = Field(default=None, description="Current student emotional state")


@router.post("/synthesize-audio")
async def tutor_synthesize_audio(request: TutorSynthesizeAudioRequest):
    """Synthesize audio directly utilizing the session's current context and pace_modifier."""
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    try:
        audio_base64 = await _synthesize_audio(
            request.text, 
            session.voice, 
            request.student_emotion,
            request.session_id
        )
        return {"success": True, "audio_base64": audio_base64}
    except Exception as e:
        logger.error(f"Tutor synthesize audio error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Repeat / Clarification ───────────────────────────────────────────

# Extra TTS rate applied in verbatim repeat mode to make delivery slower/clearer.
_VERBATIM_REPEAT_RATE_DELTA = -20  # percentage points


class RepeatRequest(BaseModel):
    session_id: str = Field(..., description="Session ID")
    mode: str = Field(
        default="rephrase",
        description=(
            "'verbatim' — re-deliver the exact last chunk at a slower rate. "
            "'rephrase' — re-generate a simpler explanation for the same subtopic."
        ),
    )
    include_audio: bool = Field(default=True, description="Include TTS audio in response")
    student_emotion: Optional[str] = Field(
        default=None, description="Current student emotional state"
    )


@router.post("/repeat")
async def repeat(request: RepeatRequest):
    """
    Handle a ``Repeat/clarification`` intent.

    When the Intent Classifier returns ``Repeat/clarification``, the frontend
    should call this endpoint instead of replaying the last audio blob.

    - ``mode="verbatim"`` — returns the exact last lecture text re-synthesised
      with a slower TTS rate (−20 pp) for clearer delivery.
    - ``mode="rephrase"`` (default) — calls the LLM again for the same
      subtopic with a simplification directive and returns fresh audio.

    The topic pointer is **not** advanced in either mode.
    """
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if request.mode not in ("verbatim", "rephrase"):
        raise HTTPException(
            status_code=400,
            detail="'mode' must be 'verbatim' or 'rephrase'.",
        )

    try:
        result = await repeat_lecture_chunk(request.session_id, mode=request.mode)
    except ValueError as exc:
        # Nothing to repeat yet, or session missing.
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Repeat endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    audio_base64 = None
    if request.include_audio and result["text"]:
        # For verbatim mode apply a slower rate on top of existing modifiers.
        if request.mode == "verbatim":
            # Temporarily shift pace_modifier to bake in the -20pp delta.
            original_pace = session.pace_modifier
            session.pace_modifier = original_pace + _VERBATIM_REPEAT_RATE_DELTA
            try:
                audio_base64 = await _synthesize_audio(
                    result["text"],
                    session.voice,
                    request.student_emotion,
                    request.session_id,
                )
            finally:
                session.pace_modifier = original_pace
        else:
            audio_base64 = await _synthesize_audio(
                result["text"],
                session.voice,
                request.student_emotion,
                request.session_id,
            )

    return {
        "success": True,
        "session_id": request.session_id,
        "text": result["text"],
        "audio_base64": audio_base64,
        "topic": result["topic"],
        "subtopic": result["subtopic"],
        "mode": result["mode"],
        "progress": result["progress"],
        "status": result["status"],
        "inference_time": result.get("inference_time"),
    }


@router.get("/health")
async def tutor_health():
    """Check if the tutor service is ready (Ollama Cloud reachable)."""
    from services.tutor_service import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_API_KEY
    import httpx
    try:
        headers = {}
        if OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags", headers=headers)
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            has_model = any(OLLAMA_MODEL in m for m in models)
        return {
            "status": "healthy",
            "ollama_url": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "api_key_set": bool(OLLAMA_API_KEY),
            "model_available": has_model,
            "available_models": models,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "ollama_url": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "api_key_set": bool(OLLAMA_API_KEY),
            "error": str(e),
        }

# ─── Emotion → TTS prosody mapping ──────────────────────────────

# Maps an emotion string (lowercased) to (rate, pitch) overrides for edge-tts.
# Covers every label from FER (Angry, Disgust, Fear, Happy, Neutral, Sad, Surprise)
# and SER (Angry, Bored, Disgust, Fear, Happy, Neutral, Question, Sad, Surprise),
# plus common aliases the fusion LLM might produce.
# Unrecognised emotions fall back to neutral defaults (+0%, +0Hz).
_EMOTION_TTS_MAP: dict[str, tuple[str, str]] = {
    # User-specified mappings
    "bored":      ("+15%", "+5Hz"),
    "confused":   ("-15%", "-3Hz"),
    "anxious":    ("-10%", "-5Hz"),
    "happy":      ("+10%", "+3Hz"),
    "excited":    ("+10%", "+3Hz"),
    "frustrated": ("-10%", "-3Hz"),
    # Model labels not already covered
    "angry":      ("-10%", "-3Hz"),    # same as frustrated
    "disgust":    ("-10%", "-3Hz"),    # same as frustrated
    "fear":       ("-10%", "-5Hz"),    # same as anxious
    "fearful":    ("-10%", "-5Hz"),    # alias
    "sad":        ("-15%", "-3Hz"),    # same as confused — slower, softer
    "surprise":   ("+10%", "+3Hz"),    # same as excited — energetic
    "surprised":  ("+10%", "+3Hz"),    # alias
    # Neutral / default
    "neutral":    ("+0%",  "+0Hz"),
    "uncertain":  ("+0%",  "+0Hz"),
    "question":   ("+0%",  "+0Hz"),
    "calm":       ("+0%",  "+0Hz"),
}


def _emotion_to_prosody(emotion: Optional[str]) -> tuple[str, str]:
    """Return (rate, pitch) for the given student emotion, defaulting to neutral."""
    if not emotion:
        return "+0%", "+0Hz"
    key = emotion.strip().lower()
    rate, pitch = _EMOTION_TTS_MAP.get(key, ("+0%", "+0Hz"))
    if key not in _EMOTION_TTS_MAP:
        logger.info(f"[TTS Prosody] Unknown emotion '{emotion}' — using neutral defaults")
    else:
        logger.info(f"[TTS Prosody] Emotion '{emotion}' → rate={rate} pitch={pitch}")
    return rate, pitch


# ─── Helpers ─────────────────────────────────────────────────────

def _get_prosody(
    student_emotion: Optional[str] = None,
    session_id: Optional[str] = None,
) -> tuple[str, str]:
    """Compute (rate, pitch) from emotion + session pace modifier."""
    rate, pitch = _emotion_to_prosody(student_emotion)
    if session_id:
        from services.tutor_service import get_session
        session = get_session(session_id)
        if session and hasattr(session, 'pace_modifier') and session.pace_modifier != 0:
            try:
                current_rate = int(rate.replace("%", "").replace("+", ""))
            except ValueError:
                current_rate = 0
            new_rate = current_rate + session.pace_modifier
            rate = f"+{new_rate}%" if new_rate >= 0 else f"{new_rate}%"
    return rate, pitch


async def _synthesize_audio(
    text: str,
    voice: str,
    student_emotion: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    """Synthesize speech and return base64-encoded MP3.

    If *student_emotion* is provided the TTS rate and pitch are adjusted
    so Dr. Nova's delivery mirrors the adaptive tone the LLM text already
    carries. Overridden by permanent pace if set by student intent.
    """
    try:
        rate, pitch = _get_prosody(student_emotion, session_id)
        tts = get_tts_service()
        result = await tts.synthesize(text=text, voice=voice, rate=rate, pitch=pitch)
        return base64.b64encode(result["audio_bytes"]).decode("utf-8")
    except Exception as e:
        logger.warning(f"TTS synthesis failed, returning text only: {e}")
        return None


async def _generate_blendshapes(
    text: str,
    voice: str,
    student_emotion: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[dict]:
    """Generate A2F blendshape animation data for the given text.

    Returns a dict with keys ``names`` and ``frames`` on success,
    or ``None`` if Audio2Face is unavailable (frontend uses fallback visemes).
    """
    import os
    try:
        rate, pitch = _get_prosody(student_emotion, session_id)
        tts = get_tts_service()
        wav_path = await tts.synthesize_wav(text=text, voice=voice, rate=rate, pitch=pitch)

        from services.a2f_client import get_blendshapes
        result = get_blendshapes(wav_path)

        # Cleanup temp WAV
        try:
            os.remove(wav_path)
        except OSError:
            pass

        if result is None:
            return None

        return {
            "names": result["blendshape_names"],
            "frames": result["frames"],
        }
    except Exception as e:
        logger.warning(f"A2F blendshape generation failed (using fallback): {e}")
        return None

