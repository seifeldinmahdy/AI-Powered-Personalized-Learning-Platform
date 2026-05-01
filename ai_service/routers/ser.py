"""
SER Router — Speech Emotion Recognition endpoints.
"""

from fastapi import APIRouter, File, UploadFile, HTTPException, Form
from typing import Optional, List
from services.ser_service import get_ser_service, EMOTION_LABELS
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ser",
    tags=["SER"],
)


@router.post("/predict")
async def predict_emotion(
    audio: UploadFile = File(
        ..., description="Audio file (WAV / MP3 / FLAC / WebM)"
    ),
):
    """
    Predict emotion from a single audio clip.

    Accepts any common audio format. The audio is resampled to 22 050 Hz,
    truncated / padded to 3 s, converted to a 128×130 log-Mel spectrogram,
    and classified by the 2D-CNN.

    Returns:
        JSON with emotion label, confidence, and per-class probabilities.
    """
    try:
        data = await audio.read()
        if len(data) == 0:
            raise HTTPException(status_code=400, detail="Empty audio file")

        ser = get_ser_service()
        result = ser.predict_audio(data)

        return {
            "success": True,
            **result,
            "filename": audio.filename,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SER prediction error: {e}")
        raise HTTPException(status_code=500, detail=f"SER failed: {e}")


@router.post("/predict-stream")
async def predict_stream(
    chunks: List[UploadFile] = File(
        ..., description="Multiple consecutive audio chunks from a stream"
    ),
    session_id: Optional[str] = Form(
        default="default",
        description="Session ID to isolate the superimpose buffer per client",
    ),
):
    """
    Stream-style prediction with chunk superimposing (averaging).

    Send multiple short audio clips; the service accumulates their
    Mel spectrograms in a rolling buffer and averages before predicting.
    This is the audio equivalent of FER frame superimposing — it
    produces more stable results over time.

    Args:
        chunks:     Multiple audio files (ordered, most-recent last).
        session_id: Isolates the buffer per client/session.

    Returns:
        JSON with smoothed emotion, confidence, buffer_size, probabilities.
    """
    try:
        raw_list: list[bytes] = []
        for f in chunks:
            data = await f.read()
            if len(data) > 0:
                raw_list.append(data)

        if not raw_list:
            raise HTTPException(
                status_code=400, detail="No valid audio chunks received"
            )

        ser = get_ser_service()
        result = ser.predict_chunks(raw_list, session_id=session_id)

        return {
            "success": True,
            **result,
            "session_id": session_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"SER stream prediction error: {e}")
        raise HTTPException(status_code=500, detail=f"SER failed: {e}")


@router.post("/reset-buffer")
async def reset_buffer(
    session_id: str = Form(default="default"),
):
    """Clear the spectrogram buffer for a session."""
    try:
        ser = get_ser_service()
        ser.reset_buffer(session_id)
        return {
            "success": True,
            "session_id": session_id,
            "message": "Buffer cleared",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def ser_health():
    """Check if the SER model is loaded and ready."""
    try:
        ser = get_ser_service()
        return {
            "status": "healthy",
            "model_loaded": ser.model is not None,
            "superimpose_chunks": ser.superimpose_chunks,
            "confidence_threshold": ser.confidence_threshold,
            "emotion_labels": ser.emotion_labels,
            "mel_normalisation": {
                "mean": ser.mel_mean,
                "std": ser.mel_std,
            },
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
