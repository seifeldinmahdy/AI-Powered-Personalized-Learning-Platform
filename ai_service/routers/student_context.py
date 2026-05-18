"""
Student Context Router — retrieval and update endpoints for persisted student context.

Provides:
- ``GET  /student-context/{student_id}/{course_id}``
     Read the student's placement-derived context.
- ``POST /student-context/{student_id}/{course_id}/update-performance``
     Update topic_performance after a session assessment.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.student_context_store import get_student_context_store
from services.topic_mastery import update_topic_performance_scores

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/student-context",
    tags=["Student Context"],
)


# ── Request / Response schemas ───────────────────────────────────


class TopicPerformanceUpdate(BaseModel):
    """Request body for updating topic performance after a session assessment."""
    session_scores: dict[str, float] = Field(
        ..., description="topic → score (0.0–1.0) for the session just completed",
    )
    session_number: int = Field(
        ..., description="Session number just completed (for logging)",
    )
    session_topic: str = Field(
        ..., description="Human-readable session title (for logging)",
    )


class TopicPerformanceUpdateResponse(BaseModel):
    """Response body echoing the full updated context."""
    student_id: str
    course_id: str
    updated_topic_performance: dict[str, float]
    updated_strengths: list[str]
    updated_weaknesses: list[str]
    updated_student_profile_summary: str
    topics_updated: list[str]
    topics_added: list[str]


# ── Endpoints ────────────────────────────────────────────────────


@router.get("/{student_id}/{course_id}")
async def get_student_context(student_id: str, course_id: str):
    """Return the persisted UnifiedStudentContext for a student+course pair.

    Parameters
    ----------
    student_id : str
        The student's user ID (as string).
    course_id : str
        The course identifier.

    Returns
    -------
    dict
        The full UnifiedStudentContext, or 404 if not found.
    """
    store = get_student_context_store()
    context = store.load(student_id, course_id)

    if context is None:
        logger.warning("student_context_not_found student=%s course=%s", student_id, course_id)
        raise HTTPException(
            status_code=404,
            detail=f"No student context found for student={student_id}, course={course_id}",
        )

    logger.info(
        "student_context_retrieved student=%s course=%s mastery=%s",
        student_id, course_id, context.profile.mastery_level,
    )
    return context.model_dump()


@router.post(
    "/{student_id}/{course_id}/update-performance",
    response_model=TopicPerformanceUpdateResponse,
)
async def update_performance(
    student_id: str,
    course_id: str,
    body: TopicPerformanceUpdate,
):
    """Update topic_performance after a session assessment.

    Applies a weighted moving average to existing topic scores and adds
    new topics directly.  Recomputes strengths, weaknesses, and the
    student_profile_summary.  Persists the updated context atomically.

    **Does NOT modify** mastery_level, composition_mode,
    language_proficiency, use_synthetic_context, course_intent,
    student_id, or course_id.
    """
    # ── Validate: non-empty session_scores ───────────────────────
    if not body.session_scores:
        raise HTTPException(
            status_code=400,
            detail="session_scores is empty — nothing to update.",
        )

    # ── Validate: score range 0.0–1.0 ────────────────────────────
    for topic, score in body.session_scores.items():
        if score < 0.0 or score > 1.0:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Invalid score for topic '{topic}': {score}. "
                    f"Score must be between 0.0 and 1.0."
                ),
            )

    # ── Load existing context ────────────────────────────────────
    store = get_student_context_store()
    context = store.load(student_id, course_id)

    if context is None:
        logger.warning(
            "update_performance_context_not_found student=%s course=%s",
            student_id, course_id,
        )
        raise HTTPException(
            status_code=404,
            detail=f"No student context found for student={student_id}, course={course_id}",
        )

    # ── Load weight from settings (if accessible) ────────────────
    weight = 0.3
    try:
        import sys
        from pathlib import Path
        _pathway_src = str(
            Path(__file__).resolve().parent.parent.parent / "course_pathway" / "src"
        )
        if _pathway_src not in sys.path:
            sys.path.insert(0, _pathway_src)
        from pathway.config import get_settings as _get_pathway_settings  # type: ignore
        weight = _get_pathway_settings().topic_performance_update_weight
    except Exception:
        pass  # Use default — non-critical

    # ── Snapshot before state for logging ─────────────────────────
    old_performance = dict(context.profile.topic_performance)
    old_strengths = set(context.profile.strengths)
    old_weaknesses = set(context.profile.weaknesses)

    # ── Compute updated scores ───────────────────────────────────
    result = update_topic_performance_scores(
        current_performance=context.profile.topic_performance,
        session_scores=body.session_scores,
        weight=weight,
    )
    new_performance = result["topic_performance"]
    new_strengths = result["strengths"]
    new_weaknesses = result["weaknesses"]

    # ── Classify topics for logging ──────────────────────────────
    topics_updated = [t for t in body.session_scores if t in old_performance]
    topics_added = [t for t in body.session_scores if t not in old_performance]

    # Detect category transitions
    new_strengths_set = set(new_strengths)
    new_weaknesses_set = set(new_weaknesses)
    weakness_to_strength = sorted(old_weaknesses & new_strengths_set)
    strength_to_weakness = sorted(old_strengths & new_weaknesses_set)

    # ── Update context in-place ──────────────────────────────────
    context.profile.topic_performance = new_performance
    context.profile.strengths = new_strengths
    context.profile.weaknesses = new_weaknesses

    # ── Regenerate student_profile_summary ────────────────────────
    mastery = context.profile.mastery_level
    intent = context.profile.course_intent or course_id
    parts = [f"{mastery} learner in {intent}."]
    if new_strengths:
        parts.append(f"Strong in: {', '.join(new_strengths)}.")
    if new_weaknesses:
        parts.append(f"Needs work on: {', '.join(new_weaknesses)}.")
    context.profile.student_profile_summary = " ".join(parts)

    # ── Persist atomically ───────────────────────────────────────
    store.save(student_id, course_id, context)

    # ── Log ───────────────────────────────────────────────────────
    before_after = {
        t: {"before": old_performance.get(t, "NEW"), "after": new_performance[t]}
        for t in body.session_scores
    }
    logger.info(
        "topic_performance_updated student=%s course=%s session=%d "
        "session_topic=%s weight=%.2f topics_updated=%s topics_added=%s "
        "before_after=%s weakness_to_strength=%s strength_to_weakness=%s "
        "strengths=%s weaknesses=%s",
        student_id, course_id, body.session_number,
        body.session_topic, weight,
        topics_updated, topics_added,
        before_after,
        weakness_to_strength, strength_to_weakness,
        new_strengths, new_weaknesses,
    )

    return TopicPerformanceUpdateResponse(
        student_id=student_id,
        course_id=course_id,
        updated_topic_performance=new_performance,
        updated_strengths=new_strengths,
        updated_weaknesses=new_weaknesses,
        updated_student_profile_summary=context.profile.student_profile_summary,
        topics_updated=topics_updated,
        topics_added=topics_added,
    )

