"""
Assessment Router — placement test generation and submission endpoints.
"""

from __future__ import annotations

import logging
import math
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.assessment_service import generate_assessment_questions, generate_categorized_questions
from services.category_service import build_assessment_categories
from services.student_context_store import get_student_context_store
from schemas.student_context import (
    UnifiedStudentContext,
    StudentProfileState,
    LiveSessionState,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assessments", tags=["Assessments"])


# ── Request / Response schemas ───────────────────────────────────


class GenerateRequest(BaseModel):
    course_title: str
    num_questions: int = 6


class GenerateCategorizedRequest(BaseModel):
    course_title: str
    course_id: str
    total_questions: int = 50


class AnswerItem(BaseModel):
    question_id: int
    question: str
    topic: str
    chosen_option: str
    correct_option: str
    is_correct: bool


class SubmitPlacementRequest(BaseModel):
    student_id: str
    course_id: str
    course_title: str
    enrollment_id: int
    composition_mode: Literal["visual_heavy", "text_heavy", "balanced"] = "balanced"
    language_proficiency: Literal["Elementary", "Intermediate", "Advanced", "Native"] = "Intermediate"
    answers: list[AnswerItem]


class PlacementResultResponse(BaseModel):
    score_pct: int
    mastery_level: str
    strengths: list[str]
    weaknesses: list[str]
    topic_performance: dict[str, float]
    incorrectly_answered: list[dict]
    context_saved: bool


# ── Endpoints ────────────────────────────────────────────────────


@router.post("/generate")
async def generate_endpoint(req: GenerateRequest):
    """Generate placement-test questions for a course topic (flat, ungrouped)."""
    try:
        return await generate_assessment_questions(req.course_title, req.num_questions)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/generate-categorized")
async def generate_categorized_endpoint(req: GenerateCategorizedRequest):
    """Generate placement-test questions grouped by LLM-derived categories.

    Pipeline: ChromaDB topics → semantic dedup → frequency filter → LLM
    grouping (exactly 5 categories) → per-category question generation.
    """
    try:
        import asyncio
        # build_assessment_categories is CPU-bound (embedding) + blocking IO (LLM)
        # Run it in a thread pool to avoid blocking the async event loop
        categories = await asyncio.to_thread(build_assessment_categories, req.course_title)
        logger.info("Created %d categories for course '%s'", len(categories), req.course_title)

        # Distribute questions across categories
        num_categories = len(categories)
        base_per_cat = max(1, req.total_questions // num_categories)

        # Generate questions per category (runs concurrently via asyncio.gather)
        result = await generate_categorized_questions(
            course_title=req.course_title,
            categories=categories,
            questions_per_category=base_per_cat,
        )

        return {"categories": result}

    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error("Categorized generation failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/submit-placement", response_model=PlacementResultResponse)
async def submit_placement(req: SubmitPlacementRequest):
    """Score placement answers, build UnifiedStudentContext, and persist it.

    This is the single endpoint that converts raw assessment answers into
    the complete student context used by every downstream component.
    """
    total = len(req.answers)
    if total == 0:
        raise HTTPException(status_code=400, detail="No answers provided")

    correct_count = sum(1 for a in req.answers if a.is_correct)
    score_pct = round((correct_count / total) * 100)

    # ── Derive mastery level ─────────────────────────────────────
    if score_pct >= 70:
        mastery_level = "Expert"
    elif score_pct >= 40:
        mastery_level = "Intermediate"
    else:
        mastery_level = "Novice"

    # ── Per-topic scoring ────────────────────────────────────────
    topic_counts: dict[str, dict] = {}
    for a in req.answers:
        topic = a.topic or "General"
        if topic not in topic_counts:
            topic_counts[topic] = {"correct": 0, "total": 0}
        topic_counts[topic]["total"] += 1
        if a.is_correct:
            topic_counts[topic]["correct"] += 1

    topic_performance = {
        topic: round(data["correct"] / data["total"], 2)
        for topic, data in topic_counts.items()
        if data["total"] > 0
    }

    strengths = [t for t, s in topic_performance.items() if s > 0.7]
    weaknesses = [t for t, s in topic_performance.items() if s < 0.5]

    # ── Build incorrectly_answered ───────────────────────────────
    incorrectly_answered = [
        {
            "question": a.question,
            "chosen_option": a.chosen_option,
            "correct_option": a.correct_option,
        }
        for a in req.answers
        if not a.is_correct
    ]

    # ── Build UnifiedStudentContext ──────────────────────────────
    profile = StudentProfileState(
        student_id=req.student_id,
        course_id=req.course_id,
        mastery_level=mastery_level,
        composition_mode=req.composition_mode,
        language_proficiency=req.language_proficiency,
        strengths=strengths,
        weaknesses=weaknesses,
        topic_performance=topic_performance,
        incorrectly_answered=incorrectly_answered,
        use_synthetic_context=False,
        course_intent=req.course_title,
        student_profile_summary=(
            f"{mastery_level} learner in {req.course_title}. "
            f"Strong in: {', '.join(strengths) if strengths else 'no topics yet'}. "
            f"Needs work on: {', '.join(weaknesses) if weaknesses else 'no topics yet'}."
        ),
    )
    live = LiveSessionState()
    context = UnifiedStudentContext(profile=profile, live=live)

    # ── Persist ──────────────────────────────────────────────────
    store = get_student_context_store()
    store.save(req.student_id, req.course_id, context)

    logger.info(
        "placement_submitted student=%s course=%s score=%s mastery=%s strengths=%s weaknesses=%s",
        req.student_id, req.course_id, score_pct, mastery_level, strengths, weaknesses,
    )

    return PlacementResultResponse(
        score_pct=score_pct,
        mastery_level=mastery_level,
        strengths=strengths,
        weaknesses=weaknesses,
        topic_performance=topic_performance,
        incorrectly_answered=incorrectly_answered,
        context_saved=True,
    )


@router.get("/health")
async def health():
    return {"status": "ok"}
