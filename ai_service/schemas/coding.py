from pydantic import BaseModel, Field
from typing import Literal, Optional


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


class LabSlideContext(BaseModel):
    title: str = ""
    content: str = ""
    code: str = ""


class CodingLabGenerateRequest(BaseModel):
    student_id: str = ""
    course_id: str
    lesson_id: str
    lesson_title: str
    session_id: Optional[str] = None
    student_profile_summary: str = ""
    slides: list[LabSlideContext] = Field(default_factory=list)
    force_regenerate: bool = False


class LabChecklistItem(BaseModel):
    id: str
    item: str
    reason: str = ""


class LabCell(BaseModel):
    id: str
    cell_type: Literal["explanation", "code", "task"] = "explanation"
    title: str
    narrative: str = ""
    code: str = ""
    expected_output: str = ""
    task_prompt: str = ""
    starter_code: str = ""
    success_criteria: list[str] = Field(default_factory=list)
    tutor_script: str = ""
    tips: list[str] = Field(default_factory=list)
    student_notes: list[dict] = Field(default_factory=list)
    # Each note: {"content": str, "timestamp": str}  # ISO UTC
    suggested_questions: list[dict] = Field(default_factory=list)
    # Each question: {"question": str, "was_asked": bool}


class CodingLab(BaseModel):
    title: str
    intro: str
    estimated_minutes: int = 15
    tutor_opening: str = ""
    cells: list[LabCell]
    completion_message: str = "Lab complete. You are ready for the coding question."
    general_notes: list[dict] = Field(default_factory=list)
    # Each note: {"content": str, "timestamp": str}  # ISO UTC


class CodingLabGenerateResponse(BaseModel):
    lab_id: str
    cached: bool = False
    generated_at: str
    checklist: list[LabChecklistItem]
    lab: CodingLab
    completed_at: str = ""


class CodingLabExplainRequest(BaseModel):
    session_id: Optional[str] = None
    lab_title: str = ""
    cell: LabCell
    mode: Literal["explain", "tip"] = "explain"
    student_profile_summary: str = ""


class CodingLabExplainResponse(BaseModel):
    success: bool = True
    text: str
    audio_base64: Optional[str] = None
    blendshapes: Optional[dict] = None


class CodingLabRunRequest(BaseModel):
    code: str
    timeout_seconds: int = Field(default=5, ge=1, le=10)


class CodingLabRunResponse(BaseModel):
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
