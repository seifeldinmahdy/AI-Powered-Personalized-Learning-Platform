"""
TTS Service using Edge TTS (Microsoft Neural Voices) for text-to-speech synthesis.
"""

import edge_tts
import asyncio
import tempfile
import os
import time
import subprocess
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

# Best English neural voices
VOICES = {
    "jenny":   "en-US-JennyNeural",
    "aria":    "en-US-AriaNeural",
    "guy":     "en-US-GuyNeural",
    "andrew":  "en-US-AndrewMultilingualNeural",
    "ava":     "en-US-AvaMultilingualNeural",
}

DEFAULT_VOICE = "en-US-AndrewMultilingualNeural"

# Aria supports these emotional delivery styles
SUPPORTED_STYLES = [
    "cheerful", "sad", "angry", "excited",
    "friendly", "hopeful", "empathetic",
    "chat", "narration-professional",
]


class TTSService:
    def __init__(self):
        logger.info("TTS Service initialized (Edge TTS — no model loading required)")

    async def synthesize(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        rate: str = "+0%",
        pitch: str = "+0Hz",
    ) -> Dict:
        """
        Synthesize speech from text.

        Args:
            text:  The text to convert to speech.
            voice: Edge TTS voice name (e.g. 'en-US-GuyNeural').
            rate:  Speed adjustment (e.g. '+20%', '-30%').
            pitch: Pitch adjustment (e.g. '+50Hz', '-50Hz').

        Returns:
            Dict with audio_bytes, content_type, and metadata.
        """
        for attempt in range(3):
            try:
                logger.info(
                    f"Synthesizing {len(text)} chars | voice={voice} rate={rate} pitch={pitch} (attempt {attempt+1})"
                )
                start = time.time()

                communicate = edge_tts.Communicate(
                    text=text, voice=voice, rate=rate, pitch=pitch,
                )

                # Collect audio bytes in memory
                audio_chunks: list[bytes] = []
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_chunks.append(chunk["data"])

                audio_bytes = b"".join(audio_chunks)
                elapsed = round(time.time() - start, 3)

                logger.info(
                    f"Synthesis complete — {len(audio_bytes)} bytes in {elapsed}s"
                )

                return {
                    "audio_bytes": audio_bytes,
                    "content_type": "audio/mpeg",
                    "voice": voice,
                    "rate": rate,
                    "pitch": pitch,
                    "text_length": len(text),
                    "audio_size_bytes": len(audio_bytes),
                    "inference_time": elapsed,
                }

            except Exception as e:
                logger.error(f"TTS synthesis error (attempt {attempt+1}): {e}")
                if attempt == 2:
                    raise RuntimeError(f"Failed to synthesize speech: {e}") from e
                await asyncio.sleep(1)

    async def synthesize_wav(
        self,
        text: str,
        voice: str = DEFAULT_VOICE,
        rate: str = "+0%",
        pitch: str = "+0Hz",
    ) -> str:
        """Synthesize speech and convert to 16 kHz mono 16-bit PCM WAV.

        This WAV format is what Audio2Face-3D NIM expects as input.

        Args:
            text:  The text to convert to speech.
            voice: Edge TTS voice name.
            rate:  Speed adjustment.
            pitch: Pitch adjustment.

        Returns:
            Path to the temporary WAV file. Caller MUST delete after use.
        """
        for attempt in range(3):
            try:
                import imageio_ffmpeg

                logger.info(f"Synthesizing WAV for A2F — {len(text)} chars (attempt {attempt+1})")
                start = time.time()

                # Step 1: Generate MP3 via edge-tts
                _, tmp_mp3 = tempfile.mkstemp(suffix=".mp3")
                communicate = edge_tts.Communicate(
                    text=text, voice=voice, rate=rate, pitch=pitch,
                )
                await communicate.save(tmp_mp3)

                # Step 2: Convert to 16kHz mono 16-bit PCM WAV via ffmpeg
                _, tmp_wav = tempfile.mkstemp(suffix=".wav")
                ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
                cmd = [
                    ffmpeg_exe,
                    "-i", tmp_mp3,
                    "-ac", "1",           # mono
                    "-ar", "16000",       # 16 kHz
                    "-sample_fmt", "s16", # 16-bit signed PCM
                    tmp_wav,
                    "-y",                 # overwrite output
                ]
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    logger.error(f"ffmpeg conversion failed: {result.stderr}")
                    raise RuntimeError(f"ffmpeg failed: {result.stderr}")

                # Step 3: Cleanup temp MP3
                try:
                    os.remove(tmp_mp3)
                except OSError:
                    pass

                elapsed = round(time.time() - start, 3)
                wav_size = os.path.getsize(tmp_wav)
                logger.info(
                    f"WAV synthesis complete — {wav_size} bytes in {elapsed}s"
                )
                return tmp_wav

            except Exception as e:
                logger.error(f"WAV synthesis error (attempt {attempt+1}): {e}")
                # Ensure cleanup on failure
                try:
                    if 'tmp_mp3' in locals():
                        os.remove(tmp_mp3)
                except OSError:
                    pass
                    
                if attempt == 2:
                    raise RuntimeError(f"Failed to synthesize WAV: {e}") from e
                await asyncio.sleep(1)

    async def list_voices(self, language: str = "en") -> List[Dict]:
        """Return available Edge TTS voices for a language prefix."""
        all_voices = await edge_tts.list_voices()
        filtered = [
            {
                "short_name": v["ShortName"],
                "gender": v.get("Gender", "Unknown"),
                "locale": v["Locale"],
                "friendly_name": v.get("FriendlyName", v["ShortName"]),
            }
            for v in all_voices
            if v["Locale"].startswith(language)
        ]
        return filtered

    @staticmethod
    def get_preset_voices() -> Dict[str, str]:
        """Return the curated preset voice map."""
        return dict(VOICES)

    @staticmethod
    def get_supported_styles() -> List[str]:
        """Return styles supported by the Aria voice."""
        return list(SUPPORTED_STYLES)


# ── Singleton ──
_tts_service: Optional[TTSService] = None


def get_tts_service() -> TTSService:
    """Get or create the global TTS service instance."""
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService()
    return _tts_service
