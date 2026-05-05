"""
Student Context Router — retrieval endpoint for persisted student context.

Provides ``GET /student-context/{student_id}/{course_id}`` so every
downstream component (pathway generator, slides generator, tutor) can
read the student's placement-derived context without the frontend
re-passing it on every request.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from services.student_context_store import get_student_context_store

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/student-context",
    tags=["Student Context"],
)


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
        logger.warning(
            "student_context_not_found",
            student_id=student_id,
            course_id=course_id,
        )
        raise HTTPException(
            status_code=404,
            detail=f"No student context found for student={student_id}, course={course_id}",
        )

    logger.info(
        "student_context_retrieved",
        student_id=student_id,
        course_id=course_id,
        mastery=context.profile.mastery_level,
    )
    return context.model_dump()
