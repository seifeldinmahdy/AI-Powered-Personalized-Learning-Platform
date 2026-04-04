"""Centralized configuration via environment variables using pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path:
    """Walk up from this file to find the .env next to requirements.txt."""
    current = Path(__file__).resolve().parent
    for _ in range(5):
        candidate = current / ".env"
        if candidate.exists():
            return candidate
        current = current.parent
    return Path(".env")


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=str(_find_env_file()),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Ollama Cloud ──────────────────────────────────────────────
    ollama_host: str = "https://ollama.com"
    ollama_model: str = "gpt-oss:120b"
    ollama_api_key: str = ""

    # ── Retry ─────────────────────────────────────────────────────
    max_retries: int = 3

    # ── ChromaDB ──────────────────────────────────────────────────
    chroma_db_path: str = "./data/chroma"
    chroma_collection_name: str = "course_chunks"

    # ── Chunking ──────────────────────────────────────────────────
    chunk_size_tokens: int = 350
    chunk_min_tokens: int = 300
    chunk_max_tokens: int = 400
    chunk_overlap_tokens: int = 50

    # ── Embedding ─────────────────────────────────────────────────
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # ── RAG ───────────────────────────────────────────────────────
    top_k: int = 5

    # ── Paths ─────────────────────────────────────────────────────
    raw_books_dir: str = "./raw_books"


def get_settings() -> Settings:
    """Factory that returns a cached Settings instance."""
    return Settings()
