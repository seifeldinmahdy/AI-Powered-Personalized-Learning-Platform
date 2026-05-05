"""
TTS Router for text-to-speech synthesis endpoints.
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from services.tts_service import get_tts_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/tts",
    tags=["TTS"],
)


# ─── Request / Response schemas ──────────────────────────────────

class SynthesizeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000,
                      description="Text to convert to speech")
    voice: str = Field(default="en-US-GuyNeural",
                       description="Edge TTS voice name")
    rate: str = Field(default="+0%",
                      description="Speed adjustment (e.g. '+20%', '-30%')")
    pitch: str = Field(default="+0Hz",
                       description="Pitch adjustment (e.g. '+50Hz', '-50Hz')")


class SynthesizeMetadataResponse(BaseModel):
    success: bool
    voice: str
    rate: str
    pitch: str
    text_length: int
    audio_size_bytes: int
    inference_time_seconds: float


# ─── Endpoints ───────────────────────────────────────────────────

@router.post("/synthesize",
             response_class=Response,
             responses={200: {"content": {"audio/mpeg": {}}}})
async def synthesize(request: SynthesizeRequest):
    """
    Convert text to speech and return the MP3 audio bytes.

    Returns raw audio/mpeg bytes directly — suitable for streaming
    to an <audio> element or saving to file.
    """
    try:
        tts = get_tts_service()
        result = await tts.synthesize(
            text=request.text,
            voice=request.voice,
            rate=request.rate,
            pitch=request.pitch,
        )

        return Response(
            content=result["audio_bytes"],
            media_type="audio/mpeg",
            headers={
                "X-TTS-Voice": result["voice"],
                "X-TTS-Inference-Time": str(result["inference_time"]),
                "X-TTS-Audio-Size": str(result["audio_size_bytes"]),
            },
        )

    except Exception as e:
        logger.error(f"TTS synthesis error: {e}")
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")


@router.post("/synthesize-json")
async def synthesize_json(request: SynthesizeRequest):
    """
    Synthesize speech and return metadata (no audio bytes).
    Useful for checking voice/rate/pitch settings before streaming.
    """
    try:
        tts = get_tts_service()
        result = await tts.synthesize(
            text=request.text,
            voice=request.voice,
            rate=request.rate,
            pitch=request.pitch,
        )

        return SynthesizeMetadataResponse(
            success=True,
            voice=result["voice"],
            rate=result["rate"],
            pitch=result["pitch"],
            text_length=result["text_length"],
            audio_size_bytes=result["audio_size_bytes"],
            inference_time_seconds=result["inference_time"],
        )

    except Exception as e:
        logger.error(f"TTS error: {e}")
        raise HTTPException(status_code=500, detail=f"TTS failed: {e}")


@router.get("/voices")
async def list_voices(
    language: str = Query(default="en", description="Language prefix filter"),
):
    """List all available Edge TTS voices for a language."""
    try:
        tts = get_tts_service()
        voices = await tts.list_voices(language)
        return {
            "count": len(voices),
            "language_filter": language,
            "voices": voices,
        }
    except Exception as e:
        logger.error(f"Error listing voices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/presets")
async def get_presets():
    """Return curated preset voices and supported emotional styles."""
    tts = get_tts_service()
    return {
        "preset_voices": tts.get_preset_voices(),
        "supported_styles": tts.get_supported_styles(),
    }


@router.get("/health")
async def tts_health():
    """Check if the TTS service is ready."""
    try:
        tts = get_tts_service()
        return {"status": "healthy", "engine": "edge-tts"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
