"""
Speech Emotion Recognition Service.

Uses the trained 2D-CNN (Mel spectrogram) model with optional
multi-chunk superimposing for stable predictions from audio streams.
"""

import io
import os
import time
import logging
import numpy as np
from collections import deque
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ─── Audio / Spectrogram Configuration (must match training notebook) ───
SAMPLE_RATE = 22050
DURATION = 3                # seconds — pad / truncate all audio to this
N_MELS = 128                # mel frequency bins
N_FFT = 2048
HOP_LENGTH = 512
MAX_TIME_STEPS = 130        # fixed time dimension for mel spectrograms

DEFAULT_CONFIDENCE_THRESHOLD = 55.0   # percent
DEFAULT_SUPERIMPOSE_CHUNKS = 5        # rolling buffer size for streaming

# The 9 emotion classes (must match label-encoder order from training)
EMOTION_LABELS = [
    "Angry", "Bored", "Disgust", "Fear", "Happy",
    "Neutral", "Question", "Sad", "Surprise",
]


# ─── SpecAugment layer (needed to deserialize the .keras file) ──────────
def _get_spec_augment_class():
    """Return the SpecAugment Keras layer class, defined locally so
    TensorFlow is only imported when the service is actually used."""
    import tensorflow as tf
    from tensorflow.keras import layers as L

    class SpecAugment(L.Layer):
        """Frequency & time masking — active only during training."""

        def __init__(self, freq_mask=15, time_mask=20, num_masks=2, **kw):
            super().__init__(**kw)
            self.freq_mask = freq_mask
            self.time_mask = time_mask
            self.num_masks = num_masks

        def call(self, inputs, training=None):
            if not training:
                return inputs
            x = inputs
            shape = tf.shape(x)
            freq_dim, time_dim = shape[1], shape[2]
            for _ in range(self.num_masks):
                # Frequency mask
                f = tf.random.uniform([], 1, self.freq_mask, dtype=tf.int32)
                f0 = tf.random.uniform([], 0, freq_dim - f, dtype=tf.int32)
                freq_idx = tf.range(freq_dim)
                fm = tf.logical_and(freq_idx >= f0, freq_idx < f0 + f)
                fm = tf.reshape(fm, [1, freq_dim, 1, 1])
                x = tf.where(tf.broadcast_to(fm, shape), 0.0, x)
                # Time mask
                t = tf.random.uniform([], 1, self.time_mask, dtype=tf.int32)
                t0 = tf.random.uniform([], 0, time_dim - t, dtype=tf.int32)
                time_idx = tf.range(time_dim)
                tm = tf.logical_and(time_idx >= t0, time_idx < t0 + t)
                tm = tf.reshape(tm, [1, 1, time_dim, 1])
                x = tf.where(tf.broadcast_to(tm, shape), 0.0, x)
            return x

        def get_config(self):
            cfg = super().get_config()
            cfg.update({
                "freq_mask": self.freq_mask,
                "time_mask": self.time_mask,
                "num_masks": self.num_masks,
            })
            return cfg

    return SpecAugment


