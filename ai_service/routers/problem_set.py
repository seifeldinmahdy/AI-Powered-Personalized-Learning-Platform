"""
Problem Set router — post-session multi-question coding assessment.

Endpoints:
  POST /problem-set/generate
  POST /problem-set/submit
  GET  /problem-set/{problem_set_id}
  GET  /problem-set/student/{student_id}/lesson/{lesson_id}
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from schemas.problem_set import (
    ProblemSetGenerateRequest,
    ProblemSetSubmitRequest,
    ProblemSetData,
    EvaluationResult,
)
from services.problem_set_service import generate, evaluate_submission
from services.problem_set_store import get_problem_set_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/problem-set", tags=["problem-set"])


@router.post("/generate")
async def generate_problem_set(request: ProblemSetGenerateRequest):
    """Generate a problem set from session context."""
    try:
        problem_set = await generate(request)
        return problem_set.model_dump()

    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error("Problem set generation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Generation failed: {e}")


@router.post("/submit")
async def submit_answer(request: ProblemSetSubmitRequest):
    """Submit a code answer for evaluation."""
    store = get_problem_set_store()

    # Find the problem set to get the lesson_id
    # We need to search since we only have problem_set_id
    problem_set = _find_problem_set(request.problem_set_id, request.student_id)
    if not problem_set:
        raise HTTPException(status_code=404, detail="Problem set not found")

    try:
        result = await evaluate_submission(
            problem_set_id=request.problem_set_id,
            question_id=request.question_id,
            student_id=request.student_id,
            lesson_id=problem_set.lesson_id,
            code=request.code,
            language=request.language,
            hints_used=request.hints_used,
        )
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Submission evaluation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {e}")


@router.get("/{problem_set_id}")
async def get_problem_set(problem_set_id: str, student_id: str = ""):
    """Get a problem set with submissions merged."""
    problem_set = _find_problem_set(problem_set_id, student_id)
    if not problem_set:
        raise HTTPException(status_code=404, detail="Problem set not found")

    return problem_set.model_dump()


@router.get("/student/{student_id}/lesson/{lesson_id}")
async def get_student_problem_sets(student_id: str, lesson_id: str):
    """Get all problem sets for a student + lesson."""
    store = get_problem_set_store()
    problem_sets = store.find_by_student_lesson(student_id, lesson_id)

    results = []
    for ps in problem_sets:
        results.append(ps.model_dump())

    return results


def _find_problem_set(problem_set_id: str, student_id: str = "") -> ProblemSetData | None:
    """Search for a problem set by ID across all student/lesson directories."""
    store = get_problem_set_store()
    import os
    base_dir = store._dir
    if not base_dir.exists():
        return None

    for student_dir in base_dir.iterdir():
        if not student_dir.is_dir():
            continue
        if student_id and student_dir.name != student_id.replace("/", "_").replace("\\", "_").replace(":", "_"):
            continue
        for lesson_dir in student_dir.iterdir():
            if not lesson_dir.is_dir():
                continue
            result = store.load(student_dir.name, lesson_dir.name, problem_set_id)
            if result:
                return result
    return None
