"""RetrievalService — the single, scope-enforcing access path to the vector store.

Every consumer (pathway generator, slides/session-chunk feed, assessment topic
read, and — in Batch 3 — RAG/tutor) MUST go through this service. Every method
REQUIRES a :class:`RetrievalScope` and applies the scope filter internally, so
no caller can retrieve chunks without a corpus identity.

Collection strategy (chosen: single collection, metadata-filtered)
------------------------------------------------------------------
All corpora live in one ChromaDB collection (``course_chunks``); isolation is
enforced by a MANDATORY ``corpus_id`` filter injected here. This is the only
place a ChromaDB ``where`` clause is built, so the scope can never be forgotten.
We chose this over one-collection-per-corpus because the existing data is a
single collection (backfill = add metadata in place, not recopy every chunk),
and the choke-point design gives the same guarantee in practice (proven by the
A/B leakage test). The public API here is collection-strategy-agnostic: a future
switch to per-corpus collections would change only the store wiring below, not a
single caller.

Scope identity
--------------
``corpus_id`` is a STABLE, admin-defined handle (Django ``CourseCorpus.corpus_id``)
that does NOT overload the Django ``course_id`` string or the book filename. The
mapping ``course_id -> corpus_id`` is resolved upstream (see
``pathway.corpus_resolver``); this module only consumes the resolved scope.

Batch 4 breadcrumb
------------------
The corpus-aware INGESTION rework (tagging chunks with corpus_id/course_id at
index time, and making ``concept_id`` tagging non-optional) lands in Batch 4.
Until then, existing vectors are stamped with corpus_id by the
``backfill_corpus_vector_tags`` management command; this service reads that tag.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import structlog

from src.indexing.store import VectorStore
from src.models.schemas import SourceChunk

logger = structlog.get_logger(__name__)


class ScopeError(ValueError):
    """Raised when a retrieval is attempted without a valid corpus scope."""


@dataclass(frozen=True)
class RetrievalScope:
    """The mandatory retrieval scope.

    Parameters
    ----------
    corpus_id:
        The authoritative scope key. Required — retrieval without it is refused.
    course_id:
        The Django course id, carried for logging/diagnostics only. It is NEVER
        used as a filter (that would re-introduce the overloaded-identifier bug).
    """

    corpus_id: str
    course_id: str | None = None

    def validate(self) -> None:
        if not self.corpus_id or not str(self.corpus_id).strip():
            raise ScopeError(
                "RetrievalScope.corpus_id is required — refusing to query the "
                "vector store without a corpus scope."
            )

    @property
    def membership_key(self) -> str:
        """Flat metadata key flagging chunk membership in THIS corpus.

        Membership is a per-corpus flag (``corpus__<corpus_id> = "1"``) rather than
        a single stamped ``corpus_id``, so one book's chunks can belong to many
        corpora at once (a book selected into multiple courses). Detached chunks
        carry ``"0"`` (or no key) and are excluded by the ``= "1"`` filter.
        """
        return f"corpus__{self.corpus_id}"

    def concept_key(self) -> str:
        """Flat metadata key holding this corpus's concept tag for a chunk.

        Concepts are per-course, so a shared book is tagged independently per
        corpus (``concept__<corpus_id> = "<concept_id>"``).
        """
        return f"concept__{self.corpus_id}"

    def where(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """Build the ``where`` clause for this scope (+ optional extras).

        Scopes on the per-corpus membership flag, so retrieval only ever returns
        chunks selected into this corpus — never the whole table.
        """
        base = {self.membership_key: "1"}
        if not extra:
            return base
        conditions = [{k: v} for k, v in {**base, **extra}.items()]
        return {"$and": conditions}


@dataclass
class RetrievedChunk:
    """Neutral, scope-tagged chunk returned by RetrievalService.

    A superset of the metadata every consumer needs; each consumer maps this to
    its own schema (pathway ``CourseChunk``, RAG ``SourceChunk``, …).
    """

    chunk_id: str
    raw_text: str
    topic: str
    difficulty: str
    is_definitional: bool
    depends_on: list[str]
    summary: str
    book: str
    corpus_id: str
    course_id: str
    concept_id: str
    page_start: int
    page_end: int
    chunk_index: int
    relevance_score: float | None = None


def _parse_depends_on(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(d) for d in raw]
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
            return [str(d) for d in val] if isinstance(val, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _chunk_from_meta(chunk_id: str, doc: str, meta: dict[str, Any],
                     relevance: float | None = None,
                     corpus_id: str | None = None) -> RetrievedChunk:
    # Concept is per-corpus (``concept__<corpus_id>``); fall back to the legacy
    # scalar ``concept_id`` for not-yet-migrated chunks.
    concept = ""
    if corpus_id:
        concept = str(meta.get(f"concept__{corpus_id}", "") or "")
    if not concept:
        concept = str(meta.get("concept_id", "") or "")
    return RetrievedChunk(
        chunk_id=chunk_id,
        raw_text=doc or "",
        topic=meta.get("topic", "unknown"),
        difficulty=meta.get("difficulty", "beginner"),
        is_definitional=bool(meta.get("is_definitional", False)),
        depends_on=_parse_depends_on(meta.get("depends_on", "[]")),
        summary=meta.get("summary", ""),
        book=meta.get("book", ""),
        corpus_id=str(corpus_id or meta.get("corpus_id", "")),
        course_id=str(meta.get("course_id", meta.get("course", ""))),
        concept_id=concept,
        page_start=int(meta.get("page_start", 0)),
        page_end=int(meta.get("page_end", 0)),
        chunk_index=int(meta.get("chunk_index", 0)),
        relevance_score=relevance,
    )


class RetrievalService:
    """Scope-enforcing facade over the vector store.

    Parameters
    ----------
    store:
        A :class:`VectorStore` bound to the shared collection.
    embedder:
        Optional embedder; only required for :meth:`semantic_search`.
    """

    def __init__(self, store: VectorStore, embedder: Any | None = None) -> None:
        self._store = store
        self._embedder = embedder

    # ── Metadata reads (pathway, assessment, session-chunks) ─────────

    def get_all_chunks(self, scope: RetrievalScope) -> list[RetrievedChunk]:
        """Return every chunk in *scope*, ordered by ``chunk_index``."""
        scope.validate()
        res = self._store.get_where(scope.where(), include=["documents", "metadatas"])
        chunks = self._rows_to_chunks(res, scope.corpus_id)
        chunks.sort(key=lambda c: c.chunk_index)
        logger.info("retrieval_get_all_chunks", corpus_id=scope.corpus_id, count=len(chunks))
        return chunks

    def get_chunks_by_ids(
        self, scope: RetrievalScope, ids: list[str],
    ) -> list[RetrievedChunk]:
        """Fetch specific chunk ids, constrained to *scope*.

        Ids belonging to another corpus are silently dropped (the scope filter
        excludes them), so a stale/foreign id can never leak across corpora.
        """
        scope.validate()
        if not ids:
            return []
        res = self._store.get_by_ids(ids, where=scope.where(),
                                     include=["documents", "metadatas"])
        return self._rows_to_chunks(res, scope.corpus_id)

    def get_topics(self, scope: RetrievalScope) -> list[str]:
        """Distinct topic strings within *scope*."""
        scope.validate()
        res = self._store.get_where(scope.where(), include=["metadatas"])
        topics = {m.get("topic") for m in res.get("metadatas", []) if m.get("topic")}
        return sorted(topics)

    def get_topic_summary(self, scope: RetrievalScope) -> dict[str, int]:
        """topic → chunk_count within *scope*."""
        scope.validate()
        res = self._store.get_where(scope.where(), include=["metadatas"])
        counts: dict[str, int] = {}
        for m in res.get("metadatas", []):
            topic = m.get("topic")
            if topic:
                counts[topic] = counts.get(topic, 0) + 1
        return counts

    def get_topics_by_difficulty(
        self, scope: RetrievalScope, difficulty: str,
    ) -> list[str]:
        """Distinct topics within *scope* filtered by difficulty tier."""
        scope.validate()
        res = self._store.get_where(
            scope.where({"difficulty": difficulty}), include=["metadatas"],
        )
        topics = {m.get("topic") for m in res.get("metadatas", []) if m.get("topic")}
        return sorted(topics)

    def get_chunks_for_concept(
        self, scope: RetrievalScope, concept_id: str,
    ) -> list[RetrievedChunk]:
        """Every chunk in *scope* tagged with *concept_id*, ordered by index.

        Used by backward-designed assessment generation (probe the CLO concept
        set) and concept-keyed slide grounding. Corpus scope is still enforced.
        """
        scope.validate()
        res = self._store.get_where(
            scope.where({scope.concept_key(): str(concept_id)}),
            include=["documents", "metadatas"],
        )
        chunks = self._rows_to_chunks(res, scope.corpus_id)
        chunks.sort(key=lambda c: c.chunk_index)
        return chunks

    def get_concept_chunk_counts(self, scope: RetrievalScope) -> dict[str, int]:
        """concept_id → chunk_count within *scope* (untagged chunks excluded)."""
        scope.validate()
        res = self._store.get_where(scope.where(), include=["metadatas"])
        ckey = scope.concept_key()
        counts: dict[str, int] = {}
        for m in res.get("metadatas", []):
            cid = m.get(ckey) or m.get("concept_id")
            if cid:
                counts[str(cid)] = counts.get(str(cid), 0) + 1
        return counts

    def count(self, scope: RetrievalScope) -> int:
        """Number of chunks in *scope*. ``0`` means the corpus is empty."""
        scope.validate()
        return self._store.count_where(scope.where())

    # ── Semantic search (wired to RAG/tutor in Batch 3) ──────────────

    def semantic_search(
        self,
        scope: RetrievalScope,
        query: str | None = None,
        query_embedding: list[float] | None = None,
        topic: str | None = None,
        difficulty: str | None = None,
        concept_id: str | None = None,
        top_k: int = 5,
    ) -> list[RetrievedChunk]:
        """Scoped semantic similarity search.

        Always applies the corpus filter, so retrieval can never cross courses.
        An optional ``concept_id`` narrows to a single concept's chunks.
        """
        scope.validate()
        if query_embedding is None:
            if query is None or self._embedder is None:
                raise ValueError(
                    "semantic_search requires either query_embedding or "
                    "(query + an embedder configured on RetrievalService)."
                )
            query_embedding = self._embedder.embed_single(query)

        extra: dict[str, Any] = {}
        if topic:
            extra["topic"] = topic
        if difficulty:
            extra["difficulty"] = difficulty
        if concept_id:
            extra[scope.concept_key()] = str(concept_id)

        results = self._store.query(
            embedding=query_embedding,
            filters=scope.where(extra or None),
            top_k=top_k,
        )
        return self._query_results_to_chunks(results, scope.corpus_id)

    def to_source_chunks(self, chunks: list[RetrievedChunk]) -> list[SourceChunk]:
        """Adapter: RetrievedChunk → rag_pipeline SourceChunk (for Batch 3)."""
        return [
            SourceChunk(
                chunk_id=c.chunk_id,
                text=c.raw_text,
                book=c.book,
                page_start=c.page_start,
                page_end=c.page_end,
                relevance_score=c.relevance_score or 0.0,
                topic=c.topic,
                difficulty=c.difficulty,
            )
            for c in chunks
        ]

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _rows_to_chunks(res: dict[str, Any], corpus_id: str | None = None) -> list[RetrievedChunk]:
        ids = res.get("ids", []) or []
        docs = res.get("documents", []) or [""] * len(ids)
        metas = res.get("metadatas", []) or [{}] * len(ids)
        return [
            _chunk_from_meta(cid, doc, meta or {}, corpus_id=corpus_id)
            for cid, doc, meta in zip(ids, docs, metas)
        ]

    @staticmethod
    def _query_results_to_chunks(results: dict[str, Any], corpus_id: str | None = None) -> list[RetrievedChunk]:
        if not results.get("ids") or not results["ids"][0]:
            return []
        ids = results["ids"][0]
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]
        out: list[RetrievedChunk] = []
        for cid, doc, meta, dist in zip(ids, docs, metas, distances):
            relevance = round(max(0.0, 1.0 - dist / 2.0), 4)
            out.append(_chunk_from_meta(cid, doc, meta or {}, relevance=relevance, corpus_id=corpus_id))
        return out
