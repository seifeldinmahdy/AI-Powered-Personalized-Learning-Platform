from pydantic import BaseModel, Field
from typing import Literal


class TopicRequest(BaseModel):
    topic: str


class SubmitRequest(BaseModel):
    question: str
    code: str


class RubricRequest(BaseModel):
    question: str


class CriterionModel(BaseModel):
    name: str
    weight: int
    description: str


class RubricModel(BaseModel):
    criteria: list[CriterionModel]
    total_points: int = 100


class EvaluateGradedRequest(BaseModel):
    question: str
    code: str
    rubric: RubricModel | None = None


class BreakdownItem(BaseModel):
    criterion: str
    earned: int
    max: int
    comment: str


class GradedResultResponse(BaseModel):
    score: int
    letter_grade: str
    status: Literal["Pass", "Needs Work", "Error"]
    breakdown: list[BreakdownItem]
    feedback: str
    hint: str


class HintRequest(BaseModel):
    question: str
    code: str = ""
    hint_level: int = Field(default=1, ge=1, le=3)


class HintResponse(BaseModel):
    hint: str
    level: int
