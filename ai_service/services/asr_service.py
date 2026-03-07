"""
ASR Service using Whisper model for speech-to-text transcription.
"""

import whisper
import numpy as np
import time
import tempfile
import os
from typing import Dict
import logging
import soundfile as sf
from io import BytesIO
import librosa

logger = logging.getLogger(__name__)


class ASRService:
    def __init__(self, model_size: str = "tiny"):
        """
        Initialize the ASR service with a Whisper model.

        Args:
            model_size: Size of Whisper model (tiny, base, small, medium, large)
        """
        logger.info(f"Loading Whisper {model_size} model...")
        self.model = whisper.load_model(model_size)
        logger.info("Whisper model loaded successfully")

    def transcribe_audio(self, audio_data: bytes, language: str = 'en') -> Dict:
        """
        Transcribe audio data to text.

        Args:
            audio_data: Raw audio file bytes
            language: Language code for transcription (default: 'en')

        Returns:
            Dictionary containing transcription result and metadata
        """
        try:
            logger.info(f"Received audio data of size: {len(audio_data)} bytes")

            # Load audio from bytes using soundfile
            try:
                audio_array, sample_rate = sf.read(BytesIO(audio_data))
                logger.info(f"Loaded audio via soundfile: shape={audio_array.shape}, sample_rate={sample_rate}Hz")
            except Exception as sf_error:
                logger.warning(f"soundfile failed: {sf_error}. Trying librosa...")
                # Fallback to librosa if soundfile fails
                audio_array, sample_rate = librosa.load(BytesIO(audio_data), sr=None)
                logger.info(f"Loaded audio via librosa: shape={audio_array.shape}, sample_rate={sample_rate}Hz")

            # Convert to float32 and ensure mono
            if len(audio_array.shape) > 1:
                # Convert stereo to mono by averaging channels
                logger.info(f"Converting stereo to mono (original shape: {audio_array.shape})")
                audio_array = np.mean(audio_array, axis=1)

            audio_array = audio_array.astype(np.float32)
            
            # Calculate duration
            duration = len(audio_array) / sample_rate
            logger.info(f"Audio info: shape={audio_array.shape}, dtype={audio_array.dtype}, duration={duration:.2f}s")

            # Whisper requires 16kHz audio - resample if needed
            TARGET_SAMPLE_RATE = 16000
            if sample_rate != TARGET_SAMPLE_RATE:
                logger.info(f"Resampling audio from {sample_rate}Hz to {TARGET_SAMPLE_RATE}Hz")
                audio_array = librosa.resample(
                    audio_array, 
                    orig_sr=sample_rate, 
                    target_sr=TARGET_SAMPLE_RATE
                )
                sample_rate = TARGET_SAMPLE_RATE
                logger.info(f"Resampled audio shape: {audio_array.shape}")

            # Normalize audio to prevent clipping
            max_val = np.abs(audio_array).max()
            if max_val > 0:
                audio_array = audio_array / max_val
                logger.info(f"Normalized audio (max value was {max_val:.3f})")

            # Validate audio array
            if len(audio_array) == 0:
                raise ValueError("Audio array is empty after processing")
            
            if not np.isfinite(audio_array).all():
                raise ValueError("Audio array contains NaN or Inf values")

            # Transcribe using numpy array directly (no FFmpeg needed)
            logger.info(f"Starting Whisper transcription with language: {language}")
            start_time = time.time()
            result = self.model.transcribe(
                audio_array,
                language=language,
                fp16=False
            )
            end_time = time.time()

            logger.info(f"Transcription completed in {end_time - start_time:.3f}s")
            logger.info(f"Transcribed text: '{result['text'][:100]}...'")

            return {
                "text": result['text'].strip(),
                "language": result.get('language', language),
                "inference_time": round(end_time - start_time, 3),
                "segments": result.get('segments', [])
            }

        except Exception as e:
            logger.error(f"Transcription error: {type(e).__name__}: {str(e)}")
            import traceback
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
            raise RuntimeError(f"Failed to transcribe audio: {type(e).__name__}: {str(e)}") from e


# Global instance
_asr_service = None


def get_asr_service() -> ASRService:
    """Get or create the global ASR service instance."""
    global _asr_service
    if _asr_service is None:
        _asr_service = ASRService(model_size="tiny")
    return _asr_service
