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
    """In-session performance update → concept-mastery events (single writer).

    Per-topic session scores are recorded as ``source="checkpoint"`` events via
    the one Django writer (/progress/mastery/record). Topics are mapped to
    Concepts there — logged, and DROPPED below the confidence floor. No parallel
    topic_performance signal is maintained.

    TODO(loud): concept-tag the checkpoint generator so this stops relying on a
    fuzzy topic→concept mapping on the live mastery write path.
    """
    store = get_student_context_store()
    context = store.load(student_id, course_id)
    if context is None:
        raise HTTPException(
            status_code=404,
            detail=f"No student context found for student={student_id}, course={course_id}",
        )

    from services.mastery import post_mastery_events
    events = [
        {
            "topic": topic,
            "course_id": str(course_id),
            "outcome": float(score),
            "source": "checkpoint",
            "alpha": 0.3,
        }
        for topic, score in (body.session_scores or {}).items()
    ]
    if events:
        await post_mastery_events(student_id, events)

    logger.info(
        "update_performance recorded %d checkpoint event(s) student=%s course=%s session=%s",
        len(events), student_id, course_id, body.session_number,
    )

    # strengths/weaknesses are now derived from concept_mastery elsewhere; echo
    # the current context (no parallel topic signal).
    return TopicPerformanceUpdateResponse(
        student_id=student_id,
        course_id=course_id,
        updated_topic_performance={},
        updated_strengths=context.profile.strengths,
        updated_weaknesses=context.profile.weaknesses,
        updated_student_profile_summary=context.profile.student_profile_summary,
        topics_updated=[],
        topics_added=[],
    )

