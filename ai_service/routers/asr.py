"""
ASR Router for audio transcription endpoints.
"""

from fastapi import APIRouter, File, UploadFile, HTTPException, Form
from typing import Optional
from services.asr_service import get_asr_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/asr",
    tags=["ASR"]
)


@router.post("/transcribe")
async def transcribe_audio(
    audio_file: UploadFile = File(..., description="Audio file to transcribe"),
    language: Optional[str] = Form(default='en', description="Language code (e.g., 'en', 'es', 'fr')")
):
    """
    Transcribe audio file to text using Whisper model.

    Args:
        audio_file: Audio file (WAV, MP3, M4A, etc.)
        language: Language code for transcription (default: 'en')

    Returns:
        JSON with transcription text and metadata
    """
    try:
        # Validate file type
        if not audio_file.content_type or not audio_file.content_type.startswith('audio'):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Expected audio file, got {audio_file.content_type}"
            )

        # Read audio data
        audio_data = await audio_file.read()

        if len(audio_data) == 0:
            raise HTTPException(status_code=400, detail="Empty audio file")

        # Get ASR service and transcribe
        asr_service = get_asr_service()
        result = asr_service.transcribe_audio(audio_data, language=language)

        return {
            "success": True,
            "transcription": result["text"],
            "language": result["language"],
            "inference_time_seconds": result["inference_time"],
            "filename": audio_file.filename
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing audio file: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process audio: {str(e)}"
        )


@router.get("/health")
async def asr_health():
    """Check if ASR service is loaded and ready."""
    try:
        asr_service = get_asr_service()
        return {
            "status": "healthy",
            "model_loaded": asr_service.model is not None
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }
