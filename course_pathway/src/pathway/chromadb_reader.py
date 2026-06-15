"""Read-only adapter over the existing rag_pipeline VectorStore.

Provides typed access to ChromaDB chunk data without modifying the
collection.  Shares the same PersistentClient path and collection
name used by the Conversational RAG Agent.

No new collection is created.  No writes.  No re-indexing.
"""

from __future__ import annotations

import json
from pathlib import Path

import chromadb
import structlog

from pathway.models.schemas import CourseChunk

logger = structlog.get_logger(__name__)


class ChromaDBReader:
    """Read-only interface to the shared ``course_chunks`` collection.

    Parameters
    ----------
    persist_dir:
        Absolute path to the ChromaDB persistent storage directory.
    collection_name:
        Name of the existing collection (default ``course_chunks``).
    """

    def __init__(self, persist_dir: str, collection_name: str = "course_chunks") -> None:
        logger.info(
            "chromadb_reader_init",
            persist_dir=persist_dir,
            collection=collection_name,
        )

        if not Path(persist_dir).exists():
            raise FileNotFoundError(
                f"ChromaDB directory not found: {persist_dir}. "
                "Run the RAG indexing pipeline first."
            )

        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        count = self._collection.count()
        logger.info("chromadb_reader_ready", count=count)

    # ── Read-only queries ────────────────────────────────────────

    def get_all_course_chunks(self, course_id: str) -> list[CourseChunk]:
        """Retrieve every chunk belonging to *course_id* with full metadata.

        Returns a list of ``CourseChunk`` objects ordered by ``chunk_index``.
        """
        results = self._collection.get(
            where={"course": course_id},
            include=["documents", "metadatas"],
        )

        if not results["ids"]:
            logger.warning("no_chunks_for_course", course_id=course_id)
            return []

        chunks: list[CourseChunk] = []
        for chunk_id, doc, meta in zip(
            results["ids"],
            results["documents"],
            results["metadatas"],
        ):
            depends_on_raw = meta.get("depends_on", "[]")
            if isinstance(depends_on_raw, str):
                try:
                    depends_on = json.loads(depends_on_raw)
                except json.JSONDecodeError:
                    depends_on = []
            elif isinstance(depends_on_raw, list):
                depends_on = depends_on_raw
            else:
                depends_on = []

            chunks.append(
                CourseChunk(
                    chunk_id=chunk_id,
                    raw_text=doc,
                    topic=meta.get("topic", "unknown"),
                    difficulty=meta.get("difficulty", "beginner"),
                    is_definitional=bool(meta.get("is_definitional", False)),
                    depends_on=[str(d) for d in depends_on],
                    summary=meta.get("summary", ""),
                    book=meta.get("book", ""),
                    course=meta.get("course", course_id),
                    page_start=int(meta.get("page_start", 0)),
                    page_end=int(meta.get("page_end", 0)),
                    chunk_index=int(meta.get("chunk_index", 0)),
                )
            )

        # Sort by chunk_index to preserve book order
        chunks.sort(key=lambda c: c.chunk_index)

        logger.info(
            "course_chunks_loaded",
            course_id=course_id,
            count=len(chunks),
        )
        return chunks

    def get_course_topics(self, course_id: str) -> list[str]:
        """Return distinct topic strings for a course."""
        results = self._collection.get(
            where={"course": course_id},
            include=["metadatas"],
        )

        topics: set[str] = set()
        for meta in results["metadatas"]:
            topic = meta.get("topic")
            if topic:
                topics.add(topic)

        return sorted(topics)

    def get_topic_summary(self, course_id: str) -> dict[str, int]:
        """Return topic → chunk_count mapping for a course.

        Useful for giving the LLM a sense of how much material
        exists per topic when designing the curriculum.
        """
        results = self._collection.get(
            where={"course": course_id},
            include=["metadatas"],
        )

        counts: dict[str, int] = {}
        for meta in results["metadatas"]:
            topic = meta.get("topic")
            if topic:
                counts[topic] = counts.get(topic, 0) + 1

        return counts

    def get_available_courses(self) -> list[str]:
        """Return a sorted list of all course IDs in the collection."""
        all_data = self._collection.get(include=["metadatas"])
        courses: set[str] = set()
        for meta in all_data["metadatas"]:
            course = meta.get("course")
            if course:
                courses.add(course)
        return sorted(courses)

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

    def get_topics_by_difficulty(
        self, course_id: str, difficulty: str,
    ) -> list[str]:
        """Return distinct topic strings for a course filtered by difficulty.

        Parameters
        ----------
        course_id:
            Course identifier.
        difficulty:
            Difficulty tier: 'beginner', 'intermediate', or 'expert'.
        """
        results = self._collection.get(
            where={"$and": [{"course": course_id}, {"difficulty": difficulty}]},
            include=["metadatas"],
        )

        topics: set[str] = set()
        for meta in results["metadatas"]:
            topic = meta.get("topic")
            if topic:
                topics.add(topic)

        return sorted(topics)

    @property
    def chunk_count(self) -> int:
        """Total number of chunks across all courses."""
        return self._collection.count()
