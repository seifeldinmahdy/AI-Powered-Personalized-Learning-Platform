"""LLM answer generation grounded in retrieved context.

Formats retrieved chunks into a context block and calls the LLM with a
strict system prompt that forbids answering from parametric knowledge
and requires source citations.
"""

from __future__ import annotations

import structlog

from src.llm.client import OllamaCloudClient
from src.models.schemas import SourceChunk

logger = structlog.get_logger(__name__)

# ── Prompt templates ─────────────────────────────────────────────

RAG_SYSTEM_PROMPT = (
    "You are a helpful computer science tutor.  You answer student questions "
    "using ONLY the provided context excerpts from course textbooks.\n\n"
    "RULES:\n"
    "1. Answer ONLY from the provided context.  If the context does not "
    "contain enough information, say so clearly.\n"
    "2. For EVERY factual claim you make, cite the source in the format "
    "[Book: <book>, Pages: <page_start>-<page_end>].\n"
    "3. Never fabricate information.  Never use knowledge outside the "
    "provided context.\n"
    "4. Be concise, accurate, and pedagogically clear.\n"
    "5. If multiple sources cover the same point, prefer the one with "
    "the highest relevance.\n"
)


def _format_context(sources: list[SourceChunk]) -> str:
    """Build a numbered context block from retrieved chunks."""
    parts: list[str] = []
    for i, src in enumerate(sources, 1):
        parts.append(
            f"--- Source {i} ---\n"
            f"Book: {src.book}\n"
            f"Pages: {src.page_start}-{src.page_end}\n"
            f"Topic: {src.topic}\n"
            f"Relevance: {src.relevance_score}\n"
            f"Content:\n{src.text}\n"
        )
    return "\n".join(parts)


# ── Generator ────────────────────────────────────────────────────

class AnswerGenerator:
    """Generates LLM answers grounded in retrieved context."""

    def __init__(self, llm_client: OllamaCloudClient) -> None:
        self.llm = llm_client

    def generate(
        self,
        question: str,
        sources: list[SourceChunk],
    ) -> str:
        """Generate an answer to *question* using *sources* as context.

        Returns the raw answer string with inline citations.
        """
        if not sources:
            return (
                "I could not find any relevant information in the course "
                "materials to answer your question.  Please try rephrasing "
                "or asking about a topic covered in the course."
            )

        context_block = _format_context(sources)

        user_message = (
            f"CONTEXT:\n{context_block}\n\n"
            f"QUESTION:\n{question}"
        )

        messages = [
            {"role": "system", "content": RAG_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        logger.info(
            "answer_generation_start",
            question_length=len(question),
            n_sources=len(sources),
        )

        answer = self.llm.chat(messages, json_mode=False, temperature=0.3)

        logger.info(
            "answer_generation_complete",
            answer_length=len(answer),
        )
        return answer
