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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pathway", tags=["Pathway"])

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
    mastery_level: str = "Intermediate"
    composition_mode: str = "balanced"
    language_proficiency: str = "Intermediate"
    strengths: list[str] = []
    weaknesses: list[str] = []
    topic_performance: dict[str, float] = {}
    incorrectly_answered: list[dict] = []
    use_synthetic_context: bool = False


class SessionOut(BaseModel):
    session_number: int
    session_title: str
    topics_covered: list[str]
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
    sessions: list[SessionOut]


class PlanListItem(BaseModel):
    course_id: str
    context_hash: str
    created_at: str


# ── Endpoints ────────────────────────────────────────────────────


@router.post("/generate", response_model=PlanSummary)
async def generate_pathway(request: GenerateRequest):
    """Generate a personalised learning pathway for a student.

    If a cached plan exists with the same context hash, it is returned
    immediately.  Otherwise the full pipeline runs.
    """
    try:
        gen = _get_generator()

        from pathway.models.schemas import StudentContext

        context = StudentContext(
            student_id=request.student_id,
            course_id=request.course_id,
            mastery_level=request.mastery_level,
            composition_mode=request.composition_mode,
            language_proficiency=request.language_proficiency,
            strengths=request.strengths,
            weaknesses=request.weaknesses,
            topic_performance=request.topic_performance,
            incorrectly_answered=request.incorrectly_answered,
            use_synthetic_context=request.use_synthetic_context,
        )

        response = gen.generate(context)
        return _plan_to_summary(response.plan, response.cached)

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Pathway generation error: {e}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")


@router.post("/regenerate", response_model=PlanSummary)
async def regenerate_pathway(request: GenerateRequest):
    """Force-regenerate a pathway, ignoring any cached plan."""
    try:
        gen = _get_generator()

        from pathway.models.schemas import StudentContext

        context = StudentContext(
            student_id=request.student_id,
            course_id=request.course_id,
            mastery_level=request.mastery_level,
            composition_mode=request.composition_mode,
            language_proficiency=request.language_proficiency,
            strengths=request.strengths,
            weaknesses=request.weaknesses,
            topic_performance=request.topic_performance,
            incorrectly_answered=request.incorrectly_answered,
            use_synthetic_context=request.use_synthetic_context,
        )

        response = gen.generate(context, force_regenerate=True)
        return _plan_to_summary(response.plan, response.cached)

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Pathway regeneration error: {e}")
        raise HTTPException(status_code=500, detail=f"Regeneration failed: {e}")


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
    """List all course IDs available in ChromaDB."""
    try:
        gen = _get_generator()
        return gen._reader.get_available_courses()
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

        # The session already has SessionChunk objects with chunk_id and raw_text
        # But we also need topic, page_start, page_end from ChromaDB metadata
        # Fetch all course chunks from ChromaDB for metadata lookup
        all_chunks = gen._reader.get_all_course_chunks(request.course_id)
        chunk_map = {c.chunk_id: c for c in all_chunks}

        result = []
        for sc in session.chunks:
            meta = chunk_map.get(sc.chunk_id)
            result.append(SessionChunkOut(
                chunk_id=sc.chunk_id,
                raw_text=sc.raw_text,
                topic=meta.topic if meta else "",
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
        sessions=[
            SessionOut(
                session_number=s.session_number,
                session_title=s.session_title,
                topics_covered=s.topics_covered,
                estimated_token_count=s.estimated_token_count,
                chunk_count=len(s.chunks),
                book=s.book,
                page_range_start=s.page_range_start,
                page_range_end=s.page_range_end,
            )
            for s in plan.sessions
        ],
    )
