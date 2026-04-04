"""ChromaDB retrieval with optional metadata filters.

Builds ChromaDB ``where`` clauses from RAGQuery filters and returns
parsed SourceChunk objects.
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from src.indexing.store import VectorStore
from src.models.schemas import RAGQuery, SourceChunk

logger = structlog.get_logger(__name__)


class Retriever:
    """Queries ChromaDB by semantic similarity with optional metadata filters."""

    def __init__(self, store: VectorStore) -> None:
        self.store = store

    def retrieve(
        self,
        query_embedding: list[float],
        query: RAGQuery,
    ) -> list[SourceChunk]:
        """Retrieve the top-k most similar chunks for *query*.

        Parameters
        ----------
        query_embedding:
            Pre-computed embedding of the student question.
        query:
            Typed query with optional course/topic/difficulty filters.

        Returns
        -------
        list[SourceChunk]
            Ranked list of source chunks, closest first.
        """
        filters = self._build_filters(query)

        results = self.store.query(
            embedding=query_embedding,
            filters=filters,
            top_k=query.top_k,
        )

        return self._parse_results(results)

    # ── Filter construction ──────────────────────────────────────

    @staticmethod
    def _build_filters(query: RAGQuery) -> dict[str, Any] | None:
        """Translate optional RAGQuery fields into a ChromaDB ``where`` clause."""
        conditions: list[dict[str, Any]] = []

        if query.course:
            conditions.append({"course": query.course})
        if query.topic:
            conditions.append({"topic": query.topic})
        if query.difficulty:
            conditions.append({"difficulty": query.difficulty})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    # ── Result parsing ───────────────────────────────────────────

    @staticmethod
    def _parse_results(results: dict[str, Any]) -> list[SourceChunk]:
        """Convert raw ChromaDB results into typed SourceChunk objects."""
        sources: list[SourceChunk] = []

        if not results["ids"] or not results["ids"][0]:
            return sources

        ids = results["ids"][0]
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]

        for chunk_id, text, meta, distance in zip(
            ids, docs, metas, distances
        ):
            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            # Convert to a 0-1 relevance score
            relevance = max(0.0, 1.0 - distance / 2.0)

            # Deserialize depends_on if present (not needed for SourceChunk
            # but keeps metadata consistent)
            _ = json.loads(meta.get("depends_on", "[]"))

            sources.append(
                SourceChunk(
                    chunk_id=chunk_id,
                    text=text,
                    book=meta.get("book", ""),
                    page_start=meta.get("page_start", 0),
                    page_end=meta.get("page_end", 0),
                    relevance_score=round(relevance, 4),
                    topic=meta.get("topic", ""),
                    difficulty=meta.get("difficulty", ""),
                )
            )

        logger.info("retrieval_complete", n_sources=len(sources))
        return sources
