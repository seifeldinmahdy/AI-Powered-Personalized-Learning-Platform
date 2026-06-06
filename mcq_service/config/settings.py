"""Centralized configuration for the MCQ Assessment Service.

Loads from environment variables / .env file using pydantic-settings.
Follows the same singleton pattern as course_pathway/src/pathway/config.py.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path:
    """Walk up from this file to find the closest .env file."""
    current = Path(__file__).resolve().parent
    for _ in range(6):
        candidate = current / ".env"
        if candidate.exists():
            return candidate
        current = current.parent
    return Path(".env")


class MCQSettings(BaseSettings):
    """All configuration for the MCQ service."""

    model_config = SettingsConfigDict(
        env_file=str(_find_env_file()),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Ollama ───────────────────────────────────────────────────────
    OLLAMA_HOST: str = "https://ollama.com"
    OLLAMA_API_KEY: str = ""
    OLLAMA_MODEL: str = "gpt-oss:120b"  # shared fallback

    # Per-model overrides (empty = use OLLAMA_MODEL).
    # Set to local Ollama model names to use fine-tuned GGUF models
    # without touching the LoRA paths (which require CUDA/Unsloth).
    QG_OLLAMA_MODEL: str = ""   # e.g. "mcq-qg" for local inference
    DG_OLLAMA_MODEL: str = ""   # e.g. "mcq-dg" for local inference

    # ── Session checkpoints ──────────────────────────────────────────
    CHECKPOINT_INTERVAL: int = 3

    # ── Topic performance blending ───────────────────────────────────
    TOPIC_PERFORMANCE_UPDATE_WEIGHT: float = 0.3

    # ── Score category thresholds ────────────────────────────────────
    SCORE_VERY_WEAK_THRESHOLD: float = 0.3
    SCORE_WEAK_THRESHOLD: float = 0.5
    SCORE_MODERATE_THRESHOLD: float = 0.75

    # ── Generation tuning ────────────────────────────────────────────
    MCQ_MAX_REGENERATION_ATTEMPTS: int = 2
    MCQ_DISTRACTOR_COUNT: int = 3

    # ── Llama / Unsloth base model ───────────────────────────────────
    LLAMA_BASE_MODEL: str = "unsloth/Llama-3.2-3B-Instruct"

    # ── Fine-tuned LoRA adapter paths ────────────────────────────────
    # Empty = use Ollama.  Set the path when LoRA adapters are ready.
    QG_LORA_PATH: str = ""
    DG_LORA_PATH: str = ""

    # ── LoRA hyperparameters ─────────────────────────────────────────
    LORA_R: int = 16
    LORA_ALPHA: int = 16
    LORA_DROPOUT: float = 0.0  # Unsloth recommends 0 for speed

    # ── Llama tokenizer / generation ─────────────────────────────────
    MAX_SEQ_LENGTH: int = 512
    LOAD_IN_4BIT: bool = True  # QLoRA — 4-bit quantization


_settings: MCQSettings | None = None


def get_settings() -> MCQSettings:
    """Return a singleton MCQSettings instance."""
    global _settings
    if _settings is None:
        _settings = MCQSettings()
    return _settings
