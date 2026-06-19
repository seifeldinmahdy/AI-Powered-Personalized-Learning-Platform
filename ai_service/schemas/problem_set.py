"""
Pydantic v2 schemas for the post-session Problem Set feature.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
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
    # Identity is set server-side from the verified X-Student-ID header; the
    # router overwrites this before any read. Optional so the Django proxy can
    # strip the browser-supplied value without breaking construction.
    student_id: str = ""
    course_id: str
    lesson_id: str
    lesson_title: str = ""
    student_profile_summary: str = ""
    slides: list[SlideContext] = Field(default_factory=list)
    lab_cells: list[LabCellContext] = Field(default_factory=list)


class ProblemSetSubmitRequest(BaseModel):
    problem_set_id: str
    question_id: str
    # Set server-side from the verified header; router overwrites before any read.
    student_id: str = ""
    code: str
    language: str = "python"
    hints_used: int = Field(default=0, ge=0, le=3)


# ── Core data models ───────────────────────────────────────────

class RubricCategory(str, Enum):
    CORRECTNESS = "correctness"
    LOGIC = "logic"
    EDGE_CASES = "edge_cases"
    SYNTAX_STYLE = "syntax_style"
    REQUIREMENTS = "requirements"


class RubricCheck(BaseModel):
    id: str           # pattern: r1c1, r1c2, r2c1, etc.
    question: str     # unambiguous yes/no question answerable by reading source text
    weight: float     # fraction of this criterion's score. all checks in one criterion must sum to 1.0
    result: bool | None = None    # None at generation, filled by evaluator
    evidence: str | None = None   # None at generation, filled by evaluator


class RubricCriterion(BaseModel):
    id: str                    # pattern: r1, r2, r3, etc.
    category: RubricCategory   # exactly one of the 5 standard categories
    name: str                  # human-readable name
    weight: float              # percentage of total score. all criteria sum to 100
    checks: list[RubricCheck]  # 2 to 4 checks per criterion
    concept_id: Optional[str] = None  # concept this criterion targets (set by generator, used by mastery.py)


class RubricScore(BaseModel):
    criterion: str
    category: str = ""
    earned: int = 0
    max: int = 0
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
    static_hint: str = "Think carefully about what the problem requires."
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
    evaluated_rubric: list[RubricCriterion] = Field(default_factory=list)
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
    # Durable-store coordinates (Batch 10a). plan_version pins the artifact to a
    # pathway version; generation_index marks regenerations (0 = original).
    plan_version: int = 0
    generation_index: int = 0
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    questions: list[ProblemSetQuestion] = Field(default_factory=list)
    submissions: dict[str, SubmissionData] = Field(default_factory=dict)
