from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from schemas.coding import (
    TopicRequest, SubmitRequest,
    RubricRequest, RubricModel,
    EvaluateGradedRequest, GradedResultResponse,
    HintRequest, HintResponse,
    CodingLabGenerateRequest, CodingLabGenerateResponse,
    CodingLabExplainRequest, CodingLabExplainResponse,
    CodingLabRunRequest, CodingLabRunResponse,
)
from services.coding_service import generate_problem, evaluate_code
from services.rubric_service import generate_rubric
from services.evaluator import evaluate_submission_graded
from services.hint_service import get_hint
from services.lab_service import generate_coding_lab, explain_lab_cell, run_lab_code

router = APIRouter(
    prefix="/api/coding",
    tags=["Coding Evaluator"]
)


@router.post("/generate")
async def generate_endpoint(req: TopicRequest):
    return await generate_problem(req.topic)


@router.post("/evaluate")
async def evaluate_endpoint(req: SubmitRequest):
    return await evaluate_code(req.question, req.code)


@router.post("/rubric", response_model=RubricModel)
async def rubric_endpoint(req: RubricRequest):
    """Generate a grading rubric for a coding problem."""
    try:
        import asyncio
        result = await asyncio.to_thread(generate_rubric, req.question)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/evaluate-graded", response_model=GradedResultResponse)
async def evaluate_graded_endpoint(req: EvaluateGradedRequest):
    """Evaluate student code and return a 0–100 score with per-criterion breakdown."""
    try:
        import asyncio
        rubric_dict = req.rubric.model_dump() if req.rubric else None
        result = await asyncio.to_thread(
            evaluate_submission_graded, req.question, req.code, rubric_dict
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/hint", response_model=HintResponse)
async def hint_endpoint(req: HintRequest):
    """Get a progressive hint for a coding problem."""
    try:
        import asyncio
        result = await asyncio.to_thread(get_hint, req.question, req.code, req.hint_level)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/labs/generate", response_model=CodingLabGenerateResponse)
async def generate_lab_endpoint(req: CodingLabGenerateRequest):
    """Generate or load a local notebook-style coding lab for a completed session."""
    try:
        return await generate_coding_lab(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/labs/explain", response_model=CodingLabExplainResponse)
async def explain_lab_endpoint(req: CodingLabExplainRequest):
    """Generate spoken tutor narration for a lab cell without requiring a tutor session."""
    try:
        return await explain_lab_cell(
            lab_title=req.lab_title,
            cell=req.cell,
            mode=req.mode,
            student_profile_summary=req.student_profile_summary,
            session_id=req.session_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/labs/run", response_model=CodingLabRunResponse)
async def run_lab_code_endpoint(req: CodingLabRunRequest):
    """Compile and execute a short Python lab snippet."""
    try:
        import asyncio
        return await asyncio.to_thread(run_lab_code, req.code, req.timeout_seconds)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Notes, questions, completion ────────────────────────────────

class CellNoteRequest(BaseModel):
    cell_id: str
    content: str
    student_id: str

class GeneralNoteRequest(BaseModel):
    content: str
    student_id: str

class QuestionAskedRequest(BaseModel):
    cell_id: str
    question_text: str
    student_id: str

class LabCompleteRequest(BaseModel):
    lab_id: str
    student_id: str
    course_id: str
    lesson_id: str


@router.post("/labs/{lab_id}/note/cell")
async def save_cell_note_endpoint(lab_id: str, req: CellNoteRequest):
    """Save a student note on a specific cell."""
    from services.lab_service import save_lab_cell_note
    parts = lab_id.split("_")
    course_id = parts[1] if len(parts) > 1 else ""
    lesson_id = parts[2] if len(parts) > 2 else ""
    await save_lab_cell_note(
        student_id=req.student_id,
        course_id=course_id,
        lesson_id=lesson_id,
        cell_id=req.cell_id,
        content=req.content,
    )
    return {"status": "ok"}


@router.post("/labs/{lab_id}/note/general")
async def save_general_note_endpoint(lab_id: str, req: GeneralNoteRequest):
    """Save a general lab note."""
    from services.lab_service import save_lab_general_note
    parts = lab_id.split("_")
    course_id = parts[1] if len(parts) > 1 else ""
    lesson_id = parts[2] if len(parts) > 2 else ""
    await save_lab_general_note(
        student_id=req.student_id,
        course_id=course_id,
        lesson_id=lesson_id,
        content=req.content,
    )
    return {"status": "ok"}


@router.post("/labs/{lab_id}/question/asked")
async def mark_question_asked_endpoint(lab_id: str, req: QuestionAskedRequest):
    """Mark a suggested question as asked."""
    from services.lab_service import mark_lab_question_asked
    parts = lab_id.split("_")
    course_id = parts[1] if len(parts) > 1 else ""
    lesson_id = parts[2] if len(parts) > 2 else ""
    await mark_lab_question_asked(
        student_id=req.student_id,
        course_id=course_id,
        lesson_id=lesson_id,
        cell_id=req.cell_id,
        question_text=req.question_text,
    )
    return {"status": "ok"}


# How long /labs/complete will wait for the lab profiler before returning. The
# profiler updates the Django learning profile that the NEXT step (problem-set
# generation) reads, so we wait for it to land — bounded so a slow LLM can't hang
# the request (on timeout it finishes in the background, shielded).
LAB_PROFILER_WAIT_SECONDS = 30


@router.post("/labs/complete")
async def complete_lab_endpoint(req: LabCompleteRequest):
    """Mark the lab complete, then run the lab profiler BEFORE returning.

    Running the profiler synchronously (bounded) closes the race where the
    problem set was generated against a STALE learning profile: the client awaits
    this call before navigating to the problem set, so the profile is updated
    first. On timeout the profiler keeps running in the background and the problem
    set just uses the prior profile.
    """
    import asyncio
    import logging
    from services.lab_service import mark_lab_completed
    from services.profiler_service import run_lab_profiler

    log = logging.getLogger(__name__)
    try:
        await mark_lab_completed(
            student_id=req.student_id,
            course_id=req.course_id,
            lesson_id=req.lesson_id,
        )
    except Exception:
        log.warning("lab complete: durable persist failed (lab_id=%s)", req.lab_id, exc_info=True)

    profile_updated = False
    task = asyncio.create_task(
        run_lab_profiler(
            student_id=req.student_id,
            lab_id=req.lab_id,
            course_id=req.course_id,
            lesson_id=req.lesson_id,
        )
    )
    try:
        # shield → a timeout stops us WAITING but never cancels the profiler.
        await asyncio.wait_for(asyncio.shield(task), timeout=LAB_PROFILER_WAIT_SECONDS)
        profile_updated = True
    except asyncio.TimeoutError:
        log.info("lab complete: profiler still running after %ss (lab_id=%s) — continuing",
                 LAB_PROFILER_WAIT_SECONDS, req.lab_id)
    except Exception:
        log.warning("lab complete: profiler failed (lab_id=%s)", req.lab_id, exc_info=True)
    return {"status": "ok", "profile_updated": profile_updated}