# ═══════════════════════════════════════════════════════════════
class SERService:
    """Speech Emotion Recognition — mirrors the FER service pattern."""

    def __init__(
        self,
        model_path: str = "ai_service/models/best_ser_model.keras",
        superimpose_chunks: int = DEFAULT_SUPERIMPOSE_CHUNKS,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ):
        import tensorflow as tf

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"SER model not found: {model_path}")

        # ── Load model with custom SpecAugment layer ──
        SpecAugment = _get_spec_augment_class()
        logger.info(f"Loading SER model from {model_path} …")
        self.model = tf.keras.models.load_model(
            model_path, custom_objects={"SpecAugment": SpecAugment}
        )
        logger.info("SER model loaded successfully")

        # ── Hardcoded normalisation stats (from training notebook) ──
        self.mel_mean = -30.0
        self.mel_std = 15.0
        logger.info(f"Mel normalisation: mean={self.mel_mean:.4f}, std={self.mel_std:.4f}")

        # ── Emotion labels (must match training label order) ──
        self.emotion_labels = list(EMOTION_LABELS)

        self.superimpose_chunks = superimpose_chunks
        self.confidence_threshold = confidence_threshold

        # Per-session spectrogram buffers
        self._buffers: Dict[str, deque] = {}

    # ─── Public API ──────────────────────────────────────────

    def predict_audio(self, audio_bytes: bytes) -> Dict:
        """
        Predict emotion from a single audio clip (WAV / MP3 / FLAC / WebM).

        Returns dict with emotion, confidence, probabilities.
        """
        start = time.time()
        mel = self._bytes_to_mel(audio_bytes)
        if mel is None:
            return self._empty_result(time.time() - start, reason="Could not decode audio")
        mel_input = self._prepare_input(mel)
        return self._predict(mel_input, time.time() - start)

    def predict_chunks(
        self,
        chunks: List[bytes],
        session_id: str = "default",
    ) -> Dict:
        """
        Stream-style prediction: accumulate mel spectrograms from
        multiple audio chunks in a rolling buffer and average before
        predicting — analogous to FER frame superimposing.
        """
        start = time.time()
        buf = self._get_buffer(session_id)

        for raw in chunks:
            mel = self._bytes_to_mel(raw)
            if mel is not None:
                buf.append(mel)

        if len(buf) == 0:
            return self._empty_result(time.time() - start, reason="No valid audio chunks")

        superimposed = np.mean(buf, axis=0)
        mel_input = self._prepare_input(superimposed)
        result = self._predict(mel_input, time.time() - start)
        result["buffer_size"] = len(buf)
        result["superimpose_chunks"] = self.superimpose_chunks
        return result

    def reset_buffer(self, session_id: str = "default") -> None:
        """Clear the spectrogram buffer for a session."""
        self._buffers.pop(session_id, None)

    # ─── Internal helpers ────────────────────────────────────

    def _get_buffer(self, session_id: str) -> deque:
        if session_id not in self._buffers:
            self._buffers[session_id] = deque(maxlen=self.superimpose_chunks)
        return self._buffers[session_id]

    def _bytes_to_mel(self, audio_bytes: bytes) -> Optional[np.ndarray]:
        """Decode audio bytes → log-Mel spectrogram (128 × 130)."""
        import librosa
        import soundfile as sf
        import tempfile

        try:
            y = None
            sr = None

            # Attempt 1: read with soundfile in-memory (WAV, FLAC, OGG)
            audio_buf = io.BytesIO(audio_bytes)
            try:
                y, sr = sf.read(audio_buf, dtype="float32")
                if y.ndim > 1:
                    y = y.mean(axis=1)  # stereo → mono
            except Exception:
                pass

            # Attempt 2: write to temp file so librosa/ffmpeg can detect
            # the container format (handles MP4, M4A, WebM, MP3, etc.)
            if y is None:
                with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp:
                    tmp.write(audio_bytes)
                    tmp_path = tmp.name
                try:
                    y, sr = librosa.load(tmp_path, sr=None)
                finally:
                    os.remove(tmp_path)

            # Resample to target sample rate
            if sr != SAMPLE_RATE:
                y = librosa.resample(y, orig_sr=sr, target_sr=SAMPLE_RATE)

            # Fix to exact duration (pad / truncate)
            target_len = SAMPLE_RATE * DURATION
            if len(y) < target_len:
                y = np.pad(y, (0, target_len - len(y)), mode="constant")
            else:
                y = y[:target_len]

            # Normalise amplitude to [-1, 1]
            peak = np.max(np.abs(y))
            if peak > 0:
                y = y / peak

            # Mel spectrogram → dB
            mel = librosa.feature.melspectrogram(
                y=y, sr=SAMPLE_RATE, n_mels=N_MELS,
                n_fft=N_FFT, hop_length=HOP_LENGTH,
            )
            mel_db = librosa.power_to_db(mel, ref=np.max)

            # Fix time dimension
            if mel_db.shape[1] < MAX_TIME_STEPS:
                pad_w = MAX_TIME_STEPS - mel_db.shape[1]
                mel_db = np.pad(mel_db, ((0, 0), (0, pad_w)),
                                mode="constant", constant_values=-80)
            else:
                mel_db = mel_db[:, :MAX_TIME_STEPS]

            return mel_db  # (128, 130)

        except Exception as e:
            logger.warning(f"Audio decode failed: {e}")
            return None

    def _prepare_input(self, mel: np.ndarray) -> np.ndarray:
        """Normalise and reshape for the model: (1, 128, 130, 1)."""
        mel_norm = (mel - self.mel_mean) / (self.mel_std + 1e-8)
        return mel_norm[np.newaxis, ..., np.newaxis].astype(np.float32)

    def _predict(self, model_input: np.ndarray, elapsed: float) -> Dict:
        preds = self.model.predict(model_input, verbose=0)[0]
        emo_idx = int(np.argmax(preds))
        confidence = float(preds[emo_idx]) * 100

        emotion = (
            self.emotion_labels[emo_idx]
            if confidence >= self.confidence_threshold
            else "Uncertain"
        )

        return {
            "emotion_detected": True,
            "emotion": emotion,
            "confidence": round(confidence, 2),
            "probabilities": {
                self.emotion_labels[i]: round(float(preds[i]) * 100, 2)
                for i in range(len(self.emotion_labels))
            },
            "inference_time_seconds": round(elapsed, 3),
        }

    @staticmethod
    def _empty_result(elapsed: float, reason: str = "") -> Dict:
        return {
            "emotion_detected": False,
            "emotion": None,
            "confidence": 0.0,
            "probabilities": {e: 0.0 for e in EMOTION_LABELS},
            "inference_time_seconds": round(elapsed, 3),
            "reason": reason,
        }

# ── Singleton ──────────────────────────────────────────────────
_ser_service: Optional[SERService] = None


def get_ser_service() -> SERService:
    """Get or create the global SER service instance."""
    global _ser_service
    if _ser_service is None:
        base = os.path.dirname(__file__)
        models_dir = os.path.join(base, "..", "models")

        # Model
        candidates = [
            os.path.join(models_dir, "best_ser_model.keras"),
            "ai_service/models/best_ser_model.keras",
            "best_ser_model.keras",
        ]
        model_path = candidates[0]
        for c in candidates:
            if os.path.exists(c):
                model_path = c
                break

        _ser_service = SERService(model_path=model_path)
    return _ser_service
