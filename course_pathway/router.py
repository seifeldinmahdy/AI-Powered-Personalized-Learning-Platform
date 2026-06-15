"""FastAPI router for the Course Pathway Generator.

Endpoints
---------
POST  /pathway/generate           — Generate a personalised session plan
GET   /pathway/{student_id}       — Retrieve all cached plans for a student
POST  /pathway/regenerate         — Force-regenerate ignoring cache
GET   /pathway/courses            — List available courses in ChromaDB
GET   /pathway/health             — Health check
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pathway", tags=["Pathway"])


def _require_service_key(x_service_key: Optional[str]) -> None:
    """Gate generation endpoints to internal/admin callers only.

    A student's browser cannot call generate/regenerate: these require the
    internal service key (used by the placement trigger and the admin-only Django
    regenerate proxy). A keyless/wrong-key call gets a clear 403 — never a silent
    regeneration. (Read endpoints stay open to the enrolled student.)
    """
    expected = os.getenv("INTERNAL_SERVICE_KEY", "")
    if not expected or x_service_key != expected:
        raise HTTPException(
            status_code=403,
            detail=(
                "Pathway (re)generation is not permitted from this caller. "
                "Students cannot regenerate their pathway; it is created once "
                "after placement and re-versioned only by the system or an admin."
            ),
        )

# ── Lazy singleton initialisation ────────────────────────────────

_generator = None


def _get_generator():
    """Lazily initialise the PathwayGenerator singleton.

    Resolves paths at import time using the same strategy as
    ``ai_service/routers/rag.py``.
    """
    global _generator
    if _generator is not None:
        return _generator

    # Add course_pathway/src to path
    _course_pathway_dir = Path(__file__).resolve().parent
    _src_dir = _course_pathway_dir / "src"
    if str(_src_dir) not in sys.path:
        sys.path.insert(0, str(_src_dir))

    from pathway.config import get_settings
    from pathway.chromadb_reader import ChromaDBReader
    from pathway.generator import PathwayGenerator
    from pathway.llm.naming import OllamaClient
    from pathway.storage.plan_store import PlanStore

    settings = get_settings()

    reader = ChromaDBReader(
        persist_dir=settings.chroma_db_path,
        collection_name=settings.chroma_collection_name,
    )

    store = PlanStore(db_path=settings.sqlite_db_path)

    # Build LLM client (None if no API key configured)
    llm_client = None
    if settings.ollama_api_key:
        llm_client = OllamaClient(
            host=settings.ollama_host,
            model=settings.ollama_model,
            api_key=settings.ollama_api_key,
            max_retries=settings.max_retries,
        )

    _generator = PathwayGenerator(
        settings=settings,
        reader=reader,
        store=store,
        llm_client=llm_client,
    )

    logger.info("PathwayGenerator initialised successfully.")
    return _generator


# ── Request / Response schemas ───────────────────────────────────

# Re-export from schemas for the router (avoids import-time issues
# when ai_service includes this router before pathway is on sys.path)

class GenerateRequest(BaseModel):
    student_id: str
    course_id: str
    course_title: str = ""
    mastery_level: str = "Intermediate"
    composition_mode: str = "balanced"
    language_proficiency: str = "Intermediate"
    strengths: list[str] = []
    weaknesses: list[str] = []
    strength_concept_ids: list[str] = []
    weak_concept_ids: list[str] = []
    topic_performance: dict[str, float] = {}
    incorrectly_answered: list[dict] = []
    use_synthetic_context: bool = False


class SessionOut(BaseModel):
    session_number: int
    session_title: str
    topics_covered: list[str]
    concept_ids: list[str] = []   # provenance
    clo_codes: list[str] = []     # provenance
    estimated_token_count: int
    chunk_count: int
    book: str
    page_range_start: int
    page_range_end: int


class PlanSummary(BaseModel):
    student_id: str
    course_id: str
    total_sessions: int
    total_chunks: int
    generated_at: str
    cached: bool
    plan_version: int = 1
    sessions: list[SessionOut]


class PlanListItem(BaseModel):
    course_id: str
    context_hash: str
    created_at: str
    plan_version: int = 1


# ── Scope resolution ─────────────────────────────────────────────


def _resolve_corpus_or_404(course_id: str) -> str:
    """Resolve course_id -> corpus_id server-side, or raise a clear 404.

    Keeps the scope a server-side, SoR-derived boundary (the browser never
    sends corpus_id). A missing corpus is an admin-facing error, not a silent
    cross-course fallback.
    """
    from pathway.corpus_resolver import resolve_corpus_id

    corpus_id = resolve_corpus_id(course_id)
    if not corpus_id:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No corpus is defined for course '{course_id}'. An admin must "
                f"create the course corpus and add sources before content can "
                f"be generated."
            ),
        )
    return corpus_id


# ── Endpoints ────────────────────────────────────────────────────


def _context_from_request(request: GenerateRequest, corpus_id: str):
    from pathway.models.schemas import StudentContext
    return StudentContext(
        student_id=request.student_id,
        course_id=request.course_id,
        corpus_id=corpus_id,
            course_title=request.course_title,
        mastery_level=request.mastery_level,
        composition_mode=request.composition_mode,
        language_proficiency=request.language_proficiency,
        strengths=request.strengths,
        weaknesses=request.weaknesses,
        strength_concept_ids=request.strength_concept_ids,
        weak_concept_ids=request.weak_concept_ids,
        topic_performance=request.topic_performance,
        incorrectly_answered=request.incorrectly_answered,
        use_synthetic_context=request.use_synthetic_context,
    )


def _run_generation(request: GenerateRequest, force: bool) -> "PlanSummary":
    """Shared generate/regenerate body: resolve scope, fetch CLOs, generate."""
    from pathway.generator import CoverageError
    from pathway.clo_fetch import fetch_clo_concepts

    gen = _get_generator()
    corpus_id = _resolve_corpus_or_404(request.course_id)
    context = _context_from_request(request, corpus_id)
    clo_concepts = fetch_clo_concepts(request.course_id)
    try:
        response = gen.generate(context, clo_concepts=clo_concepts, force_regenerate=force)
    except CoverageError as e:
        # Coverage failure is an authoring problem — surface it clearly (422).
        raise HTTPException(status_code=422, detail=str(e))
    return _plan_to_summary(response.plan, response.cached)


@router.post("/generate", response_model=PlanSummary)
async def generate_pathway(
    request: GenerateRequest,
    x_service_key: Optional[str] = Header(default=None),
):
    """INTERNAL: generate a pathway (service-key only).

    Not callable by a student browser. Used by the placement trigger / admin
    regenerate proxy. Returns the current version if context is unchanged.
    """
    _require_service_key(x_service_key)
    try:
        return _run_generation(request, force=False)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Pathway generation error: {e}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")


@router.post("/regenerate", response_model=PlanSummary)
async def regenerate_pathway(
    request: GenerateRequest,
    x_service_key: Optional[str] = Header(default=None),
):
    """INTERNAL: force a NEW plan version (service-key only; admin path)."""
    _require_service_key(x_service_key)
    try:
        return _run_generation(request, force=True)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Pathway regeneration error: {e}")
        raise HTTPException(status_code=500, detail=f"Regeneration failed: {e}")


@router.get("/versions")
async def pathway_versions(student_id: str, course_id: str):
    """Admin/instructor: list all plan versions for a student+course (metadata
    only — no full plan JSON). The current version is flagged is_current."""
    try:
        gen = _get_generator()
        return {"versions": gen._store.list_versions(student_id, course_id)}
    except Exception as e:
        logger.error(f"pathway_versions error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/current", response_model=PlanSummary)
async def current_pathway(student_id: str, course_id: str):
    """Read-only: return the CURRENT authoritative plan (no generation).

    The pathway page and live session read this — opening the page never
    triggers regeneration.
    """
    try:
        gen = _get_generator()
        plan = gen._store.load_current(student_id, course_id)
        if plan is None:
            raise HTTPException(
                status_code=404,
                detail="No pathway has been generated yet for this student/course.",
            )
        return _plan_to_summary(plan, cached=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"current_pathway error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SessionProvenance(BaseModel):
    session_number: int
    session_title: str
    concept_ids: list[str]
    clo_codes: list[str]


@router.get("/{student_id}/{course_id}/provenance", response_model=list[SessionProvenance])
async def pathway_provenance(student_id: str, course_id: str):
    """List, per session, the concepts and CLOs it covers (explainability)."""
    try:
        gen = _get_generator()
        plan = gen._store.load_current(student_id, course_id)
        if plan is None:
            raise HTTPException(status_code=404, detail="No current plan.")
        return [
            SessionProvenance(
                session_number=s.session_number, session_title=s.session_title,
                concept_ids=s.concept_ids, clo_codes=s.clo_codes,
            )
            for s in plan.sessions
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"provenance error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{student_id}", response_model=list[PlanListItem])
async def list_student_plans(student_id: str):
    """List all cached pathway plans for a student."""
    try:
        gen = _get_generator()
        plans = gen._store.list_plans(student_id)
        return [PlanListItem(**p) for p in plans]
    except Exception as e:
        logger.error(f"Plan listing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/courses/available", response_model=list[str])
async def available_courses():
    """List all corpus IDs present in the vector store (introspection)."""
    try:
        gen = _get_generator()
        return gen._reader.list_corpus_ids()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SessionChunksRequest(BaseModel):
    student_id: str
    course_id: str
    session_number: int


class SessionChunkOut(BaseModel):
    chunk_id: str
    raw_text: str
    topic: str
    concept_id: str = ""
    page_start: int
    page_end: int


@router.post("/session-chunks", response_model=list[SessionChunkOut])
async def get_session_chunks(request: SessionChunksRequest):
    """Return the raw text chunks for a specific session from a cached plan.

    Loads the plan from the store, finds the session by number, and
    returns the chunk texts by looking them up in ChromaDB.
    """
    try:
        gen = _get_generator()

        # Load cached plan
        cached_plan = gen._store.load(request.student_id, request.course_id)
        if cached_plan is None:
            raise HTTPException(status_code=404, detail="No cached plan found")

        # Find the session
        session = None
        for s in cached_plan.sessions:
            if s.session_number == request.session_number:
                session = s
                break

        if session is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session {request.session_number} not found",
            )

        # Enrich the session's chunks with topic/page metadata, scoped to this
        # course's corpus. We fetch ONLY the session's chunk ids (scoped), so a
        # stale id from another corpus can never leak in.
        corpus_id = _resolve_corpus_or_404(request.course_id)
        from src.retrieval.retrieval_service import RetrievalScope  # type: ignore
        scope = RetrievalScope(corpus_id=corpus_id, course_id=request.course_id)

        chunk_ids = [sc.chunk_id for sc in session.chunks]
        meta_chunks = gen._reader.get_chunks_by_ids(scope, chunk_ids)
        chunk_map = {c.chunk_id: c for c in meta_chunks}

        result = []
        for sc in session.chunks:
            meta = chunk_map.get(sc.chunk_id)
            result.append(SessionChunkOut(
                chunk_id=sc.chunk_id,
                raw_text=sc.raw_text,
                topic=meta.topic if meta else "",
                concept_id=(meta.concept_id if meta else "") or "",
                page_start=meta.page_start if meta else 0,
                page_end=meta.page_end if meta else 0,
            ))

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Session chunks error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def pathway_health():
    """Health check for the pathway generator."""
    try:
        gen = _get_generator()
        chunk_count = gen._reader.chunk_count
        courses = gen._reader.get_available_courses()
        return {
            "status": "healthy",
            "indexed_chunks": chunk_count,
            "available_courses": courses,
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


# ── Helpers ──────────────────────────────────────────────────────


def _plan_to_summary(plan, cached: bool) -> PlanSummary:
    """Convert a SessionPlan to the API response model."""
    return PlanSummary(
        student_id=plan.student_id,
        course_id=plan.course_id,
        total_sessions=plan.total_sessions,
        total_chunks=plan.total_chunks,
        generated_at=plan.generated_at,
        cached=cached,
        plan_version=plan.plan_version,
        sessions=[
            SessionOut(
                session_number=s.session_number,
                session_title=s.session_title,
                topics_covered=s.topics_covered,
                concept_ids=s.concept_ids,
                clo_codes=s.clo_codes,
                estimated_token_count=s.estimated_token_count,
                chunk_count=len(s.chunks),
                book=s.book,
                page_range_start=s.page_range_start,
                page_range_end=s.page_range_end,
            )
            for s in plan.sessions
        ],
    )
