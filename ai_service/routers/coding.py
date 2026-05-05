from fastapi import APIRouter, HTTPException
from schemas.coding import (
    TopicRequest, SubmitRequest,
    RubricRequest, RubricModel,
    EvaluateGradedRequest, GradedResultResponse,
    HintRequest, HintResponse,
)
from services.coding_service import generate_problem, evaluate_code
from services.rubric_service import generate_rubric
from services.evaluator import evaluate_submission_graded
from services.hint_service import get_hint

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
