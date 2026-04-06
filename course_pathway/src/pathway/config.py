"""Centralized configuration for the Course Pathway Generator.

Loads from environment variables / .env file using pydantic-settings.
Re-uses the same Ollama Cloud credentials as rag_pipeline.
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


class PathwaySettings(BaseSettings):
    """All configuration for the pathway generator."""

    model_config = SettingsConfigDict(
        env_file=str(_find_env_file()),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Ollama Cloud (shared with rag_pipeline) ──────────────────
    ollama_host: str = "https://ollama.com"
    ollama_model: str = "gpt-oss:120b"
    ollama_api_key: str = ""
    max_retries: int = 3

    # ── ChromaDB (shared with rag_pipeline) ──────────────────────
    chroma_db_path: str = ""
    chroma_collection_name: str = "course_chunks"

    # ── Session grouping ─────────────────────────────────────────
    session_min_tokens: int = 3000
    session_max_tokens: int = 5000

    # ── Section discovery ────────────────────────────────────────
    topic_similarity_threshold: float = 0.85

    # ── LLM curriculum ordering ──────────────────────────────────
    ollama_curriculum_timeout: int = 600

    # ── Storage ──────────────────────────────────────────────────
    sqlite_db_path: str = ""

    def resolve_paths(self, project_root: Path) -> None:
        """Resolve relative paths to absolute paths based on project root.

        Called once at startup to ensure ChromaDB and SQLite paths are absolute
        regardless of the working directory.
        """
        if not self.chroma_db_path:
            self.chroma_db_path = str(
                project_root / "rag_pipeline" / "data" / "chroma"
            )
        elif not Path(self.chroma_db_path).is_absolute():
            self.chroma_db_path = str(project_root / self.chroma_db_path)

        if not self.sqlite_db_path:
            self.sqlite_db_path = str(
                project_root / "course_pathway" / "data" / "session_plans.db"
            )
        elif not Path(self.sqlite_db_path).is_absolute():
            self.sqlite_db_path = str(project_root / self.sqlite_db_path)


_settings: PathwaySettings | None = None


def get_settings() -> PathwaySettings:
    """Return a singleton PathwaySettings instance with resolved paths."""
    global _settings
    if _settings is None:
        _settings = PathwaySettings()
        # Project root is 2 levels up from this file:
        # course_pathway/src/pathway/config.py → AI-Powered-...
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        _settings.resolve_paths(project_root)
    return _settings
