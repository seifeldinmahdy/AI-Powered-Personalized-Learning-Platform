"""Pydantic v2 data contracts for all cross-module boundaries."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Indexing Models ───────────────────────────────────────────────


class ChunkMetadata(BaseModel):
    """LLM-analyzed metadata for a single textbook chunk."""

    topic: str = Field(..., description="Main concept, 1-3 words")
    difficulty: str = Field(
        ..., description="One of: beginner, intermediate, expert"
    )
    is_definitional: bool = Field(
        ...,
        description="True if the chunk primarily introduces/defines a concept",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="Prerequisite topics needed to understand this chunk",
    )
    summary: str = Field(
        ..., description="One-sentence description of what the chunk teaches"
    )


class RawChunk(BaseModel):
    """A chunk of text extracted from a PDF before LLM analysis."""

    text: str
    page_start: int
    page_end: int
    chunk_index: int
    book_stem: str

    @property
    def chunk_id(self) -> str:
        return f"{self.book_stem}_{self.page_start}_{self.chunk_index}"


class IndexedChunk(BaseModel):
    """A fully processed chunk ready for ChromaDB storage."""

    chunk_id: str
    raw_text: str
    embedding: list[float] | None = None
    topic: str
    difficulty: str
    is_definitional: bool
    depends_on: list[str] = Field(default_factory=list)
    summary: str
    book: str
    course: str
    page_start: int
    page_end: int
    chunk_index: int


# ── RAG Models ────────────────────────────────────────────────────


class RAGQuery(BaseModel):
    """Input contract for the RAG engine."""

    question: str
    course: str | None = None
    topic: str | None = None
    difficulty: str | None = None
    top_k: int = 5


class SourceChunk(BaseModel):
    """A single retrieved source used in a RAG answer."""

    chunk_id: str
    text: str
    book: str
    page_start: int
    page_end: int
    relevance_score: float
    topic: str
    difficulty: str


class RAGResponse(BaseModel):
    """Output contract from the RAG engine."""

    answer: str
    sources: list[SourceChunk]
    question: str
