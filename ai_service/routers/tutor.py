"""
Tutor Router — AI tutoring session endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import json
from pydantic import BaseModel, Field
from typing import List, Optional
from routers._auth import jwt_verified_student_id
from services.tutor_service import (
    create_session,
    get_session,
    generate_lecture_chunk,
    generate_lecture_chunk_stream,
    answer_question,
    answer_question_stream,
    repeat_lecture_chunk,
    stop_session,
    get_session_state,
    abandon_socratic_exchange,
)
from services.tts_service import get_tts_service
from services.tts_tags import strip_all_tags
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
    prior_topics: Optional[List[str]] = Field(default=None, description="Titles of lessons the student already completed, so the tutor can call back to them ('as we saw last lesson…')")


class ContinueRequest(BaseModel):
    session_id: str = Field(..., description="Session ID")
    include_audio: bool = Field(default=True, description="Include TTS audio in response")
    student_emotion: Optional[str] = Field(default=None, description="Current student emotional state for tone adaptation")


class GroundingPassage(BaseModel):
    """A raw retrieved source passage the tutor must ground on."""
    text: str
    book: str = ""
    page_start: int = 0
    page_end: int = 0
    topic: str = ""
    relevance_score: float = 0.0


class AskQuestionRequest(BaseModel):
    session_id: str = Field(..., description="Session ID")
    question: str = Field(..., min_length=1, description="Student's question")
    include_audio: bool = Field(default=True, description="Include TTS audio in response")
    student_emotion: Optional[str] = Field(default=None, description="Student's emotional state during the question")
    grounding: Optional[list[GroundingPassage]] = Field(
        default=None,
        description="Raw retrieved source passages (from /rag/ask) for the tutor "
                    "to ground on. The tutor grounds on these PRIMARY passages, "
                    "not on a pre-generated RAG answer.",
    )


class StopRequest(BaseModel):
    session_id: str = Field(..., description="Session ID")


# ─── Endpoints ───────────────────────────────────────────────────


@router.post("/start")
async def start_session(
    request: StartSessionRequest,
    student_id: str = Depends(jwt_verified_student_id),
):
    """
    Start a new AI tutoring session.

    Provide a list of topics (with optional subtopics). The tutor will
    lecture through them in order, recursively summarizing context.

    The student identity comes ONLY from the verified token (``student_id``),
    never from the request body — the session (and any profile fetch it triggers)
    is bound to the authenticated student.
    """
    try:
        topics = [t.model_dump() for t in request.topics]
        session = create_session(
            topics=topics,
            voice=request.voice,
            session_id=request.session_id,
            student_profile_summary=request.student_profile_summary,
            student_profile_data=request.student_profile_data,
            student_id=student_id,
            prior_topics=request.prior_topics,
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


def _assert_session_owner(session, student_id: str) -> None:
    """Reject a verified student operating on someone else's tutor session.

    The session records the ``student_id`` it was started for (from the verified
    token at ``/start``). A different verified student — even with a valid token —
    cannot drive or read another student's live session by guessing its id.
    Sessions without a recorded owner (legacy) are not blocked, since there is no
    owner to compare against.
    """
    owner = getattr(session, "student_id", None)
    if owner and str(owner) != str(student_id):
        raise HTTPException(status_code=403, detail="This session belongs to another student.")


@router.post("/continue")
async def continue_session(
    request: ContinueRequest,
    student_id: str = Depends(jwt_verified_student_id),
):
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _assert_session_owner(session, student_id)

    async def event_generator():
        try:
            async for item in generate_lecture_chunk_stream(request.session_id, student_emotion=request.student_emotion):
                if item["type"] == "chunk":
                    raw_text = item["text"]
                    # Display/transcript gets NO spoken cues; the raw text (with
                    # cues) goes to TTS — Chatterbox speaks the valid cues, Edge
                    # strips them.
                    chunk_data = {
                        "text_chunk": strip_all_tags(raw_text),
                        "audio_base64": None,
                        "blendshapes": None
                    }
                    if request.include_audio and raw_text.strip():
                        chunk_data["audio_base64"] = await _synthesize_audio(
                            raw_text,
                            session.voice,
                            request.student_emotion,
                            request.session_id
                        )
                        chunk_data["blendshapes"] = await _generate_blendshapes(
                            raw_text, session.voice,
                            request.student_emotion, request.session_id,
                        )
                    yield f"data: {json.dumps(chunk_data)}\n\n"
                elif item["type"] == "metadata":
                    meta = item["metadata"]
                    meta["success"] = True
                    meta["session_id"] = request.session_id
                    yield f"data: {json.dumps(meta)}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/ask")
async def ask(
    request: AskQuestionRequest,
    student_id: str = Depends(jwt_verified_student_id),
):
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    _assert_session_owner(session, student_id)

    async def event_generator():
        try:
            grounding_passages = (
                [p.model_dump() for p in request.grounding] if request.grounding else None
            )
            async for item in answer_question_stream(
                request.session_id,
                request.question,
                student_emotion=request.student_emotion,
                grounding_passages=grounding_passages,
            ):
                if item["type"] == "chunk":
                    raw_text = item["text"]
                    chunk_data = {
                        "text_chunk": strip_all_tags(raw_text),
                        "audio_base64": None,
                        "blendshapes": None
                    }
                    if request.include_audio and raw_text.strip():
                        chunk_data["audio_base64"] = await _synthesize_audio(
                            raw_text,
                            session.voice,
                            request.student_emotion,
                            request.session_id
                        )
                        chunk_data["blendshapes"] = await _generate_blendshapes(
                            raw_text, session.voice,
                            request.student_emotion, request.session_id,
                        )
                    yield f"data: {json.dumps(chunk_data)}\n\n"
                elif item["type"] == "metadata":
                    meta = item["metadata"]
                    meta["success"] = True
                    meta["session_id"] = request.session_id
                    yield f"data: {json.dumps(meta)}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/status")
async def session_status(session_id: str):
    """Get the current state of a tutoring session."""
    state = get_session_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"success": True, **state}


@router.post("/stop")
async def stop(request: StopRequest):
    """End a tutoring session early."""
    success = stop_session(request.session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"success": True, "session_id": request.session_id, "status": "finished"}


class AbandonSocraticRequest(BaseModel):
    session_id: str = Field(..., description="Session ID")


@router.post("/abandon-socratic")
async def abandon_socratic(request: AbandonSocraticRequest):
    """Mark any open Socratic exchange as abandoned (e.g. after slide navigation)."""
    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    was_open = abandon_socratic_exchange(request.session_id)
    return {
        "success": True,
        "session_id": request.session_id,
        "abandoned": was_open,
        "socratic_status": (
            session.socratic_exchange.status
            if session.socratic_exchange else None
        ),
    }


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


class ReactionSynthesizeRequest(BaseModel):
    text: str = Field(..., description="Quip text to synthesize")
    emotion: Optional[str] = Field(default=None, description="A2F delivery emotion (e.g. excited, happy, sad)")
    voice: Optional[str] = Field(default=None, description="TTS voice; defaults to LearnPal's voice")


@router.post("/synthesize-reaction")
async def tutor_synthesize_reaction(request: ReactionSynthesizeRequest):
    """Synthesize a short, session-less voiceline + A2F blendshapes for the
    avatar's playful reactions. Used by the offline-demo bake script to pre-
    render the easter-egg quips in LearnPal's real voice with lip-sync.
    """
    voice = request.voice or "en-US-GuyNeural"
    try:
        audio_base64 = await _synthesize_audio(request.text, voice, request.emotion)
        blendshapes = await _generate_blendshapes(request.text, voice, request.emotion)
        return {"success": True, "audio_base64": audio_base64, "blendshapes": blendshapes}
    except Exception as e:
        logger.error(f"Reaction synthesis error: {e}")
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
    from services.tutor_service import OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_API_KEY
    import httpx
    try:
        headers = {}
        if OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_HOST.rstrip('/')}/api/tags", headers=headers)
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            has_model = any(OLLAMA_MODEL in m for m in models)
        return {
            "status": "healthy",
            "ollama_url": OLLAMA_HOST,
            "model": OLLAMA_MODEL,
            "api_key_set": bool(OLLAMA_API_KEY),
            "model_available": has_model,
            "available_models": models,
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "ollama_url": OLLAMA_HOST,
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


# ─── Emotion → Chatterbox delivery (tag + temperature) ──────────
# Edge uses rate/pitch (above); Chatterbox Turbo has no cfg_weight/exaggeration,
# so it uses a whitelisted delivery TAG + temperature (pace reuses the rate above
# as a time-stretch, so both backends stay in sync). The tutor RESPONDS to the
# student's emotion supportively — it never MIRRORS it (a fearful student gets a
# calm [whispering] delivery, never [fear]). Excluded: [angry] [sarcastic]
# [crying] [fear].
_EMOTION_TAG_TEMP: dict[str, tuple[str, float]] = {
    "bored":      ("[sigh]", 0.90),
    "happy":      ("[chuckle]", 0.85),
    "excited":    ("[laugh]", 0.85),
    "surprise":   ("[gasp]", 0.85),
    "surprised":  ("[gasp]", 0.85),
    "confused":   ("", 0.70),
    "sad":        ("[sigh]", 0.70),
    "anxious":    ("[clear throat]", 0.70),
    "fear":       ("[shush]", 0.70),
    "fearful":    ("[shush]", 0.70),
    "frustrated": ("[sigh]", 0.72),
    "angry":      ("[clear throat]", 0.72),
    "disgust":    ("", 0.72),
    "neutral":    ("", 0.80),
    "uncertain":  ("", 0.80),
    "question":   ("", 0.80),
    "calm":       ("", 0.75),
}


def _get_delivery(student_emotion: Optional[str] = None, session_id: Optional[str] = None):
    """Resolve a backend-agnostic Delivery from the student's emotion.

    Spoken cue tags are now emitted by the tutor LLM inline (where natural), NOT
    mechanically prefixed here — so ``tag`` stays empty. Emotion still drives
    Turbo ``temperature`` and the pace ``time_stretch`` (and Edge ``rate``/``pitch``).
    """
    from services.tts_chatterbox import Delivery
    rate, pitch = _get_prosody(student_emotion, session_id)  # existing pace logic (+ pace_modifier)
    key = (student_emotion or "").strip().lower()
    _legacy_tag, temperature = _EMOTION_TAG_TEMP.get(key, ("", 0.80))
    # Derive time-stretch from the SAME rate so Edge and Turbo pace match.
    try:
        pct = int(rate.replace("%", "").replace("+", ""))
    except ValueError:
        pct = 0
    stretch = max(0.7, min(1.3, 1.0 + pct / 100.0))
    return Delivery(tag="", temperature=temperature, time_stretch=stretch, rate=rate, pitch=pitch)


async def _synthesize_audio(
    text: str,
    voice: str,
    student_emotion: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Optional[str]:
    """Synthesize speech and return base64-encoded MP3.

    If *student_emotion* is provided the TTS rate and pitch are adjusted
    so LearnPal's delivery mirrors the adaptive tone the LLM text already
    carries. Overridden by permanent pace if set by student intent.
    """
    try:
        delivery = _get_delivery(student_emotion, session_id)
        tts = get_tts_service()
        result = await tts.synthesize(text=text, voice=voice, rate=delivery.rate,
                                      pitch=delivery.pitch, delivery=delivery)
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
        delivery = _get_delivery(student_emotion, session_id)
        tts = get_tts_service()
        wav_path = await tts.synthesize_wav(text=text, voice=voice, rate=delivery.rate,
                                            pitch=delivery.pitch, delivery=delivery)

        from services.a2f_client import get_blendshapes

        # Map student_emotion to A2F tutor emotion (empathetic response)
        a2f_emotion = None
        if student_emotion:
            key = student_emotion.strip().lower()
            if key in ["bored"]:
                a2f_emotion = {"amazement": 0.3}
            elif key in ["happy", "excited", "surprise", "surprised"]:
                a2f_emotion = {"joy": 0.8}
            elif key in ["sad", "anxious", "fear", "fearful", "frustrated", "angry"]:
                a2f_emotion = {"sadness": 0.5}  # Empathetic concern
            elif key in ["disgust"]:
                a2f_emotion = {"amazement": 0.5}

        result = get_blendshapes(wav_path, emotion_dict=a2f_emotion)

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

