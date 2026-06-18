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
    OLLAMA_HOST: str
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

    # ── Base model (Qwen3-4B-Instruct, 4-bit) ────────────────────────
    # Unsloth quantized variant — one base model, two LoRA adapters.
    LLAMA_BASE_MODEL: str = "unsloth/Qwen3-4B-Instruct"

    # ── Fine-tuned LoRA adapter paths ────────────────────────────────
    # Primary path fields for Qwen3-4B adapters.
    # Empty = use Ollama.  Set the path when LoRA adapters are ready.
    # QG_MODEL_PATH / DG_MODEL_PATH are preferred; QG_LORA_PATH /
    # DG_LORA_PATH kept for backward compatibility with Llama adapters.
    QG_MODEL_PATH: str = ""   # path to QG Qwen3-4B LoRA adapter dir
    DG_MODEL_PATH: str = ""   # path to DG Qwen3-4B LoRA adapter dir
    QG_LORA_PATH: str = ""    # legacy: Llama-3.2-3B QG adapter
    DG_LORA_PATH: str = ""    # legacy: Llama-3.2-3B DG adapter

    # ── LoRA hyperparameters ─────────────────────────────────────────
    # QG: higher rank — must adhere to conditioning AND generate content
    QG_LORA_R: int = 32
    QG_LORA_ALPHA: int = 64
    # DG: simpler task, lower rank sufficient
    DG_LORA_R: int = 16
    DG_LORA_ALPHA: int = 32
    LORA_DROPOUT: float = 0.05

    # ── Tokenizer / generation ───────────────────────────────────────
    MAX_SEQ_LENGTH: int = 1024       # shared default
    MAX_SEQ_LENGTH_QG: int = 1024    # QG-specific (inputs shorter with simplified prompt)
    MAX_SEQ_LENGTH_DG: int = 1024    # DG-specific
    LOAD_IN_4BIT: bool = True        # QLoRA — 4-bit quantization


_settings: MCQSettings | None = None


def get_settings() -> MCQSettings:
    """Return a singleton MCQSettings instance."""
    global _settings
    if _settings is None:
        _settings = MCQSettings()
    return _settings
