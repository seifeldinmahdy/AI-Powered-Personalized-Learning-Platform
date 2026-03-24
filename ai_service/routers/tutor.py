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
    stop_session,
    get_session_state,
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
    voice: str = Field(default="en-US-JennyNeural", description="TTS voice name")


class ContinueRequest(BaseModel):
    session_id: str = Field(..., description="Session ID")
    include_audio: bool = Field(default=True, description="Include TTS audio in response")


class AskQuestionRequest(BaseModel):
    session_id: str = Field(..., description="Session ID")
    question: str = Field(..., min_length=1, description="Student's question")
    include_audio: bool = Field(default=True, description="Include TTS audio in response")


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
        result = await generate_lecture_chunk(request.session_id)

        # Generate TTS audio if requested and there's text
        audio_base64 = None
        if request.include_audio and result["text"]:
            audio_base64 = await _synthesize_audio(result["text"], session.voice)

        return {
            "success": True,
            "session_id": request.session_id,
            "text": result["text"],
            "audio_base64": audio_base64,
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
        result = await answer_question(request.session_id, request.question)

        audio_base64 = None
        if request.include_audio and result["answer"]:
            audio_base64 = await _synthesize_audio(result["answer"], session.voice)

        return {
            "success": True,
            "session_id": request.session_id,
            "answer": result["answer"],
            "audio_base64": audio_base64,
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


@router.post("/stop")
async def stop(request: StopRequest):
    """End a tutoring session early."""
    success = stop_session(request.session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"success": True, "session_id": request.session_id, "status": "finished"}


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


# ─── Helper ──────────────────────────────────────────────────────

async def _synthesize_audio(text: str, voice: str) -> Optional[str]:
    """Synthesize speech and return base64-encoded MP3."""
    try:
        tts = get_tts_service()
        result = await tts.synthesize(text=text, voice=voice)
        return base64.b64encode(result["audio_bytes"]).decode("utf-8")
    except Exception as e:
        logger.warning(f"TTS synthesis failed, returning text only: {e}")
        return None
