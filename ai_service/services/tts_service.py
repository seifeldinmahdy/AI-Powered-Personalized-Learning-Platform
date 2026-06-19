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

from services.tts_tags import strip_all_tags

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
        delivery=None,  # accepted for interface parity with Chatterbox; Edge uses rate/pitch
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
        # Edge can't interpret spoken-cue tags — strip them so it never reads
        # "[sigh]" aloud (Chatterbox keeps them; this is the fallback path).
        text = strip_all_tags(text)
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
        delivery=None,  # accepted for interface parity with Chatterbox; Edge uses rate/pitch
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
        text = strip_all_tags(text)  # Edge can't speak cue tags; strip them.
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


class VoiceRouter:
    """Dispatches TTS to the configured backend with graceful Edge fallback.

    ``TTS_BACKEND=chatterbox`` uses Chatterbox Turbo; ``edge`` (default) uses
    Edge. Any Chatterbox load/synthesis failure trips a process-wide circuit
    breaker and serves Edge for the rest of the run, so the tutor never goes
    silent. All call sites keep using ``get_tts_service().synthesize(...)``.
    """

    def __init__(self) -> None:
        self._edge: Optional[TTSService] = None
        self._chatterbox = None
        self._chatterbox_dead = False

    def _edge_backend(self) -> TTSService:
        if self._edge is None:
            self._edge = TTSService()
        return self._edge

    def _want_chatterbox(self) -> bool:
        backend = os.getenv("TTS_BACKEND", "edge").strip().lower()
        return backend in ("chatterbox", "turbo", "chatterbox-turbo") and not self._chatterbox_dead

    def _chatterbox_backend(self):
        if self._chatterbox is None:
            from services.tts_chatterbox import get_chatterbox_service
            self._chatterbox = get_chatterbox_service()
        return self._chatterbox

    async def synthesize(self, *args, **kwargs) -> Dict:
        if self._want_chatterbox():
            try:
                return await self._chatterbox_backend().synthesize(*args, **kwargs)
            except Exception as exc:
                logger.warning("Chatterbox synthesize failed (%s) — falling back to Edge for the rest of this process", exc)
                self._chatterbox_dead = True
        return await self._edge_backend().synthesize(*args, **kwargs)

    async def synthesize_wav(self, *args, **kwargs) -> str:
        if self._want_chatterbox():
            try:
                return await self._chatterbox_backend().synthesize_wav(*args, **kwargs)
            except Exception as exc:
                logger.warning("Chatterbox synthesize_wav failed (%s) — falling back to Edge for the rest of this process", exc)
                self._chatterbox_dead = True
        return await self._edge_backend().synthesize_wav(*args, **kwargs)

    async def list_voices(self, language: str = "en") -> List[Dict]:
        backend = self._chatterbox_backend() if self._want_chatterbox() else self._edge_backend()
        try:
            return await backend.list_voices(language)
        except Exception:
            return await self._edge_backend().list_voices(language)

    def get_preset_voices(self) -> Dict[str, str]:
        backend = self._chatterbox_backend() if self._want_chatterbox() else self._edge_backend()
        return backend.get_preset_voices()

    def get_supported_styles(self) -> List[str]:
        backend = self._chatterbox_backend() if self._want_chatterbox() else self._edge_backend()
        return backend.get_supported_styles()


# ── Singleton ──
_voice_router: Optional[VoiceRouter] = None


def get_tts_service() -> VoiceRouter:
    """Return the global voice router (Chatterbox-or-Edge, with Edge fallback)."""
    global _voice_router
    if _voice_router is None:
        _voice_router = VoiceRouter()
    return _voice_router
