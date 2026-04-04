"""LLM-based chunk analysis — one API call per chunk.

Sends a structured prompt to Ollama Cloud requesting topic, difficulty,
is_definitional, depends_on, and summary in a single JSON response.
"""

from __future__ import annotations

import structlog

from src.llm.client import OllamaCloudClient
from src.models.schemas import ChunkMetadata

logger = structlog.get_logger(__name__)

# ── Prompt templates ─────────────────────────────────────────────

ANALYSIS_SYSTEM_PROMPT = (
    "You are an expert computer science educator analyzing textbook content. "
    "For the given text chunk, produce a JSON object with EXACTLY these fields:\n"
    "\n"
    '  "topic"           — the single main concept this chunk covers (1-3 words)\n'
    '  "difficulty"      — one of: "beginner", "intermediate", "expert"\n'
    '  "is_definitional" — true if the chunk primarily introduces and defines a '
    "concept for the first time, false otherwise\n"
    '  "depends_on"      — a JSON array of prerequisite topic strings (1-3 words '
    "each) a student must understand before this chunk makes sense; use an empty "
    "array [] if there are no prerequisites\n"
    '  "summary"         — one sentence describing what this chunk teaches\n'
    "\n"
    "Return ONLY the JSON object.  No markdown fences, no commentary."
)

_USER_TEMPLATE = "Analyze this textbook chunk:\n\n{chunk_text}"


# ── Analyzer ─────────────────────────────────────────────────────

class ChunkAnalyzer:
    """Calls the LLM once per chunk and parses structured metadata."""

    _VALID_DIFFICULTIES = {"beginner", "intermediate", "expert"}

    def __init__(self, llm_client: OllamaCloudClient) -> None:
        self.llm = llm_client

    def analyze(self, chunk_text: str, chunk_id: str = "") -> ChunkMetadata:
        """Analyze a single chunk and return validated ``ChunkMetadata``.

        Parameters
        ----------
        chunk_text:
            Raw textbook text for this chunk.
        chunk_id:
            Optional identifier for structured logging.

        Returns
        -------
        ChunkMetadata
            Validated Pydantic model with all five fields.

        Raises
        ------
        RuntimeError
            If the LLM response cannot be parsed after exhausting retries.
        """
        messages = [
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _USER_TEMPLATE.format(chunk_text=chunk_text),
            },
        ]

        logger.info("chunk_analysis_start", chunk_id=chunk_id)

        data = self.llm.chat_json(messages, temperature=0.2)

        # ── Validate and coerce ──────────────────────────────────
        metadata = self._parse_response(data, chunk_id)

        logger.info(
            "chunk_analysis_complete",
            chunk_id=chunk_id,
            topic=metadata.topic,
            difficulty=metadata.difficulty,
        )
        return metadata

    # ── Internal parsing ─────────────────────────────────────────

    def _parse_response(
        self, data: dict, chunk_id: str
    ) -> ChunkMetadata:
        """Coerce raw LLM JSON into a validated ChunkMetadata."""
        # Normalize difficulty
        difficulty = str(data.get("difficulty", "beginner")).lower().strip()
        if difficulty not in self._VALID_DIFFICULTIES:
            logger.warning(
                "invalid_difficulty_coerced",
                chunk_id=chunk_id,
                raw=difficulty,
                coerced="beginner",
            )
            difficulty = "beginner"

        # Normalize depends_on
        depends_on_raw = data.get("depends_on", [])
        if isinstance(depends_on_raw, str):
            depends_on_raw = [
                t.strip() for t in depends_on_raw.split(",") if t.strip()
            ]
        elif not isinstance(depends_on_raw, list):
            depends_on_raw = []
        depends_on = [str(t) for t in depends_on_raw]

        # Normalize is_definitional
        is_def_raw = data.get("is_definitional", False)
        if isinstance(is_def_raw, str):
            is_definitional = is_def_raw.lower().strip() in (
                "true",
                "yes",
                "1",
            )
        else:
            is_definitional = bool(is_def_raw)

        return ChunkMetadata(
            topic=str(data.get("topic", "unknown")).strip(),
            difficulty=difficulty,
            is_definitional=is_definitional,
            depends_on=depends_on,
            summary=str(data.get("summary", "")).strip(),
        )
