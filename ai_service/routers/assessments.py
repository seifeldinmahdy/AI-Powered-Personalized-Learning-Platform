from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from services.assessment_service import generate_assessment_questions

router = APIRouter(prefix="/assessments", tags=["Assessments"])


class GenerateRequest(BaseModel):
    course_title: str
    num_questions: int = 6


@router.post("/generate")
async def generate_endpoint(req: GenerateRequest):
    try:
        return await generate_assessment_questions(req.course_title, req.num_questions)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/health")
async def health():
    return {"status": "ok"}
