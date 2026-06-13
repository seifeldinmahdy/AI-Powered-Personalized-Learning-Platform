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
    """In-session performance update — NEUTERED in Batch 5.

    ╔════════════════════════════════════════════════════════════════════════╗
    ║ TODO(Batch 6): RE-WIRE TO concept_mastery — THIS IS CURRENTLY NEUTERED.   ║
    ╚════════════════════════════════════════════════════════════════════════╝
    This endpoint used to maintain a parallel ``topic_performance`` signal via a
    weighted moving average. Batch 5 made concept_mastery the single source of
    truth, so the parallel write is REMOVED. It now returns the CURRENT state
    without mutating any knowledge signal.

    Consequence (accepted, see Batch 5 plan): in-session checkpoints DO NOT
    contribute to mastery until Batch 6 routes per-concept outcomes through
    mastery.py (build_entry/EMA → patch_concept_mastery), keyed by concept_id.
    """
    store = get_student_context_store()
    context = store.load(student_id, course_id)
    if context is None:
        raise HTTPException(
            status_code=404,
            detail=f"No student context found for student={student_id}, course={course_id}",
        )

    logger.warning(
        "update_performance NEUTERED (TODO Batch 6): student=%s course=%s session=%s "
        "topic=%s — ignored %d session score(s); concept_mastery not updated.",
        student_id, course_id, body.session_number, body.session_topic,
        len(body.session_scores or {}),
    )

    # Return current state unchanged (no parallel signal maintained).
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

