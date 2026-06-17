"""Auto-tag corpus chunks with concept_id when Concepts are created/updated.

Extracts the core tagging logic from the ``tag_chunks_with_concepts`` management
command into a reusable function. Called automatically from a ``post_save``
signal on :class:`Concept` (via background thread) so admins never need to run
the management command manually.

The management command remains available as a manual override / dry-run tool.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.4


def _load_vector_store():
    """Import and return a VectorStore connected to the shared ChromaDB."""
    repo_root = Path(__file__).resolve().parents[3]
    rag_dir = str(repo_root / "rag_pipeline")
    if rag_dir not in sys.path:
        sys.path.insert(0, rag_dir)
    from src.indexing.store import VectorStore  # type: ignore

    chroma_path = str(repo_root / "rag_pipeline" / "data" / "chroma")
    return VectorStore(persist_dir=chroma_path, collection_name="course_chunks")


def tag_course_chunks(course_pk: int, min_confidence: float = MIN_CONFIDENCE) -> dict:
    """Tag all corpus chunks for *course_pk* with their best-matching concept_id.

    Returns a summary dict with counts. Safe to call repeatedly (idempotent).
    """
    from apps.courses.models import Course, CourseCorpus, Concept
    from apps.courses.concept_match import build_matcher

    try:
        course = Course.objects.get(pk=course_pk)
    except Course.DoesNotExist:
        logger.warning("auto_tag: course %s not found — skipping", course_pk)
        return {"error": f"Course {course_pk} not found"}

    corpus = CourseCorpus.objects.filter(course=course).first()
    if not corpus:
        logger.warning("auto_tag: course %s has no corpus — skipping", course_pk)
        return {"error": f"Course {course_pk} has no corpus"}

    concepts = list(Concept.objects.filter(course=course))
    if not concepts:
        logger.warning("auto_tag: course %s has no concepts — skipping", course_pk)
        return {"error": f"Course {course_pk} has no concepts"}

    try:
        store = _load_vector_store()
    except Exception as exc:
        logger.error("auto_tag: failed to load vector store: %s", exc)
        return {"error": str(exc)}

    res = store.get_where({"corpus_id": corpus.corpus_id}, include=["metadatas"])
    ids = res.get("ids", []) or []
    metas = res.get("metadatas", []) or []
    if not ids:
        logger.warning("auto_tag: corpus %s has no chunks — skipping", corpus.corpus_id[:8])
        return {"error": "No chunks in corpus"}

    matcher = build_matcher(concepts)

    tagged_count = 0
    upd_ids: list[str] = []
    upd_metas: list[dict] = []

    for cid, meta in zip(ids, metas):
        topic = (meta or {}).get("topic", "")
        concept, conf = matcher.match(topic)
        if concept is None or conf < min_confidence:
            continue
        m = dict(meta or {})
        m["concept_id"] = str(concept.id)
        upd_ids.append(cid)
        upd_metas.append(m)
        tagged_count += 1

    if upd_ids:
        store.update_metadata(upd_ids, upd_metas)

    summary = {
        "course_pk": course_pk,
        "corpus_id": corpus.corpus_id[:8],
        "total_chunks": len(ids),
        "tagged": tagged_count,
        "concepts": len(concepts),
    }
    logger.info("auto_tag: completed for course %s — %s", course_pk, summary)
    return summary
