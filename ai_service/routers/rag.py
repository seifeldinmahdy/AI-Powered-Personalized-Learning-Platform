"""
RAG Router — Retrieval-Augmented Generation endpoints.
Answers student questions grounded in indexed course textbooks.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import logging
import sys
import os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["RAG"])

# Path to rag_pipeline — resolved from cwd (ai_service/) at runtime
RAG_PIPELINE_DIR = os.path.abspath(os.path.join(os.getcwd(), "..", "rag_pipeline"))

_engine = None


def get_rag_engine():
    global _engine
    if _engine is not None:
        return _engine

    if RAG_PIPELINE_DIR not in sys.path:
        sys.path.insert(0, RAG_PIPELINE_DIR)

    try:
        # Change to rag_pipeline dir so relative paths (.env, ./data/chroma) resolve correctly
        original_cwd = os.getcwd()
        os.chdir(RAG_PIPELINE_DIR)

        from src.config.settings import get_settings
        from src.llm.client import OllamaCloudClient
        from src.retrieval.engine import RAGEngine

        settings = get_settings()
        os.chdir(original_cwd)  # restore cwd after settings loaded

        llm_client = OllamaCloudClient(
            host=settings.ollama_host,
            model=settings.ollama_model,
            api_key=settings.ollama_api_key,
            max_retries=settings.max_retries,
        )
        # Override chroma path to absolute so it works from any cwd
        settings.chroma_db_path = os.path.join(RAG_PIPELINE_DIR, "data", "chroma")
        _engine = RAGEngine(settings=settings, llm_client=llm_client)
        logger.info("RAG engine initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize RAG engine: {e}")
        raise RuntimeError(f"RAG engine unavailable: {e}")

    return _engine


class RAGRequest(BaseModel):
    question: str
    course: Optional[str] = None
    topic: Optional[str] = None
    difficulty: Optional[str] = None
    top_k: int = 5


class SourceOut(BaseModel):
    book: str
    page_start: int
    page_end: int
    topic: str
    relevance_score: float


class RAGResponse(BaseModel):
    answer: str
    sources: list[SourceOut]
    question: str


@router.post("/ask", response_model=RAGResponse)
async def ask_rag(request: RAGRequest):
    """
    Answer a student question grounded in indexed course textbooks.
    Returns the answer with source citations.
    """
    try:
        engine = get_rag_engine()
        response = engine.ask(
            question=request.question,
            course=request.course,
            topic=request.topic,
            difficulty=request.difficulty,
            top_k=request.top_k,
        )
        return RAGResponse(
            answer=response.answer,
            sources=[
                SourceOut(
                    book=s.book,
                    page_start=s.page_start,
                    page_end=s.page_end,
                    topic=s.topic,
                    relevance_score=s.relevance_score,
                )
                for s in response.sources
            ],
            question=response.question,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"RAG error: {e}")
        raise HTTPException(status_code=500, detail=f"RAG query failed: {str(e)}")


@router.get("/health")
async def rag_health():
    """Check if RAG engine and ChromaDB are ready."""
    try:
        engine = get_rag_engine()
        count = engine.store.collection.count()
        return {"status": "healthy", "indexed_chunks": count}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
