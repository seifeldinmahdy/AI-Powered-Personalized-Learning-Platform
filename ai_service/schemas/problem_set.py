"""
Pydantic v2 schemas for the post-session Problem Set feature.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


# ── Request / Response schemas ──────────────────────────────────

class SlideContext(BaseModel):
    title: str = ""
    content: str = ""
    code: str = ""


class LabCellContext(BaseModel):
    id: str = ""
    cell_type: str = ""
    title: str = ""
    narrative: str = ""
    code: str = ""
    starter_code: str = ""
    task_prompt: str = ""


class ProblemSetGenerateRequest(BaseModel):
    session_id: str = ""
    student_id: str
    course_id: str
    lesson_id: str
    lesson_title: str = ""
    student_profile_summary: str = ""
    slides: list[SlideContext] = Field(default_factory=list)
    lab_cells: list[LabCellContext] = Field(default_factory=list)


class ProblemSetSubmitRequest(BaseModel):
    problem_set_id: str
    question_id: str
    student_id: str
    code: str
    language: str = "python"
    hints_used: int = Field(default=0, ge=0, le=3)


# ── Core data models ───────────────────────────────────────────

class RubricCriterion(BaseModel):
    name: str
    description: str
    weight: int = Field(default=20, ge=0, le=100)  # percentage weight


class RubricScore(BaseModel):
    criterion: str
    score: int = Field(default=0, ge=0, le=100)
    comment: str = ""


class ProblemSetQuestion(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic: str
    title: str
    scenario_framing: str
    problem_statement: str
    starter_code: str
    rubric: list[RubricCriterion] = Field(default_factory=list)
    example_solution: str = ""  # possible reference answer (not the only correct one)
    hints: list[str] = Field(default_factory=list, min_length=0, max_length=3)
    analogy_explanation: str
    difficulty: str = "medium"
    target_weakness: Optional[str] = None
    language: str = "python"


class EvaluationResult(BaseModel):
    raw_score: int = 0
    hint_penalty: int = 0
    final_score: int = 0
    passed: bool = False
    feedback: str = ""
    rubric_scores: list[RubricScore] = Field(default_factory=list)
    mistake_tags: list[str] = Field(default_factory=list)
    hint_to_show: Optional[str] = None
    example_solution: str = ""  # possible reference answer for student comparison


class SubmissionData(BaseModel):
    code: str
    hints_used: int = 0
    submitted_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    result: EvaluationResult = Field(default_factory=EvaluationResult)


class ProblemSetData(BaseModel):
    problem_set_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    student_id: str
    lesson_id: str
    course_id: str = ""
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    questions: list[ProblemSetQuestion] = Field(default_factory=list)
    submissions: dict[str, SubmissionData] = Field(default_factory=dict)
