"""Scoped, read-only adapter over the shared vector store.

Every read goes through the single :class:`RetrievalService` and is constrained
by a :class:`RetrievalScope` (corpus_id). This adapter maps the neutral
``RetrievedChunk`` to the pathway-specific :class:`CourseChunk` so the pathway
generator/discovery code is unchanged, while all store access + scope filtering
live in one place.

No new collection is created. No writes. No re-indexing.

Batch 4 breadcrumb: corpus-aware INGESTION (tagging chunks with corpus_id at
index time, non-optional concept tagging) lands later. Until then existing
vectors are stamped with corpus_id by the ``backfill_corpus_vector_tags``
management command, and this reader filters on that tag.
"""

from __future__ import annotations

import sys
from pathlib import Path

import structlog

from pathway.models.schemas import CourseChunk

logger = structlog.get_logger(__name__)


def _ensure_rag_pipeline_on_path() -> None:
    """Add rag_pipeline to sys.path so RetrievalService/VectorStore import."""
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    rag_dir = str(project_root / "rag_pipeline")
    if rag_dir not in sys.path:
        sys.path.insert(0, rag_dir)


class ChromaDBReader:
    """Pathway-facing adapter over :class:`RetrievalService`.

    Parameters
    ----------
    persist_dir:
        Absolute path to the ChromaDB persistent storage directory.
    collection_name:
        Name of the existing collection (default ``course_chunks``).
    """

    def __init__(self, persist_dir: str, collection_name: str = "course_chunks") -> None:
        if not Path(persist_dir).exists():
            raise FileNotFoundError(
                f"ChromaDB directory not found: {persist_dir}. "
                "Run the RAG indexing pipeline first."
            )

        _ensure_rag_pipeline_on_path()
        from src.indexing.store import VectorStore  # type: ignore
        from src.retrieval.retrieval_service import RetrievalService  # type: ignore

        store = VectorStore(persist_dir=persist_dir, collection_name=collection_name)
        self._service = RetrievalService(store=store)
        logger.info(
            "chromadb_reader_ready",
            persist_dir=persist_dir,
            collection=collection_name,
            count=store.count,
        )

    # ── Scoped API (used by the pathway generator) ───────────────────

    def get_all_chunks(self, scope) -> list[CourseChunk]:
        """Every chunk in *scope*, ordered by chunk_index, as CourseChunk."""
        return [self._to_course_chunk(c) for c in self._service.get_all_chunks(scope)]

    def get_chunks_by_ids(self, scope, ids: list[str]) -> list[CourseChunk]:
        """Specific chunk ids constrained to *scope*, as CourseChunk."""
        return [
            self._to_course_chunk(c)
            for c in self._service.get_chunks_by_ids(scope, ids)
        ]

    def get_topics(self, scope) -> list[str]:
        return self._service.get_topics(scope)

    def get_topic_summary(self, scope) -> dict[str, int]:
        return self._service.get_topic_summary(scope)

    def resolve_course(self, course_id: str, course_title: str = "") -> str:
        """Map an external course identifier to a ChromaDB ``course`` value.

        ChromaDB stores chunks keyed by their source-book name (e.g.
        "Think Python 2nd Edition"), while the platform identifies courses by
        a numeric Django id (e.g. "11") and a human title. This resolves the
        best-matching book so chunk queries actually hit data.

        Resolution order:
          1. Exact match on ``course_id`` (legacy: id already *is* the book).
          2. Case-insensitive exact match on ``course_id`` or ``course_title``.
          3. Fuzzy match on ``course_title`` (keyword overlap + sequence ratio).

        Returns the original ``course_id`` unchanged if nothing matches, so the
        caller still raises a clear "no chunks" error rather than guessing.
        """
        import re
        from difflib import SequenceMatcher

        available = self.get_available_courses()
        if not available:
            return course_id

        # 1. Exact id match (the original design, where id == book name)
        if course_id in available:
            return course_id

        # 2. Case-insensitive exact match on id or title
        lower_map = {c.lower(): c for c in available}
        for candidate in (course_id, course_title):
            if candidate and candidate.lower() in lower_map:
                return lower_map[candidate.lower()]

        # 3. Fuzzy match on the human title (the only meaningful signal —
        #    a numeric id carries no lexical overlap with a book name)
        if not course_title:
            return course_id

        def _normalise(s: str) -> str:
            return re.sub(r"[^a-z0-9 ]", " ", s.lower()).strip()

        def _tokens(s: str) -> set[str]:
            return {w for w in _normalise(s).split() if len(w) > 2}

        title_tokens = _tokens(course_title)
        best_match = course_id
        best_score = 0.0

        for book in available:
            book_tokens = _tokens(book)
            if title_tokens and book_tokens:
                overlap = len(title_tokens & book_tokens) / len(title_tokens | book_tokens)
            else:
                overlap = 0.0
            seq_ratio = SequenceMatcher(
                None, _normalise(course_title), _normalise(book)
            ).ratio()
            score = 0.6 * overlap + 0.4 * seq_ratio
            if score > best_score:
                best_score = score
                best_match = book

        # Require a minimal signal before trusting the guess
        if best_score < 0.15:
            logger.warning(
                "course_resolution_low_confidence",
                course_id=course_id,
                course_title=course_title,
                best_match=best_match,
                score=round(best_score, 3),
            )
            return course_id

        logger.info(
            "course_resolved",
            course_id=course_id,
            course_title=course_title,
            resolved=best_match,
            score=round(best_score, 3),
        )
        return best_match

    def get_chunks_for_concept(self, scope, concept_id: str) -> list[CourseChunk]:
        """Chunks in *scope* tagged with *concept_id*, as CourseChunk."""
        return [
            self._to_course_chunk(c)
            for c in self._service.get_chunks_for_concept(scope, concept_id)
        ]

    def get_topics_by_difficulty(self, scope, difficulty: str) -> list[str]:
        return self._service.get_topics_by_difficulty(scope, difficulty)

    def count(self, scope) -> int:
        return self._service.count(scope)

    # ── Introspection (health / dev tooling) ─────────────────────────

    def list_corpus_ids(self) -> list[str]:
        """Distinct corpus_id values present in the collection (no chunk content)."""
        res = self._service._store.get_where(None, include=["metadatas"])
        ids = {m.get("corpus_id") for m in res.get("metadatas", []) if m.get("corpus_id")}
        return sorted(ids)

    @property
    def chunk_count(self) -> int:
        """Total chunks across all corpora (health only)."""
        return self._service._store.count

    # ── Deprecated compatibility shims (dev testers / ad-hoc scripts) ─
    # These keep streamlit testers and one-off scripts working. They still
    # REQUIRE a corpus identity (the string arg is treated as corpus_id) and
    # filter on it — there is no unscoped retrieval path.

    def _scope(self, corpus_id: str):
        from src.retrieval.retrieval_service import RetrievalScope  # type: ignore
        return RetrievalScope(corpus_id=corpus_id)

    def get_all_course_chunks(self, corpus_id: str) -> list[CourseChunk]:
        """Deprecated: pass a corpus_id. Use :meth:`get_all_chunks` with a scope."""
        return self.get_all_chunks(self._scope(corpus_id))

    def get_course_topics(self, corpus_id: str) -> list[str]:
        """Deprecated: pass a corpus_id."""
        return self.get_topics(self._scope(corpus_id))

    def get_available_courses(self) -> list[str]:
        """Deprecated alias for :meth:`list_corpus_ids`."""
        return self.list_corpus_ids()

    # ── Mapping ──────────────────────────────────────────────────────

    @staticmethod
    def _to_course_chunk(c) -> CourseChunk:
        return CourseChunk(
            chunk_id=c.chunk_id,
            raw_text=c.raw_text,
            topic=c.topic,
            difficulty=c.difficulty,
            is_definitional=c.is_definitional,
            depends_on=c.depends_on,
            summary=c.summary,
            book=c.book,
            course=c.course_id or c.corpus_id,
            concept_id=getattr(c, "concept_id", "") or "",
            page_start=c.page_start,
            page_end=c.page_end,
            chunk_index=c.chunk_index,
        )
