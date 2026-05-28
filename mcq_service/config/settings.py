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

    # ── Ollama Cloud ─────────────────────────────────────────────────
    OLLAMA_HOST: str = "https://ollama.com"
    OLLAMA_API_KEY: str = ""
    OLLAMA_MODEL: str = "gpt-oss:120b"

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

    # ── Fine-tuned model paths ───────────────────────────────────────
    # Empty = use Ollama.  Set the path when fine-tuned T5 models are ready.
    QG_MODEL_PATH: str = ""
    DG_MODEL_PATH: str = ""


_settings: MCQSettings | None = None


def get_settings() -> MCQSettings:
    """Return a singleton MCQSettings instance."""
    global _settings
    if _settings is None:
        _settings = MCQSettings()
    return _settings
