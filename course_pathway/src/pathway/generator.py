"""Top-level pathway generator orchestrator.

Wires together the top-down LLM curriculum design pipeline:
    ChromaDB (topics) → LLM Curriculum Design → Chunk Retrieval →
    Personalizer → SessionGrouper → Validation → PlanStore

A single call to ``PathwayGenerator.generate()`` runs the full pipeline
and returns a ``PathwayResponse``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from difflib import SequenceMatcher

import structlog

from pathway.chromadb_reader import ChromaDBReader
from pathway.config import PathwaySettings
from pathway.llm.curriculum import (
    clean_topic_list,
    propose_curriculum,
    resolve_curriculum,
)
from pathway.llm.naming import OllamaClient
from pathway.models.schemas import (
    CourseChunk,
    DiscoveredSection,
    LLMCurriculumSession,
    PathwayResponse,
    Session,
    SessionChunk,
    SessionPlan,
    StudentContext,
)


class CoverageError(ValueError):
    """Raised when a plan fails to cover every CLO concept.

    Coverage is a guarantee, not a personalization choice: assessment results
    set depth/order/pacing/remediation, never WHETHER a CLO is taught.
    """
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
        clo_concepts: list[dict] | None = None,
        force_regenerate: bool = False,
    ) -> PathwayResponse:
        """Generate (or retrieve current) a personalized, CLO-covering plan.

        Parameters
        ----------
        context:
            Student context (mastery, strengths, weaknesses) — sets DEPTH,
            ORDER, PACING, REMEDIATION, never CLO coverage.
        clo_concepts:
            ``[{concept_id, label, clo_code}]`` — the course's CLO concept set.
            Generation GUARANTEES every concept here is covered, or raises
            ``CoverageError``.
        force_regenerate:
            If True, bypass the current-version check and create a new version.

        Returns
        -------
        PathwayResponse
            The current ``SessionPlan`` and a ``cached`` flag.
        """
        ctx_hash = context.context_hash()

        # 1. Current-version reuse (deterministic + context-hashed). Identical
        #    context returns the existing CURRENT plan — no new version.
        if not force_regenerate and not self._store.needs_regeneration(
            context.student_id, context.course_id, ctx_hash
        ):
            cached_plan = self._store.load_current(context.student_id, context.course_id)
            if cached_plan is not None:
                logger.info("pathway_served_from_current_version",
                            student_id=context.student_id, course_id=context.course_id,
                            plan_version=cached_plan.plan_version)
                return PathwayResponse(plan=cached_plan, cached=True)

        logger.info("pathway_generation_start", student_id=context.student_id,
                    course_id=context.course_id, corpus_id=context.corpus_id,
                    mastery=context.mastery_level)

        # 2. Load ALL chunks — strictly scoped to this corpus.
        scope = self._build_scope(context)
        chunks = self._reader.get_all_chunks(scope)
        if not chunks:
            raise ValueError(
                f"Course corpus is empty: no chunks found for corpus_id="
                f"'{context.corpus_id}' (course_id='{context.course_id}'"
                f"{f' (title: {context.course_id!r})' if context.course_id else ''}). "
                f"Add sources to this course's corpus and index them."
            )

        # 3. Synthetic context (testing only).
        if context.use_synthetic_context:
            unique_topics = list(dict.fromkeys(c.topic for c in chunks))
            mastery_to_diff = {"Novice": "beginner", "Intermediate": "intermediate", "Expert": "expert"}
            diff_tier = mastery_to_diff.get(context.mastery_level, "intermediate")
            difficulty_topics = self._reader.get_topics_by_difficulty(scope, diff_tier)
            context = self._synthetic_gen.generate(
                student_id=context.student_id, course_id=context.course_id,
                available_topics=unique_topics, difficulty_topics=difficulty_topics,
                mastery_level=context.mastery_level,
            )
            ctx_hash = context.context_hash()

        # 4. Topic index.
        all_topics = list(dict.fromkeys(c.topic for c in chunks))
        chunks_by_topic: dict[str, list[CourseChunk]] = defaultdict(list)
        for chunk in chunks:
            chunks_by_topic[chunk.topic].append(chunk)
        book_titles = sorted({c.book for c in chunks})

        # 5. Curriculum: capture & REPLAY the raw LLM proposal so the plan is
        #    re-resolved deterministically (independent of provider drift).
        clean_topics = clean_topic_list(all_topics)
        input_hash = hashlib.sha256(
            json.dumps({"topics": sorted(clean_topics), "intent": context.course_intent},
                       sort_keys=True).encode()
        ).hexdigest()

        raw_proposal: dict = {}
        raw_proposal_hash = ""
        cached_proposal = self._store.load_proposal(context.course_id, context.corpus_id, input_hash)
        if cached_proposal is not None:
            proposal_json, raw_proposal_hash = cached_proposal
            raw_proposal = json.loads(proposal_json)
            logger.info("curriculum_proposal_replayed", proposal_hash=raw_proposal_hash)
        elif self._llm is not None and clean_topics:
            raw_proposal = propose_curriculum(
                client=self._llm, clean_topics=clean_topics,
                course_intent=context.course_intent, book_titles=book_titles,
                max_retries=self._settings.max_retries,
                timeout=self._settings.ollama_curriculum_timeout,
                target_sessions=self._settings.target_session_count,
                min_sessions=self._settings.min_sessions,
                max_sessions=self._settings.max_sessions,
            )
            proposal_json = json.dumps(raw_proposal, sort_keys=True)
            raw_proposal_hash = hashlib.sha256(proposal_json.encode()).hexdigest()
            self._store.save_proposal(context.course_id, context.corpus_id,
                                      input_hash, proposal_json, raw_proposal_hash)

        # Deterministic resolution from the (replayed or fresh) proposal.
        curriculum = resolve_curriculum(
            raw_proposal, clean_topics,
            target_sessions=self._settings.target_session_count,
            max_sessions=self._settings.max_sessions,
        )

        # 6-8. Sections → personalise (depth/order) → group into sessions.
        sections, _ = self._build_sections_from_curriculum(curriculum, chunks_by_topic)
        personalised_sections, section_chunks = self._personalizer.personalize(
            sections, chunks, context
        )
        sessions = self._grouper.group_sessions(personalised_sections, section_chunks)

        # 9. CLO COVERAGE GUARANTEE — inject any uncovered CLO concept, then
        #    hard-fail if a CLO concept still can't be covered.
        clo_concepts = clo_concepts or []
        concept_to_clos: dict[str, set[str]] = defaultdict(set)
        concept_label: dict[str, str] = {}
        for c in clo_concepts:
            cid = str(c["concept_id"])
            concept_to_clos[cid].add(c.get("clo_code", ""))
            concept_label[cid] = c.get("label", cid)
        required = set(concept_to_clos.keys())
        if required:
            self._ensure_clo_coverage(sessions, scope, required, concept_label, concept_to_clos)

        # 9.5. Bound each session's chunk set so the slide deck never becomes
        #      abnormally long. Done AFTER coverage injection so it bounds both
        #      curriculum and injected chunks, and it keeps >=1 chunk per concept
        #      so CLO coverage stays intact.
        self._cap_session_chunks(sessions)

        # 10. Provenance: stamp each session with the CLOs it teaches.
        for s in sessions:
            clos: set[str] = set()
            for cid in s.concept_ids:
                clos.update(c for c in concept_to_clos.get(cid, set()) if c)
            s.clo_codes = sorted(clos)

        # 11. Build + persist as a NEW VERSION (never overwrite).
        plan = SessionPlan(
            student_id=context.student_id,
            course_id=context.course_id,
            sessions=sessions,
            total_sessions=len(sessions),
            total_chunks=sum(len(s.chunks) for s in sessions),
            student_context_hash=ctx_hash,
            raw_proposal_hash=raw_proposal_hash,
        )
        version = self._store.save_new_version(plan)

        logger.info("pathway_generation_complete", student_id=context.student_id,
                    course_id=context.course_id, plan_version=version,
                    total_sessions=plan.total_sessions, total_chunks=plan.total_chunks)
        return PathwayResponse(plan=plan, cached=False)

    # ── CLO coverage ─────────────────────────────────────────────

    def _ensure_clo_coverage(
        self,
        sessions: list[Session],
        scope,
        required: set[str],
        concept_label: dict[str, str],
        concept_to_clos: dict[str, set[str]],
    ) -> None:
        """Guarantee every required CLO concept is covered; raise if impossible.

        Uncovered concepts are injected into the deterministic best-fit session.
        A concept with NO corpus chunks can never be covered → CoverageError.
        """
        def covered_set() -> set[str]:
            out: set[str] = set()
            for s in sessions:
                out.update(s.concept_ids)
            return out

        missing = sorted(required - covered_set())  # deterministic order
        for cid in missing:
            cchunks = self._reader.get_chunks_for_concept(scope, cid)
            if not cchunks:
                continue  # caught by the final hard check below
            target = self._best_fit_session(sessions, concept_label.get(cid, cid))
            self._inject_chunks(target, cchunks, cid)

        still_missing = sorted(required - covered_set())
        if still_missing:
            details = ", ".join(
                f"{concept_label.get(cid, cid)} (concept {cid}; "
                f"CLO {','.join(sorted(c for c in concept_to_clos.get(cid, set()) if c)) or '?'})"
                for cid in still_missing
            )
            raise CoverageError(
                "Pathway generation aborted: the following CLO concepts have no "
                f"corpus chunks and cannot be covered — {details}. Add sources "
                "covering these concepts (or run tag_chunks_with_concepts)."
            )

    def _cap_session_chunks(self, sessions: list[Session]) -> None:
        """Bound each session's chunks to keep slide decks a sane length.

        For every session, keep at most ``max_chunks_per_concept`` representative
        chunks per concept_id and at most ``max_chunks_per_session`` chunks total.
        Chunks are already ordered definitional-first / earliest-page, so keeping
        the first few per concept yields the most representative slides.

        COVERAGE INVARIANT: at least one chunk per concept is always retained, so
        capping can never drop a CLO concept the coverage step just guaranteed.
        """
        max_pc = int(getattr(self._settings, "max_chunks_per_concept", 0) or 0)
        max_total = int(getattr(self._settings, "max_chunks_per_session", 0) or 0)
        if max_pc <= 0 and max_total <= 0:
            return

        for s in sessions:
            before = len(s.chunks)
            s.chunks = self._select_representative_chunks(s.chunks, max_pc, max_total)
            if len(s.chunks) != before:
                logger.info(
                    "session_chunks_capped",
                    session=s.session_number, before=before, after=len(s.chunks),
                )

    @staticmethod
    def _select_representative_chunks(
        chunks: list[SessionChunk], max_per_concept: int, max_total: int,
    ) -> list[SessionChunk]:
        """Pick a bounded, concept-balanced subset, preserving original order.

        Strategy: group by concept_id (insertion order), cap each group to
        ``max_per_concept``, then guarantee one-per-concept before filling the
        remaining ``max_total`` budget round-robin. The result is re-sorted into
        the original chunk order so the deck reads coherently.
        """
        if not chunks:
            return chunks

        order = {c.chunk_id: i for i, c in enumerate(chunks)}
        groups: dict[str, list[SessionChunk]] = {}
        for c in chunks:
            groups.setdefault(getattr(c, "concept_id", "") or "__untagged__", []).append(c)

        # Per-concept cap.
        if max_per_concept > 0:
            for key in groups:
                groups[key] = groups[key][:max_per_concept]

        queues = [list(g) for g in groups.values()]

        # Round 1: one per concept (coverage guarantee — may exceed max_total when
        # a session legitimately spans more concepts than the cap; coverage wins).
        selected: list[SessionChunk] = [q.pop(0) for q in queues if q]

        # Fill the remaining budget round-robin.
        if max_total <= 0 or len(selected) < max_total:
            filling = True
            while filling and (max_total <= 0 or len(selected) < max_total):
                filling = False
                for q in queues:
                    if not q:
                        continue
                    selected.append(q.pop(0))
                    filling = True
                    if max_total > 0 and len(selected) >= max_total:
                        break

        selected.sort(key=lambda c: order[c.chunk_id])
        return selected

    @staticmethod
    def _best_fit_session(sessions: list[Session], label: str) -> Session:
        """Pick the deterministic best-fit session for an uncovered concept.

        Score = max difflib ratio between the concept label and the session's
        title/topics. Tie-break: highest score, then LOWEST session_number.
        """
        label_n = label.lower().strip()

        def score(s: Session) -> float:
            cands = [s.session_title, *s.topics_covered]
            return max((SequenceMatcher(None, label_n, (c or "").lower()).ratio() for c in cands), default=0.0)

        # Sort by (-score, session_number) → best score, lowest number on ties.
        return sorted(sessions, key=lambda s: (-score(s), s.session_number))[0]

    @staticmethod
    def _inject_chunks(session: Session, course_chunks: list[CourseChunk], concept_id: str) -> None:
        """Add a concept's chunks to *session* (idempotent), updating provenance."""
        existing = {c.chunk_id for c in session.chunks}
        added = False
        for ch in sorted(course_chunks, key=lambda c: (c.chunk_index, c.chunk_id)):
            if ch.chunk_id in existing:
                continue
            session.chunks.append(SessionChunk(
                chunk_id=ch.chunk_id, raw_text=ch.raw_text, concept_id=concept_id,
            ))
            if ch.topic and ch.topic not in session.topics_covered:
                session.topics_covered.append(ch.topic)
            added = True
        if added and concept_id not in session.concept_ids:
            session.concept_ids = sorted(set(session.concept_ids) | {concept_id})
        logger.info("clo_coverage_injected", concept_id=concept_id,
                    session=session.session_number, added=added)

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
