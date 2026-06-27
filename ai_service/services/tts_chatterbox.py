"""Chatterbox Turbo TTS backend — drop-in replacement for the Edge ``TTSService``.

Same public surface as ``tts_service.TTSService`` (``synthesize`` /
``synthesize_wav`` / ``list_voices`` / ``get_preset_voices`` /
``get_supported_styles``) so it swaps in via ``get_tts_service()`` with **no
call-site changes**. The only addition is an optional ``delivery`` argument that
carries Turbo's emotion controls (a paralinguistic delivery TAG + temperature);
PACE is done as a pitch-preserving time-stretch on the output, because Turbo
removed ``cfg_weight``/``exaggeration`` and has no speed knob.

Hardening:
  - Lazy, single GPU load; a load/synthesis failure raises a clear error that the
    dispatcher catches to fall back to Edge (the live tutor never goes silent).
  - All inputs clamped; tags whitelisted by the caller (delivery.tag).

Speed:
  - **Synthesize-once**: a small LRU caches the generated (post-time-stretch)
    waveform keyed by (text, tag, temperature, stretch), so the two calls per
    utterance (``synthesize`` for the browser + ``synthesize_wav`` for A2F) run
    the model a SINGLE time. Repeated canned lines (redirects, pace
    confirmations) are also served from cache.
  - Model singleton + warmup; ``torch.inference_mode``; A2F WAV written with
    soundfile (no ffmpeg on that path).
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

from services.tts_tags import keep_valid_tags

logger = logging.getLogger(__name__)

# Browser audio target sample rate is the model's own; A2F needs 16 kHz mono PCM.
_A2F_SR = 16000
_WAVEFORM_CACHE_MAX = 256


@dataclass
class Delivery:
    """Backend-agnostic delivery spec resolved from the student's emotion.

    Edge uses ``rate``/``pitch``; Chatterbox Turbo uses ``tag`` (a whitelisted
    paralinguistic delivery token) + ``temperature``, and ``time_stretch`` for
    pace (1.0 = unchanged, >1 faster, <1 slower).
    """
    tag: str = ""
    temperature: float = 0.8
    time_stretch: float = 1.0
    # Edge compatibility (ignored by Turbo):
    rate: str = "+0%"
    pitch: str = "+0Hz"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class ChatterboxTurboService:
    """Turbo TTS with the Edge-compatible interface + emotion delivery + cache."""

    def __init__(self) -> None:
        self._model = None              # lazy; loaded on first synth
        self._sr: int = 24000           # overwritten from model.sr after load
        self._ref_clip = os.getenv("CHATTERBOX_REF_CLIP", "").strip() or None
        self._device = os.getenv("CHATTERBOX_DEVICE", "cuda").strip()
        # Generated-waveform cache: key -> (np.float32 mono, sr)
        self._cache: "OrderedDict[tuple, tuple]" = OrderedDict()
        logger.info("ChatterboxTurboService created (model loads lazily on first synth)")

    # ── Model load + warmup ─────────────────────────────────────────

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        t0 = time.time()
        # NOTE: confirm the exact import/class against the installed chatterbox
        # package; isolated here so only this line changes if the API differs.
        # Override with CHATTERBOX_IMPORT="module:ClassName" if needed.
        import_spec = os.getenv("CHATTERBOX_IMPORT", "chatterbox.tts:ChatterboxTTS")
        module_name, _, class_name = import_spec.partition(":")
        import importlib

        mod = importlib.import_module(module_name)
        model_cls = getattr(mod, class_name)
        # Turbo checkpoint selection is package-specific; from_pretrained is the
        # common entry. CHATTERBOX_MODEL lets you point at the turbo weights.
        model_id = os.getenv("CHATTERBOX_MODEL", "").strip()
        if model_id:
            self._model = model_cls.from_pretrained(model_id, device=self._device)
        else:
            self._model = model_cls.from_pretrained(device=self._device)
        self._sr = int(getattr(self._model, "sr", self._sr))
        logger.info("Chatterbox Turbo loaded on %s (sr=%d) in %.1fs",
                    self._device, self._sr, time.time() - t0)

        # Warm up so the first real utterance isn't penalized by lazy JIT/allocs.
        try:
            self._raw_generate("Hello.", "", 0.8)
            logger.info("Chatterbox warmup complete")
        except Exception as exc:
            logger.warning("Chatterbox warmup failed (non-fatal): %s", exc)
        return self._model

    # ── Core generation ─────────────────────────────────────────────

    def _raw_generate(self, text: str, tag: str, temperature: float):
        """Run the model once → (np.float32 mono waveform, sr). No cache."""
        import numpy as np
        import torch

        model = self._ensure_model()
        # Keep only the cues Turbo actually interprets; drop any hallucinated
        # bracket so the model never tries to vocalize a bogus token.
        clean = keep_valid_tags(text)
        prompt = f"{tag} {clean}".strip() if tag else clean
        kwargs = {"temperature": _clamp(float(temperature), 0.6, 1.0)}
        if self._ref_clip:
            kwargs["audio_prompt_path"] = self._ref_clip
        with torch.inference_mode():
            wav = model.generate(prompt, **kwargs)
        # Normalize to a 1-D float32 numpy array.
        if hasattr(wav, "detach"):
            wav = wav.detach().to("cpu").float().numpy()
        wav = np.asarray(wav, dtype="float32").squeeze()
        if wav.ndim > 1:
            wav = wav.mean(axis=0)
        return wav, self._sr

    def _synth_cached(self, text: str, delivery: Delivery):
        """Return the post-time-stretch waveform for (text, delivery), cached."""
        import numpy as np

        tag = delivery.tag or ""
        temp = round(_clamp(delivery.temperature, 0.6, 1.0), 3)
        stretch = round(_clamp(delivery.time_stretch, 0.7, 1.3), 3)
        key = (text, tag, temp, stretch)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        wav, sr = self._raw_generate(text, tag, temp)

        # Pace: pitch-preserving time-stretch (Turbo has no speed knob).
        if abs(stretch - 1.0) > 0.01:
            try:
                import librosa
                wav = librosa.effects.time_stretch(wav, rate=stretch)
            except Exception as exc:
                logger.warning("time_stretch failed (using unstretched): %s", exc)

        result = (np.asarray(wav, dtype="float32"), sr)
        self._cache[key] = result
        self._cache.move_to_end(key)
        if len(self._cache) > _WAVEFORM_CACHE_MAX:
            self._cache.popitem(last=False)
        return result

    # ── Output encoders ─────────────────────────────────────────────

    @staticmethod
    def _to_pcm16(wav, sr: int, target_sr: int):
        """Resample to target_sr mono and return (int16 ndarray, target_sr)."""
        import numpy as np

        if sr != target_sr:
            import librosa
            wav = librosa.resample(wav, orig_sr=sr, target_sr=target_sr)
        wav = np.clip(wav, -1.0, 1.0)
        return (wav * 32767.0).astype("<i2"), target_sr

    def _to_mp3_bytes(self, wav, sr: int) -> bytes:
        """Encode a float waveform to MP3 bytes via a single in-memory ffmpeg
        pipe (kept as MP3 so the existing frontend playback is unchanged)."""
        import subprocess
        import imageio_ffmpeg

        pcm16, _ = self._to_pcm16(wav, sr, sr)  # keep model sr for the heard audio
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
               "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
               "-f", "mp3", "pipe:1"]
        proc = subprocess.run(cmd, input=pcm16.tobytes(), stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=30)
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg mp3 encode failed: {proc.stderr.decode('utf-8', 'ignore')[:200]}")
        return proc.stdout

    # ── Public API (Edge-compatible) ────────────────────────────────

    async def synthesize(self, text: str, voice: str = "", rate: str = "+0%",
                         pitch: str = "+0Hz", delivery: Optional[Delivery] = None) -> dict:
        """Synthesize → MP3 bytes (browser). Matches TTSService.synthesize()."""
        start = time.time()
        delivery = delivery or _delivery_from_rate(rate, pitch)
        wav, sr = self._synth_cached(text, delivery)
        audio_bytes = self._to_mp3_bytes(wav, sr)
        elapsed = round(time.time() - start, 3)
        return {
            "audio_bytes": audio_bytes,
            "content_type": "audio/mpeg",
            "voice": "chatterbox-turbo",
            "rate": rate,
            "pitch": pitch,
            "text_length": len(text),
            "audio_size_bytes": len(audio_bytes),
            "inference_time": elapsed,
        }

    async def synthesize_wav(self, text: str, voice: str = "", rate: str = "+0%",
                            pitch: str = "+0Hz", delivery: Optional[Delivery] = None) -> str:
        """Synthesize → 16 kHz mono 16-bit PCM WAV path for Audio2Face.

        Same contract as TTSService.synthesize_wav() (caller deletes the file).
        Hits the same waveform cache as ``synthesize`` → the model runs once per
        utterance even though the tutor calls both methods.
        """
        import soundfile as sf

        delivery = delivery or _delivery_from_rate(rate, pitch)
        wav, sr = self._synth_cached(text, delivery)
        pcm16, out_sr = self._to_pcm16(wav, sr, _A2F_SR)
        _, tmp_wav = tempfile.mkstemp(suffix=".wav")
        sf.write(tmp_wav, pcm16, out_sr, subtype="PCM_16")
        return tmp_wav

    # ── Compat shims for the /tts router ────────────────────────────

    async def list_voices(self, language: str = "en") -> list[dict]:
        ref = self._ref_clip or "(built-in)"
        return [{"short_name": "chatterbox-turbo", "gender": "Neural",
                 "locale": "en-US", "friendly_name": f"Chatterbox Turbo ({ref})"}]

    @staticmethod
    def get_preset_voices() -> dict:
        return {"learnpal": "chatterbox-turbo"}

    @staticmethod
    def get_supported_styles() -> list[str]:
        # The whitelisted, tutor-appropriate delivery tags.
        return ["clear throat", "sigh", "shush", "cough", "groan", "sniff", "gasp", "chuckle", "laugh"]


def _delivery_from_rate(rate: str, pitch: str) -> Delivery:
    """Build a basic Delivery for callers that pass only Edge rate/pitch.

    Maps the rate percentage to a time-stretch so pace still works (e.g. the
    /tts router and lab narration), with a neutral [narration] tag.
    """
    try:
        pct = int(str(rate).replace("%", "").replace("+", ""))
    except ValueError:
        pct = 0
    stretch = _clamp(1.0 + pct / 100.0, 0.7, 1.3)
    return Delivery(tag="", temperature=0.8, time_stretch=stretch,
                    rate=rate, pitch=pitch)


# ── Singleton ───────────────────────────────────────────────────────
_chatterbox_service: Optional[ChatterboxTurboService] = None


def get_chatterbox_service() -> ChatterboxTurboService:
    global _chatterbox_service
    if _chatterbox_service is None:
        _chatterbox_service = ChatterboxTurboService()
    return _chatterbox_service
