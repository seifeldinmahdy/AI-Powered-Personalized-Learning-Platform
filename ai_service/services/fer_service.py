"""
Facial Emotion Recognition Service.

Uses the trained Keras CNN model with frame superimposing
(averaging multiple face crops) for stable predictions.
"""

import cv2
import numpy as np
import time
import os
from collections import deque
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# ─── Configuration (mirrors RealtimeFER.py) ───
IMG_SIZE = (48, 48)
DEFAULT_SUPERIMPOSE_FRAMES = 10
DEFAULT_CONFIDENCE_THRESHOLD = 55.0  # percent

EMOTION_LABELS = [
    "Angry", "Disgust", "Fear", "Happy", "Neutral", "Sad", "Surprise",
]


class FERService:
    def __init__(
        self,
        model_path: str = "ai_service/models/FER_Model.keras",
        superimpose_frames: int = DEFAULT_SUPERIMPOSE_FRAMES,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ):
        """
        Args:
            model_path: Path to the trained .keras weights file.
            superimpose_frames: Number of frames to average (buffer size).
            confidence_threshold: Minimum confidence % to accept a label.
        """
        # Lazy-import TF so the rest of the service starts quickly
        import tensorflow as tf

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"FER model not found: {model_path}")

        logger.info(f"Loading FER model from {model_path} …")
        self.model = tf.keras.models.load_model(model_path)
        logger.info("FER model loaded successfully")

        # Haar cascade for face detection
        cascade_path = (
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self.face_cascade = cv2.CascadeClassifier(cascade_path)

        self.superimpose_frames = superimpose_frames
        self.confidence_threshold = confidence_threshold

        # Per-session frame buffers keyed by session_id
        self._buffers: Dict[str, deque] = {}

    # ─── Public API ──────────────────────────────────────────

    def predict_image(self, image_bytes: bytes) -> Dict:
        """
        Run FER on a single image (no superimposing).

        Args:
            image_bytes: Raw bytes of an image file (JPEG / PNG).

        Returns:
            Dict with emotion, confidence, probabilities, face_detected flag.
        """
        start = time.time()
        frame = self._decode_image(image_bytes)
        faces = self._detect_faces(frame)

        if len(faces) == 0:
            return self._no_face_result(time.time() - start)

        face_roi = self._extract_face(frame, faces)
        face_input = np.expand_dims(face_roi, axis=(0, -1))  # (1,48,48,1)
        return self._predict(face_input, time.time() - start)

    def predict_frames(
        self,
        frames: List[bytes],
        session_id: str = "default",
    ) -> Dict:
        """
        Run FER with superimposing across multiple frames.

        Accumulates face crops into a rolling buffer and averages
        them before prediction — exactly like RealtimeFER.py.

        Args:
            frames:     List of raw image bytes (consecutive webcam grabs).
            session_id: Identifies the buffer so multiple clients are isolated.

        Returns:
            Dict with emotion, confidence, probabilities, buffer_size.
        """
        start = time.time()
        buf = self._get_buffer(session_id)

        for raw in frames:
            frame = self._decode_image(raw)
            faces = self._detect_faces(frame)
            if len(faces) > 0:
                face_roi = self._extract_face(frame, faces)
                buf.append(face_roi)

        if len(buf) == 0:
            return self._no_face_result(time.time() - start)

        # Superimpose: average all buffered crops
        superimposed = np.mean(buf, axis=0)
        superimposed = np.expand_dims(superimposed, axis=(0, -1))
        result = self._predict(superimposed, time.time() - start)
        result["buffer_size"] = len(buf)
        result["superimpose_frames"] = self.superimpose_frames
        return result

    def reset_buffer(self, session_id: str = "default") -> None:
        """Clear the frame buffer for a session."""
        self._buffers.pop(session_id, None)

    # ─── Internal helpers ────────────────────────────────────

    def _get_buffer(self, session_id: str) -> deque:
        if session_id not in self._buffers:
            self._buffers[session_id] = deque(
                maxlen=self.superimpose_frames,
            )
        return self._buffers[session_id]

    @staticmethod
    def _decode_image(image_bytes: bytes) -> np.ndarray:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Could not decode image bytes")
        return frame

    def _detect_faces(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(48, 48),
            flags=cv2.CASCADE_SCALE_IMAGE,
        )
        return faces

    @staticmethod
    def _extract_face(
        frame: np.ndarray, faces: np.ndarray
    ) -> np.ndarray:
        """Pick the largest face, resize to 48×48 grayscale, normalise."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        areas = [w * h for (x, y, w, h) in faces]
        idx = int(np.argmax(areas))
        x, y, w, h = faces[idx]
        roi = gray[y : y + h, x : x + w]
        roi = cv2.resize(roi, IMG_SIZE).astype("float32") / 255.0
        return roi

    def _predict(self, model_input: np.ndarray, elapsed_start: float) -> Dict:
        preds = self.model.predict(model_input, verbose=0)[0]
        emo_idx = int(np.argmax(preds))
        confidence = float(preds[emo_idx]) * 100

        if confidence >= self.confidence_threshold:
            emotion = EMOTION_LABELS[emo_idx]
        else:
            emotion = "Uncertain"

        elapsed = round(time.time() - (time.time() - elapsed_start), 3)

        return {
            "face_detected": True,
            "emotion": emotion,
            "confidence": round(confidence, 2),
            "probabilities": {
                EMOTION_LABELS[i]: round(float(preds[i]) * 100, 2)
                for i in range(len(EMOTION_LABELS))
            },
            "inference_time_seconds": round(elapsed_start, 3),
        }

    @staticmethod
    def _no_face_result(elapsed: float) -> Dict:
        return {
            "face_detected": False,
            "emotion": None,
            "confidence": 0.0,
            "probabilities": {e: 0.0 for e in EMOTION_LABELS},
            "inference_time_seconds": round(elapsed, 3),
        }


# ── Singleton ──
_fer_service: Optional[FERService] = None


def get_fer_service() -> FERService:
    """Get or create the global FER service instance."""
    global _fer_service
    if _fer_service is None:
        # Look for model in common locations
        candidates = [
            "ai_service/models/FER_Model.keras",
            os.path.join(os.path.dirname(__file__), "..", "..", "FER_Model.keras"),
            os.path.join(os.path.dirname(__file__), "..", "models", "FER_Model.keras"),
        ]
        model_path = "ai_service/models/FER_Model.keras"
        for c in candidates:
            if os.path.exists(c):
                model_path = c
                break
        _fer_service = FERService(model_path=model_path)
    return _fer_service
