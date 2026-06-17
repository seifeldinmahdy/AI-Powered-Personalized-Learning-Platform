"""Pydantic v2 models for the MCQ Assessment Service.

All request/response schemas in one file.  No abstract base classes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════════════════════
# INTERNAL PIPELINE MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class AssessmentContext(BaseModel):
    """Student context consumed by the MCQ orchestrator."""

    mastery_level: Literal["Novice", "Intermediate", "Expert"]
    topic_performance: dict[str, float] = Field(default_factory=dict)
    # Authoritative per-concept knowledge signal: ``concept_id → score`` (0–1).
    # When a chunk carries a ``concept_id`` present here, difficulty is resolved
    # directly from concept mastery (no fuzzy topic matching). Same 0–1 scale as
    # topic_performance, so it buckets into the same score categories the
    # generator was trained on — no retraining required.
    concept_mastery: dict[str, float] = Field(default_factory=dict)
    incorrectly_answered: list[dict] = Field(default_factory=list)
    student_id: str
    course_id: str


class GeneratedQuestion(BaseModel):
    """Raw output from the question generator before distractor attachment."""

    question: str
    correct_answer: str
    question_type: str
    topic: str
    explanation: str
    mastery_used: str
    score_category_used: str
    generation_mode: str  # "ollama" during development, "t5" after fine-tuning


# ═══════════════════════════════════════════════════════════════════════════════
# MCQ OUTPUT MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class MCQOption(BaseModel):
    """A single answer option in a multiple-choice question."""

    text: str
    is_correct: bool


class MCQQuestion(BaseModel):
    """Complete MCQ with four options, metadata, and provenance."""

    question: str
    options: list[MCQOption] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="Exactly 4 options in randomized order",
    )
    correct_answer: str
    explanation: str
    question_type: str
    topic: str
    # Django Concept.id this question probes, carried from the source chunk.
    # Lets the checkpoint write per-CONCEPT mastery (no topic→concept fuzzing).
    concept_id: str = ""
    mastery_used: str
    score_category_used: str
    distractor_scores: list[float] | None = None
    generation_mode: str


# ═══════════════════════════════════════════════════════════════════════════════
# REQUEST MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class PlacementTestRequest(BaseModel):
    """Request to generate placement-test MCQs from chunk data."""

    chunks: list[dict] = Field(
        ...,
        description="Each dict has 'text', 'topic', 'metadata'",
    )
    course_id: str
    questions_per_topic: int = 2


class SessionAssessmentRequest(BaseModel):
    """Request to generate in-session checkpoint MCQs."""

    chunks: list[dict] = Field(
        ...,
        description="Each dict has 'text', 'topic', 'metadata'",
    )
    course_id: str
    student_id: str
    session_topic: str
    session_number: int
    context: AssessmentContext
    questions_per_chunk: int = 1
    checkpoint_index: int


# ═══════════════════════════════════════════════════════════════════════════════
# RESPONSE MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class AssessmentResponse(BaseModel):
    """Returned after generating questions for a placement or session assessment."""

    questions: list[MCQQuestion]
    total_questions: int
    generation_mode: str
    session_topic: str | None = None
    checkpoint_index: int | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# SUBMISSION / SCORING MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class CheckpointSubmission(BaseModel):
    """Submitted by frontend after a student answers checkpoint questions."""

    questions: list[MCQQuestion]
    answers: dict[int, str] = Field(
        ...,
        description="Question index → selected answer text",
    )
    student_id: str
    course_id: str
    session_number: int
    checkpoint_index: int


class CheckpointResult(BaseModel):
    """Returned after scoring a checkpoint submission."""

    score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Overall score 0.0 to 1.0",
    )
    per_topic_scores: dict[str, float]
    # Per-concept scores (concept_id → 0–1), the authoritative signal written to
    # concept mastery. Empty when the questions carried no concept_id.
    per_concept_scores: dict[str, float] = Field(default_factory=dict)
    correct_count: int
    total_count: int
    question_results: list[dict] = Field(
        ...,
        description="Per question: correct bool, chosen answer, correct answer, explanation",
    )
