"""
RAG Router — scoped retrieval of textbook passages for the in-session tutor.

This endpoint is RETRIEVAL-ONLY. It returns the RAW source passages (primary
text + citations) for a question, scoped to the course's corpus via the single
RetrievalService from Batch 2 — the SAME vector store the slides and pathway
were built from. It deliberately does NOT generate an answer: the tutor LLM
grounds on these primary passages directly (one model, one generation), instead
of the old telephone game where RAG generated a paraphrase that the tutor then
re-generated from (propagating hallucinations, doubling latency/cost).

There is no longer a second, independently-configured ChromaDB for RAG: the
retrieval here goes through RetrievalService over the shared collection, and the
scope (corpus_id) is resolved server-side from the Django course_id.
"""

from __future__ import annotations

import logging
import os
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Small in-process LRU cache: (corpus_id, normalized question) -> result
_rag_cache: "OrderedDict[tuple[str, str], RAGResponse]" = OrderedDict()
_RAG_CACHE_MAX = 500

router = APIRouter(prefix="/rag", tags=["RAG"])

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_service = None
_embedder = None


def _ensure_paths() -> None:
    for p in (str(_PROJECT_ROOT / "rag_pipeline"), str(_PROJECT_ROOT / "course_pathway" / "src")):
        if p not in sys.path:
            sys.path.insert(0, p)


def get_retrieval_service():
    """Lazily build the single RetrievalService over the shared vector store.

    Uses the pathway config's chroma path/collection so RAG points at exactly
    the store slides + pathway use, and the rag_pipeline embedding model so the
    query is embedded the same way the chunks were indexed.
    """
    global _service, _embedder
    if _service is not None:
        return _service

    _ensure_paths()
    try:
        from pathway.config import get_settings as get_pathway_settings  # type: ignore
        from src.config.settings import get_settings as get_rag_settings  # type: ignore
        from src.indexing.store import VectorStore  # type: ignore
        from src.indexing.embedder import ChunkEmbedder  # type: ignore
        from src.retrieval.retrieval_service import RetrievalService  # type: ignore

        pw = get_pathway_settings()
        rag = get_rag_settings()

        store = VectorStore(
            persist_dir=pw.chroma_db_path,            # SAME store as slides/pathway
            collection_name=pw.chroma_collection_name,
        )
        _embedder = ChunkEmbedder(model_name=rag.embedding_model)
        _service = RetrievalService(store=store, embedder=_embedder)
        logger.info("RAG retrieval service initialized over shared store at %s", pw.chroma_db_path)
    except Exception as e:
        logger.error("Failed to initialize RAG retrieval service: %s", e)
        raise RuntimeError(f"RAG retrieval unavailable: {e}")

    return _service


# ── Schemas ──────────────────────────────────────────────────────


class RAGRequest(BaseModel):
    question: str
    course_id: str  # Django course id — resolved server-side to the corpus scope
    topic: Optional[str] = None      # optional hard topic filter (usually unset)
    difficulty: Optional[str] = None
    top_k: int = 5


class Passage(BaseModel):
    """A raw retrieved source passage — primary text + citation."""
    chunk_id: str
    text: str
    book: str
    page_start: int
    page_end: int
    topic: str
    relevance_score: float


class RAGResponse(BaseModel):
    question: str
    passages: list[Passage]
    grounded: bool  # True if any in-corpus passages were retrieved


@router.post("/ask", response_model=RAGResponse)
async def ask_rag(request: RAGRequest):
    """Retrieve raw textbook passages for *question*, scoped to the course corpus.

    Returns the primary passages (with citations) for the tutor to ground on.
    ``grounded=False`` means retrieval found nothing in-corpus — the caller
    should answer plainly and surface a "grounding unavailable" state rather
    than silently answering as if grounded.
    """
    _ensure_paths()
    from pathway.corpus_resolver import resolve_corpus_id  # type: ignore
    from src.retrieval.retrieval_service import RetrievalScope, ScopeError  # type: ignore

    # Resolve the corpus scope server-side. No corpus → cannot ground.
    corpus_id = resolve_corpus_id(request.course_id)
    if not corpus_id:
        logger.warning("rag/ask: no corpus for course_id=%s — returning ungrounded", request.course_id)
        return RAGResponse(question=request.question, passages=[], grounded=False)

    cache_key = (corpus_id, request.question.lower().strip())
    if cache_key in _rag_cache:
        _rag_cache.move_to_end(cache_key)
        return _rag_cache[cache_key]

    # ── (D) Soft-prefer already-covered concepts — DESIGN NOTE / TODO ──────────
    # Today retrieval is HARD-scoped to the course corpus (correct + cheap) and
    # ranked purely by semantic similarity. A future improvement is to SOFT-prefer
    # concepts the student has already seen (current + prior sessions) without
    # hard-excluding the rest: over-fetch (e.g. top_k*3) within the corpus scope,
    # then re-rank with a small bonus for chunks whose topic ∈ covered-topics
    # (covered-topics derivable from the cached SessionPlan up to the current
    # session, or from SharedSessionStore.visited_slides → slide topics). This is
    # a ranking tweak only — the hard corpus scope (the security/correctness
    # boundary) is unchanged. Left as a TODO: it needs the covered-topic set
    # plumbed in and isn't worth the extra fetch+rerank cost until measured.
    try:
        service = get_retrieval_service()
        scope = RetrievalScope(corpus_id=corpus_id, course_id=request.course_id)
        chunks = service.semantic_search(
            scope,
            query=request.question,
            topic=request.topic,
            difficulty=request.difficulty,
            top_k=request.top_k,
        )
    except ScopeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("RAG retrieval error: %s", e)
        raise HTTPException(status_code=500, detail=f"RAG retrieval failed: {e}")

    passages = [
        Passage(
            chunk_id=c.chunk_id,
            text=c.raw_text,
            book=c.book,
            page_start=c.page_start,
            page_end=c.page_end,
            topic=c.topic,
            relevance_score=c.relevance_score or 0.0,
        )
        for c in chunks
    ]
    result = RAGResponse(
        question=request.question,
        passages=passages,
        grounded=len(passages) > 0,
    )

    _rag_cache[cache_key] = result
    _rag_cache.move_to_end(cache_key)
    if len(_rag_cache) > _RAG_CACHE_MAX:
        _rag_cache.popitem(last=False)
    return result


@router.get("/health")
async def rag_health():
    """Check the shared retrieval store is reachable."""
    try:
        service = get_retrieval_service()
        count = service._store.count
        return {"status": "healthy", "indexed_chunks": count}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
