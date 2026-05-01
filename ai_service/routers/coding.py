from fastapi import APIRouter
from schemas.coding import TopicRequest, SubmitRequest
from services.coding_service import generate_problem, evaluate_code

# Create the router with a specific prefix
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