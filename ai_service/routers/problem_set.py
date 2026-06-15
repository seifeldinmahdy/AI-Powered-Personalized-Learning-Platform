"""
Problem Set router — post-session multi-question coding assessment.

Endpoints:
  POST /problem-set/generate
  POST /problem-set/submit
  POST /problem-set/hint
  GET  /problem-set/{problem_set_id}
  GET  /problem-set/student/{student_id}/lesson/{lesson_id}
"""

from __future__ import annotations

import asyncio
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from schemas.problem_set import (
    ProblemSetGenerateRequest,
    ProblemSetSubmitRequest,
    ProblemSetData,
    EvaluationResult,
)
from services.problem_set_service import (
    generate, evaluate_submission, generate_dynamic_hint,
    mastery_weight_for_generation,
)
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


@router.post("/regenerate")
async def regenerate_problem_set(request: ProblemSetGenerateRequest):
    """Regenerate a problem set for a lesson (student-initiated, MAX 3 per
    plan_version). The cap is pre-checked server-side so we don't spend an LLM
    generation only to be rejected; it resets when plan_version changes. The
    previous generation and ALL its attempts are retained (superseded), not
    deleted — they fed mastery and stay auditable.
    """
    from services.plan_resolver import current_plan_version
    from services import artifact_client

    pv = await asyncio.to_thread(
        current_plan_version, str(request.student_id), str(request.course_id)
    )
    if pv is not None:
        rc = await artifact_client.get_regen_count(
            str(request.student_id), str(request.course_id), str(request.lesson_id), pv
        )
        if rc and rc.get("remaining", 0) <= 0:
            raise HTTPException(
                status_code=409,
                detail=f"Regeneration limit reached ({rc.get('max')}) for this lesson.",
            )
    try:
        problem_set = await generate(request, regenerate=True)
        return problem_set.model_dump()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error("Problem set regeneration failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Regeneration failed: {e}")


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

        evaluated = [c.model_dump() for c in result.evaluated_rubric]
        gen_idx = getattr(problem_set, "generation_index", 0) or 0
        alpha, source = mastery_weight_for_generation(gen_idx)

        # Mastery moves ONLY on this genuine new attempt (anti-farming). A
        # regenerated set contributes with reduced alpha + a distinct source so a
        # fresh easy variant nudges rather than dominates. The LLM never touches
        # mastery scores — only mastery.py does.
        try:
            from services.mastery import update_concept_mastery_from_eval
            asyncio.create_task(
                update_concept_mastery_from_eval(
                    student_id=request.student_id,
                    evaluated_rubric=evaluated,
                    alpha=alpha, source=source,
                    # Lets Django evaluate the remediation trigger (Batch 11a).
                    plan_version=getattr(problem_set, "plan_version", 0) or 0,
                    course_id=str(getattr(problem_set, "course_id", "") or ""),
                )
            )
        except Exception as _me:
            logger.warning("Could not schedule mastery update: %s", _me)

        # Durable, append-only attempt — a retry is a NEW row, never an overwrite.
        try:
            from services import artifact_client
            await artifact_client.append_attempt(
                str(request.student_id), request.problem_set_id,
                question_id=request.question_id, code=request.code,
                evaluated_rubric=evaluated, hints_used=request.hints_used,
                score=result.final_score,
            )
        except Exception as _ae:
            logger.warning("Could not record problem-set attempt: %s", _ae)

        return result.model_dump()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Submission evaluation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {e}")


class HintRequest(BaseModel):
    problem_set_id: str
    question_id: str
    student_id: str
    lesson_id: str
    current_code: str = ""
    hint_number: int  # 2 = first dynamic hint, 3 = second
    evaluated_rubric: list | None = None


@router.post("/hint")
async def get_hint(request: HintRequest):
    """Generate a context-aware dynamic hint."""
    # Validate hint_number
    if request.hint_number not in (2, 3):
        raise HTTPException(status_code=400, detail="hint_number must be 2 or 3")

    # hint_number=2 requires non-empty code or evaluated_rubric
    if request.hint_number == 2:
        has_code = bool(request.current_code and request.current_code.strip())
        has_rubric = request.evaluated_rubric is not None
        if not has_code and not has_rubric:
            raise HTTPException(
                status_code=400,
                detail="Hint 2 requires either non-empty code or evaluated_rubric",
            )

    # hint_number=3 requires hint 2 to have been revealed already
    if request.hint_number == 3:
        store = get_problem_set_store()
        record = store.load_submission_record(
            request.student_id, request.lesson_id,
            request.problem_set_id, request.question_id,
        )
        hints_revealed = record.get("dynamic_hints_revealed", []) if record else []
        has_hint_2 = any(h.get("hint_number") == 2 for h in hints_revealed)
        if not has_hint_2:
            raise HTTPException(
                status_code=400,
                detail="Hint 3 requires hint 2 to be revealed first",
            )

    try:
        result = await generate_dynamic_hint(
            problem_set_id=request.problem_set_id,
            question_id=request.question_id,
            student_id=request.student_id,
            lesson_id=request.lesson_id,
            current_code=request.current_code,
            hint_number=request.hint_number,
            evaluated_rubric=request.evaluated_rubric,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Hint generation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Hint generation failed: {e}")


class SummaryViewedRequest(BaseModel):
    problem_set_id: str
    student_id: str
    lesson_id: str


@router.post("/summary-viewed")
async def summary_viewed(request: SummaryViewedRequest):
    """
    Fired when the student reaches the problem set summary screen — the genuine
    end of the lesson (the final, mastery-writing step).

    Validates the problem set exists, then:
      1. Tells Django to mark the lesson complete (server-side, awaited so it is
         recorded even if the tab closes the instant this returns).
      2. Fires the problem-set profiler (writes concept_mastery) in the background.

    Returns the completion result (incl. newly-earned achievements) so the
    frontend can surface XP/achievement toasts at the correct moment.
    """
    import asyncio

    store = get_problem_set_store()
    problem_set = store.load(
        request.student_id, request.lesson_id, request.problem_set_id
    )
    if not problem_set:
        raise HTTPException(status_code=404, detail="Problem set not found")

    # (1) Server-side lesson completion — the transition lives HERE, not in the
    # frontend's end-of-live-session call. Awaited so a closed tab can't skip it.
    completion = {}
    try:
        from services.completion import post_lesson_complete
        completion = await post_lesson_complete(
            student_id=request.student_id, lesson_id=request.lesson_id
        )
    except Exception as e:
        logger.warning("Failed to trigger server-side lesson completion: %s", e)

    # (2) Concept-mastery profiler (background).
    try:
        from services.profiler_service import run_problem_set_profiler
        asyncio.create_task(
            run_problem_set_profiler(
                student_id=request.student_id,
                problem_set_id=request.problem_set_id,
                lesson_id=request.lesson_id,
            )
        )
    except Exception as e:
        logger.warning("Failed to launch problem set profiler: %s", e)

    return {
        "status": "ok",
        "newly_earned_achievements": completion.get("newly_earned_achievements", []),
        "already_completed": completion.get("already_completed", False),
    }


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
