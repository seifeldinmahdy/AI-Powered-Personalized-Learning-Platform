from fastapi import APIRouter, HTTPException
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
        import asyncio
        return await asyncio.to_thread(generate_coding_lab, req)
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
