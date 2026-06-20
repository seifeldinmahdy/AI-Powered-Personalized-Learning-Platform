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

    # Scope to this corpus's chunks via the per-corpus membership flag
    # (corpus__<id> = "1"), matching tag_chunks_with_concepts. The legacy scalar
    # "corpus_id" is empty on shared/canonical books, so it would match nothing.
    membership_key = f"corpus__{corpus.corpus_id}"
    res = store.get_where({membership_key: "1"}, include=["metadatas"])
    ids = res.get("ids", []) or []
    metas = res.get("metadatas", []) or []
    if not ids:
        logger.warning("auto_tag: corpus %s has no chunks — skipping", corpus.corpus_id[:8])
        return {"error": "No chunks in corpus"}

    matcher = build_matcher(concepts)

    tagged_count = 0
    per_concept: dict[str, int] = {}
    upd_ids: list[str] = []
    upd_metas: list[dict] = []

    for cid, meta in zip(ids, metas):
        topic = (meta or {}).get("topic", "")
        concept, conf = matcher.match(topic)
        if concept is None or conf < min_confidence:
            continue
        # Per-corpus concept tag (concept__<corpus_id>), partial-merged so the
        # SAME shared book can carry different concept tags in different courses.
        # This is the key get_chunks_for_concept / CLO coverage actually reads.
        key = str(concept.id)
        upd_ids.append(cid)
        upd_metas.append({f"concept__{corpus.corpus_id}": key})
        per_concept[key] = per_concept.get(key, 0) + 1
        tagged_count += 1

    if upd_ids:
        store.update_metadata(upd_ids, upd_metas)

    summary = {
        "course_pk": course_pk,
        "corpus_id": corpus.corpus_id[:8],
        "total_chunks": len(ids),
        "tagged": tagged_count,
        "concepts": len(concepts),
        # concept_id (str) → number of chunks tagged to it this pass; lets callers
        # detect a concept that grounded to ZERO chunks.
        "per_concept": per_concept,
    }
    logger.info("auto_tag: completed for course %s — %s", course_pk, summary)
    return summary


def cleanup_orphaned_auto_concepts(course_pk: int) -> dict:
    """Delete auto-extracted concepts that no longer have grounded corpus chunks.

    Called after a book is detached from a course's corpus. A concept is orphaned
    only if NO chunk currently in the corpus (``corpus__<id> = "1"``) still carries
    its ``concept__<id>`` tag — so a concept still grounded by another attached
    book is preserved. Manual concepts (``source != "auto"``) are never deleted;
    they are the admin's own. Deleting a Concept cascades its CLO M2M unlink.
    """
    from apps.courses.models import Course, CourseCorpus, Concept

    course = Course.objects.filter(pk=course_pk).first()
    if not course:
        return {"error": f"Course {course_pk} not found"}

    corpus = CourseCorpus.objects.filter(course=course).first()
    if not corpus:
        return {"error": f"Course {course_pk} has no corpus"}

    autos = list(Concept.objects.filter(course=course, source="auto"))
    if not autos:
        return {"deleted": 0, "checked": 0, "labels": []}

    try:
        store = _load_vector_store()
    except Exception as exc:
        logger.error("cleanup_orphaned_auto_concepts: store load failed: %s", exc)
        return {"error": str(exc)}

    membership_key = f"corpus__{corpus.corpus_id}"
    concept_key = f"concept__{corpus.corpus_id}"

    orphaned = []
    for c in autos:
        try:
            n = store.count_where(
                {"$and": [{membership_key: "1"}, {concept_key: str(c.id)}]}
            )
        except Exception as exc:
            # If we cannot verify a concept is orphaned, leave it alone.
            logger.warning("cleanup: count failed for concept %s: %s", c.id, exc)
            continue
        if n == 0:
            orphaned.append(c)

    labels = [c.label for c in orphaned]
    for c in orphaned:
        c.delete()  # cascades the CLO M2M unlink

    summary = {"deleted": len(orphaned), "checked": len(autos), "labels": labels}
    logger.info("cleanup_orphaned_auto_concepts: course %s — %s", course_pk, summary)
    return summary
