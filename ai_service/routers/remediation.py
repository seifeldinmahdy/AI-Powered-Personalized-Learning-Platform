"""
Remediation review content (Batch 11a).

The remediation trigger (Django) inserts a lightweight review step when a
concept's mastery drops. This endpoint makes that step ACTIONABLE: it returns the
weak concept's source chunks via the SAME scoped retrieval the pathway/tutor use
(corpus resolved server-side from course_id, then filtered to the concept). It is
deterministic given (corpus, concept) and reads course material only — no
student-private content — so it carries no per-student body.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/remediation", tags=["remediation"])

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _ensure_paths() -> None:
    for p in (str(_PROJECT_ROOT / "course_pathway"),
              str(_PROJECT_ROOT / "course_pathway" / "src"),
              str(_PROJECT_ROOT / "rag_pipeline")):
        if p not in sys.path:
            sys.path.insert(0, p)


@router.get("/review")
async def remediation_review(concept_id: str, course_id: str, limit: int = 12):
    """Return the weak concept's review chunks (scoped to the course corpus)."""
    _ensure_paths()
    try:
        from pathway.corpus_resolver import resolve_corpus_id  # type: ignore
        from pathway.chromadb_reader import ChromaDBReader       # type: ignore
        from pathway.config import get_settings                  # type: ignore
    except Exception as exc:
        logger.error("remediation review import failed: %s", exc)
        raise HTTPException(status_code=500, detail="Retrieval unavailable")

    corpus_id = resolve_corpus_id(course_id)
    if not corpus_id:
        raise HTTPException(status_code=404, detail="No corpus for this course")

    try:
        reader = ChromaDBReader(persist_dir=get_settings().chroma_db_path)
        chunks = reader.get_all_course_chunks(corpus_id)
    except Exception as exc:
        logger.warning("remediation review retrieval failed (course=%s): %s", course_id, exc)
        raise HTTPException(status_code=502, detail="Retrieval failed")

    target = str(concept_id)
    matched = [c for c in chunks if str(getattr(c, "concept_id", "") or "") == target]
    return {
        "concept_id": target,
        "course_id": course_id,
        "chunks": [
            {"chunk_id": c.chunk_id, "raw_text": c.raw_text, "topic": c.topic}
            for c in matched[: max(1, int(limit))]
        ],
    }
