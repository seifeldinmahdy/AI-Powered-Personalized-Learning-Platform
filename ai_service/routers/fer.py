"""
FER Router for facial emotion recognition endpoints.
"""

from fastapi import APIRouter, File, UploadFile, HTTPException, Form, Query
from typing import Optional, List
from services.fer_service import get_fer_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/fer",
    tags=["FER"],
)


@router.post("/predict")
async def predict_emotion(
    image: UploadFile = File(..., description="Image file (JPEG/PNG) with a face"),
):
    """
    Predict emotion from a single image.

    Detects the largest face, preprocesses the 48×48 grayscale crop,
    and runs the CNN classifier.

    Returns:
        JSON with emotion label, confidence, and per-class probabilities.
    """
    try:
        if image.content_type and not image.content_type.startswith("image"):
            raise HTTPException(
                status_code=400,
                detail=f"Expected image file, got {image.content_type}",
            )

        data = await image.read()
        if len(data) == 0:
            raise HTTPException(status_code=400, detail="Empty image file")

        fer = get_fer_service()
        result = fer.predict_image(data)

        return {
            "success": True,
            "face_detected": result["face_detected"],
            "emotion": result["emotion"],
            "confidence": result["confidence"],
            "probabilities": result["probabilities"],
            "inference_time_seconds": result["inference_time_seconds"],
            "filename": image.filename,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"FER prediction error: {e}")
        raise HTTPException(status_code=500, detail=f"FER failed: {e}")


@router.post("/predict-video")
async def predict_video_frames(
    frames: List[UploadFile] = File(
        ..., description="Multiple consecutive image frames from webcam"
    ),
    session_id: Optional[str] = Form(
        default="default",
        description="Session ID to isolate the superimpose buffer per client",
    ),
):
    """
    Predict emotion using frame superimposing (averaging).

    Send multiple consecutive webcam frames; the service accumulates
    face crops in a rolling buffer and averages them before prediction,
    producing a much more stable result — identical to the technique
    used in RealtimeFER.py.

    Args:
        frames:     Multiple image files (ordered, most-recent last).
        session_id: Isolates the buffer per client/session.

    Returns:
        JSON with smoothed emotion, confidence, buffer_size, probabilities.
    """
    try:
        raw_list: list[bytes] = []
        for f in frames:
            data = await f.read()
            if len(data) > 0:
                raw_list.append(data)

        if not raw_list:
            raise HTTPException(status_code=400, detail="No valid frames received")

        fer = get_fer_service()
        result = fer.predict_frames(raw_list, session_id=session_id)

        return {
            "success": True,
            "face_detected": result["face_detected"],
            "emotion": result["emotion"],
            "confidence": result["confidence"],
            "probabilities": result["probabilities"],
            "buffer_size": result.get("buffer_size", 0),
            "superimpose_frames": result.get(
                "superimpose_frames", fer.superimpose_frames
            ),
            "inference_time_seconds": result["inference_time_seconds"],
            "session_id": session_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"FER video prediction error: {e}")
        raise HTTPException(status_code=500, detail=f"FER failed: {e}")


@router.post("/reset-buffer")
async def reset_buffer(
    session_id: str = Form(default="default"),
):
    """Clear the superimpose buffer for a session (e.g. when the user leaves)."""
    try:
        fer = get_fer_service()
        fer.reset_buffer(session_id)
        return {"success": True, "session_id": session_id, "message": "Buffer cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def fer_health():
    """Check if the FER model is loaded and ready."""
    try:
        fer = get_fer_service()
        return {
            "status": "healthy",
            "model_loaded": fer.model is not None,
            "superimpose_frames": fer.superimpose_frames,
            "confidence_threshold": fer.confidence_threshold,
            "emotion_labels": fer.model and list(
                __import__("services.fer_service", fromlist=["EMOTION_LABELS"]).EMOTION_LABELS
            ),
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
