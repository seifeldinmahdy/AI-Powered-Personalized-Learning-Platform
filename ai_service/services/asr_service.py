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
            audio_array, sample_rate = sf.read(BytesIO(audio_data))
            logger.info(f"Loaded audio: shape={audio_array.shape}, sample_rate={sample_rate}")

            # Convert to float32 and ensure mono
            if len(audio_array.shape) > 1:
                # Convert stereo to mono by averaging channels
                audio_array = np.mean(audio_array, axis=1)

            audio_array = audio_array.astype(np.float32)
            logger.info(f"Processed audio array shape: {audio_array.shape}")

            # Transcribe using numpy array directly (no FFmpeg needed)
            logger.info(f"Starting transcription with language: {language}")
            start_time = time.time()
            result = self.model.transcribe(
                audio_array,
                language=language,
                fp16=False
            )
            end_time = time.time()

            logger.info(f"Transcription completed in {end_time - start_time:.3f}s")

            return {
                "text": result['text'].strip(),
                "language": result.get('language', language),
                "inference_time": round(end_time - start_time, 3),
                "segments": result.get('segments', [])
            }

        except Exception as e:
            logger.error(f"Transcription error: {type(e).__name__}: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise


# Global instance
_asr_service = None


def get_asr_service() -> ASRService:
    """Get or create the global ASR service instance."""
    global _asr_service
    if _asr_service is None:
        _asr_service = ASRService(model_size="tiny")
    return _asr_service
