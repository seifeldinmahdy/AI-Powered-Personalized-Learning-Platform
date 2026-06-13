"""ChromaDB vector store operations.

Handles collection management, chunk existence checks (for resumability),
batch inserts, and semantic queries with optional metadata filters.
"""

from __future__ import annotations

import json
from typing import Any

import chromadb
import structlog

from src.models.schemas import IndexedChunk

logger = structlog.get_logger(__name__)


class VectorStore:
    """Persistent ChromaDB wrapper for the course_chunks collection.

    The same collection serves two query patterns:
      1. Pathway Generator  →  metadata-filtered queries
      2. Conversational RAG  →  semantic similarity queries
    """

    def __init__(self, persist_dir: str, collection_name: str) -> None:
        logger.info(
            "vectorstore_init",
            persist_dir=persist_dir,
            collection=collection_name,
        )
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "vectorstore_ready",
            collection=collection_name,
            existing_count=self.collection.count(),
        )

    # ── Existence checks (resumability) ──────────────────────────

    def get_existing_ids(self, chunk_ids: list[str]) -> set[str]:
        """Return the subset of *chunk_ids* that already exist."""
        if not chunk_ids:
            return set()
        try:
            results = self.collection.get(ids=chunk_ids, include=[])
            return set(results["ids"])
        except Exception as exc:
            logger.warning(
                "existence_check_error",
                error=str(exc),
                count=len(chunk_ids),
            )
            return set()

    # ── Writes ───────────────────────────────────────────────────

    def add_chunks(self, chunks: list[IndexedChunk]) -> None:
        """Batch-insert fully processed chunks into ChromaDB.

        ``depends_on`` is JSON-serialized because ChromaDB metadata
        values must be scalar types (str, int, float, bool).
        """
        if not chunks:
            return

        ids = [c.chunk_id for c in chunks]
        documents = [c.raw_text for c in chunks]
        embeddings = [c.embedding for c in chunks]
        metadatas = [
            {
                "topic": c.topic,
                "difficulty": c.difficulty,
                "is_definitional": c.is_definitional,
                "depends_on": json.dumps(c.depends_on),
                "summary": c.summary,
                "book": c.book,
                "course": c.course,
                "page_start": c.page_start,
                "page_end": c.page_end,
                "chunk_index": c.chunk_index,
            }
            for c in chunks
        ]

        self.collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        logger.info("chunks_stored", count=len(chunks))

    # ── Reads / Queries ──────────────────────────────────────────

    def query(
        self,
        embedding: list[float],
        filters: dict[str, Any] | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Semantic similarity query with optional metadata filters.

        Returns the raw ChromaDB query result dict with keys:
        ids, documents, metadatas, distances.
        """
        kwargs: dict[str, Any] = {
            "query_embeddings": [embedding],
            "n_results": top_k,
            "include": ["documents", "metadatas", "distances"],
        }
        if filters:
            kwargs["where"] = filters

        logger.info("vectorstore_query", top_k=top_k, filters=filters)
        results = self.collection.query(**kwargs)
        n_found = len(results["ids"][0]) if results["ids"] else 0
        logger.info("vectorstore_query_results", n_found=n_found)
        return results

    def get_where(
        self,
        where: dict[str, Any] | None = None,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        """Metadata-filtered fetch (no embedding/similarity).

        Thin wrapper over ``collection.get`` so callers (RetrievalService)
        never touch the raw collection. ``where`` is a ChromaDB filter clause.
        """
        kwargs: dict[str, Any] = {}
        if where:
            kwargs["where"] = where
        kwargs["include"] = include if include is not None else ["documents", "metadatas"]
        return self.collection.get(**kwargs)

    def get_by_ids(
        self,
        ids: list[str],
        where: dict[str, Any] | None = None,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch specific chunk ids, optionally constrained by a ``where`` clause.

        The ``where`` constraint lets callers enforce a scope (e.g. corpus_id)
        even when fetching by id, so an id from another corpus can never leak.
        """
        if not ids:
            return {"ids": [], "documents": [], "metadatas": []}
        kwargs: dict[str, Any] = {"ids": ids}
        if where:
            kwargs["where"] = where
        kwargs["include"] = include if include is not None else ["documents", "metadatas"]
        return self.collection.get(**kwargs)

    def count_where(self, where: dict[str, Any] | None = None) -> int:
        """Return the number of chunks matching *where* (scope-aware count)."""
        if not where:
            return self.collection.count()
        res = self.collection.get(where=where, include=[])
        return len(res.get("ids", []))

    def update_metadata(
        self,
        ids: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Update metadata on existing chunks in place (no re-embedding).

        Used by the corpus backfill to stamp ``corpus_id`` / ``course_id``
        onto already-indexed chunks without re-running the indexing pipeline.
        """
        if not ids:
            return
        self.collection.update(ids=ids, metadatas=metadatas)
        logger.info("chunk_metadata_updated", count=len(ids))

    def get_all_metadata_values(self, field: str) -> list[str]:
        """Return distinct values for a metadata field across all chunks.

        Useful for populating UI filter dropdowns.
        """
        all_data = self.collection.get(include=["metadatas"])
        values: set[str] = set()
        for meta in all_data["metadatas"]:
            val = meta.get(field)
            if val is not None:
                values.add(str(val))
        return sorted(values)

    @property
    def count(self) -> int:
        """Total number of chunks in the collection."""
        return self.collection.count()
