"""Top-level pathway generator orchestrator.

Wires together the top-down LLM curriculum design pipeline:
    ChromaDB (topics) → LLM Curriculum Design → Chunk Retrieval →
    Personalizer → SessionGrouper → Validation → PlanStore

A single call to ``PathwayGenerator.generate()`` runs the full pipeline
and returns a ``PathwayResponse``.
"""

from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher

import structlog

from pathway.chromadb_reader import ChromaDBReader
from pathway.config import PathwaySettings
from pathway.llm.curriculum import design_curriculum
from pathway.llm.naming import OllamaClient, validate_sequence
from pathway.models.schemas import (
    CourseChunk,
    DiscoveredSection,
    LLMCurriculumSession,
    PathwayResponse,
    Session,
    SessionPlan,
    StudentContext,
)
from pathway.models.synthetic import SyntheticContextGenerator
from pathway.personalization.personalizer import Personalizer
from pathway.session.grouper import SessionGrouper
from pathway.storage.plan_store import PlanStore

logger = structlog.get_logger(__name__)

# ── Topic matching ───────────────────────────────────────────────

_STRIP_RE = re.compile(r"[^a-z0-9\s]")


def _normalise(raw: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    normed = raw.lower().strip()
    normed = _STRIP_RE.sub("", normed)
    return re.sub(r"\s+", " ", normed).strip()


def _find_chunks_for_topic(
    topic: str,
    chunks_by_topic: dict[str, list[CourseChunk]],
) -> list[CourseChunk]:
    """Find chunks matching *topic* using exact then fuzzy matching."""
    # Exact match
    if topic in chunks_by_topic:
        return chunks_by_topic[topic]

    # Normalised exact match
    topic_n = _normalise(topic)
    for key, chunks in chunks_by_topic.items():
        if _normalise(key) == topic_n:
            return chunks

    # Fuzzy match
    best_score = 0.0
    best_key: str | None = None
    for key in chunks_by_topic:
        score = SequenceMatcher(None, topic_n, _normalise(key)).ratio()
        if score > best_score and score >= 0.80:
            best_score = score
            best_key = key

    if best_key:
        return chunks_by_topic[best_key]

    return []


class PathwayGenerator:
    """Full pipeline orchestrator using top-down LLM curriculum design.

    Parameters
    ----------
    settings:
        Resolved ``PathwaySettings`` instance.
    reader:
        Pre-initialised ``ChromaDBReader``.
    store:
        Pre-initialised ``PlanStore``.
    llm_client:
        Configured ``OllamaClient`` (may be None to skip LLM steps).
    """

    def __init__(
        self,
        settings: PathwaySettings,
        reader: ChromaDBReader,
        store: PlanStore,
        llm_client: OllamaClient | None = None,
    ) -> None:
        self._settings = settings
        self._reader = reader
        self._store = store
        self._llm = llm_client

        self._personalizer = Personalizer()
        self._grouper = SessionGrouper(
            max_sessions=settings.max_sessions,
            target_sessions=settings.target_session_count,
        )
        self._synthetic_gen = SyntheticContextGenerator()

    @staticmethod
    def _build_scope(context: StudentContext):
        """Build the required RetrievalScope from the student context.

        Raises ``ValueError`` if no corpus_id was resolved — retrieval must
        never run unscoped.
        """
        import sys
        from pathlib import Path

        rag_dir = str(Path(__file__).resolve().parent.parent.parent.parent / "rag_pipeline")
        if rag_dir not in sys.path:
            sys.path.insert(0, rag_dir)
        from src.retrieval.retrieval_service import RetrievalScope  # type: ignore

        if not context.corpus_id:
            raise ValueError(
                f"No corpus_id resolved for course_id='{context.course_id}'. "
                f"Cannot generate a pathway without a corpus scope."
            )
        return RetrievalScope(corpus_id=context.corpus_id, course_id=context.course_id)

    def generate(
        self,
        context: StudentContext,
        force_regenerate: bool = False,
    ) -> PathwayResponse:
        """Generate (or retrieve cached) a personalized session plan.

        Parameters
        ----------
        context:
            Student context with mastery, strengths, weaknesses.
        force_regenerate:
            If True, ignore cached plans and regenerate from scratch.

        Returns
        -------
        PathwayResponse
            Contains the ``SessionPlan`` and a ``cached`` flag.
        """
        ctx_hash = context.context_hash()

        # 1. Check cache (unless forced)
        if not force_regenerate:
            if not self._store.needs_regeneration(
                context.student_id, context.course_id, ctx_hash
            ):
                cached_plan = self._store.load(
                    context.student_id, context.course_id
                )
                if cached_plan is not None:
                    logger.info(
                        "pathway_served_from_cache",
                        student_id=context.student_id,
                        course_id=context.course_id,
                    )
                    return PathwayResponse(plan=cached_plan, cached=True)

        logger.info(
            "pathway_generation_start",
            student_id=context.student_id,
            course_id=context.course_id,
            corpus_id=context.corpus_id,
            mastery=context.mastery_level,
        )

        # 2. Load ALL chunks from ChromaDB — strictly scoped to this corpus
        scope = self._build_scope(context)
        chunks = self._reader.get_all_chunks(scope)
        if not chunks:
            # An empty result now means exactly one thing: this course's corpus
            # is empty (no silent cross-course fallback). Surface it clearly so
            # the admin knows to add sources / run the indexer + backfill.
            raise ValueError(
                f"Course corpus is empty: no chunks found for corpus_id="
                f"'{context.corpus_id}' (course_id='{context.course_id}'). "
                f"Add sources to this course's corpus and index them."
            )

        # 3. Synthetic context (if requested)
        if context.use_synthetic_context:
            topics = [c.topic for c in chunks]
            unique_topics = list(dict.fromkeys(topics))

            mastery_to_diff = {
                "Novice": "beginner",
                "Intermediate": "intermediate",
                "Expert": "expert",
            }
            diff_tier = mastery_to_diff.get(context.mastery_level, "intermediate")
            difficulty_topics = self._reader.get_topics_by_difficulty(
                scope, diff_tier
            )

            context = self._synthetic_gen.generate(
                student_id=context.student_id,
                course_id=context.course_id,
                available_topics=unique_topics,
                difficulty_topics=difficulty_topics,
                mastery_level=context.mastery_level,
            )
            ctx_hash = context.context_hash()

        # 4. Extract unique topic tags
        all_topics = list(dict.fromkeys(c.topic for c in chunks))

        # Build topic → chunks index
        chunks_by_topic: dict[str, list[CourseChunk]] = defaultdict(list)
        for chunk in chunks:
            chunks_by_topic[chunk.topic].append(chunk)

        book_titles = list({c.book for c in chunks})

        # 5. LLM designs curriculum (or fallback if no client)
        if self._llm is not None:
            curriculum = design_curriculum(
                client=self._llm,
                topics=all_topics,
                course_intent=context.course_intent,
                book_titles=book_titles,
                max_retries=self._settings.max_retries,
                timeout=self._settings.ollama_curriculum_timeout,
                target_sessions=self._settings.target_session_count,
                min_sessions=self._settings.min_sessions,
                max_sessions=self._settings.max_sessions,
            )
        else:
            # No LLM — simple alphabetical fallback
            from pathway.llm.curriculum import _alphabetical_fallback
            curriculum = _alphabetical_fallback(
                all_topics, target_sessions=self._settings.target_session_count
            )

        # 6. Build DiscoveredSections from the LLM curriculum
        sections, section_chunks_raw = self._build_sections_from_curriculum(
            curriculum, chunks_by_topic
        )

        # 7. Personalise (chunk selection per section)
        personalised_sections, section_chunks = self._personalizer.personalize(
            sections, chunks, context
        )

        # 8. Group into sessions (token budget)
        sessions = self._grouper.group_sessions(
            personalised_sections, section_chunks
        )

        # 9. Validate sequence (optional)
        if self._llm is not None and sessions:
            validation = validate_sequence(self._llm, sessions)
            logger.info("sequence_validation", result=validation)

        # 10. Build the plan
        plan = SessionPlan(
            student_id=context.student_id,
            course_id=context.course_id,
            sessions=sessions,
            total_sessions=len(sessions),
            total_chunks=sum(len(s.chunks) for s in sessions),
            student_context_hash=ctx_hash,
        )

        # 11. Persist
        self._store.save(plan)

        logger.info(
            "pathway_generation_complete",
            student_id=context.student_id,
            course_id=context.course_id,
            total_sessions=plan.total_sessions,
            total_chunks=plan.total_chunks,
        )

        return PathwayResponse(plan=plan, cached=False)

    def _build_sections_from_curriculum(
        self,
        curriculum: list[LLMCurriculumSession],
        chunks_by_topic: dict[str, list[CourseChunk]],
    ) -> tuple[list[DiscoveredSection], dict[str, list[CourseChunk]]]:
        """Convert LLM curriculum sessions into DiscoveredSections.

        For each session the LLM defined, creates a DiscoveredSection
        containing all chunks whose topic matches any of the session's
        topics. Chunks are ordered: definitional first, then by page_start.

        Parameters
        ----------
        curriculum:
            Sessions from the LLM curriculum designer.
        chunks_by_topic:
            topic string → list of CourseChunk.

        Returns
        -------
        tuple[list[DiscoveredSection], dict[str, list[CourseChunk]]]
            (sections, section_id → chunk list)
        """
        sections: list[DiscoveredSection] = []
        section_chunks_map: dict[str, list[CourseChunk]] = {}

        for llm_session in curriculum:
            section_id = f"sec_{llm_session.session_number:03d}"

            # Collect all chunks for this session's topics
            session_chunks: list[CourseChunk] = []
            for topic in llm_session.topics:
                matched = _find_chunks_for_topic(topic, chunks_by_topic)
                session_chunks.extend(matched)

            # Deduplicate by chunk_id (a chunk might be included twice)
            seen: set[str] = set()
            deduped: list[CourseChunk] = []
            for c in session_chunks:
                if c.chunk_id not in seen:
                    seen.add(c.chunk_id)
                    deduped.append(c)

            # Order: definitional first, then by page_start
            deduped.sort(key=lambda c: (not c.is_definitional, c.page_start))

            # Compute difficulty distribution
            diff_dist: dict[str, int] = defaultdict(int)
            for c in deduped:
                diff_dist[c.difficulty] += 1

            section = DiscoveredSection(
                section_id=section_id,
                canonical_topic=llm_session.session_title,
                display_title=llm_session.session_title,
                chunk_ids=[c.chunk_id for c in deduped],
                difficulty_distribution=dict(diff_dist),
                has_definitional_chunks=any(c.is_definitional for c in deduped),
                prerequisite_sections=[],
            )

            sections.append(section)
            section_chunks_map[section_id] = deduped

        total_chunks = sum(len(v) for v in section_chunks_map.values())
        logger.info(
            "sections_from_curriculum_complete",
            total_sections=len(sections),
            total_chunks=total_chunks,
        )

        return sections, section_chunks_map
