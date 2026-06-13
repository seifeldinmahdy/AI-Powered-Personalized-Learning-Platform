"""
Assessment Router — placement test generation/submission + MCQ session endpoints.

Existing endpoints (placement test — implemented separately):
  POST /assessments/generate
  POST /assessments/generate-categorized
  POST /assessments/submit-placement
  GET  /assessments/health

New MCQ service endpoints (session assessments only):
  POST /assessments/session   — generate session checkpoint MCQs
  POST /assessments/submit    — score checkpoint and update student context
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.assessment_service import generate_assessment_questions, generate_categorized_questions
from services.category_service import build_assessment_categories, _get_embedder
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


# ── Existing Endpoints (placement — unchanged) ───────────────────


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

        # Resolve the corpus scope server-side from the Django course id. The
        # assessment generator is a first-class retrieval consumer: it must read
        # topics from this course's corpus only, never an unscoped/fuzzy match.
        from pathway.corpus_resolver import resolve_corpus_id  # type: ignore
        from src.retrieval.retrieval_service import RetrievalScope  # type: ignore

        corpus_id = resolve_corpus_id(req.course_id)
        if not corpus_id:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No corpus is defined for course '{req.course_id}'. An admin "
                    f"must create the course corpus and add sources first."
                ),
            )
        scope = RetrievalScope(corpus_id=corpus_id, course_id=req.course_id)

        # build_assessment_categories is CPU-bound (embedding) + blocking IO (LLM)
        # Run it in a thread pool to avoid blocking the async event loop
        categories = await asyncio.to_thread(build_assessment_categories, req.course_title, scope)
        logger.info(
            "Created %d categories for course '%s' (corpus '%s')",
            len(categories), req.course_title, corpus_id,
        )

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

    except HTTPException:
        raise
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


# ═══════════════════════════════════════════════════════════════════════════════
# MCQ SERVICE — LAZY IMPORTS AND SINGLETON
# ═══════════════════════════════════════════════════════════════════════════════

_mcq_modules_loaded = False
_mcq_settings = None


def _ensure_mcq_imports():
    """Add mcq_service paths to sys.path once."""
    global _mcq_modules_loaded
    if _mcq_modules_loaded:
        return
    mcq_src = str(Path(__file__).resolve().parent.parent.parent / "mcq_service" / "src")
    mcq_config = str(Path(__file__).resolve().parent.parent.parent / "mcq_service")
    for p in (mcq_src, mcq_config):
        if p not in sys.path:
            sys.path.insert(0, p)
    _mcq_modules_loaded = True


def _get_mcq_settings():
    """Get or create MCQ settings singleton."""
    global _mcq_settings
    if _mcq_settings is not None:
        return _mcq_settings
    _ensure_mcq_imports()
    from config.settings import get_settings as _get_settings  # type: ignore
    _mcq_settings = _get_settings()
    return _mcq_settings


# ═══════════════════════════════════════════════════════════════════════════════
# POST /assessments/session
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/session")
async def mcq_session_endpoint(req: dict):
    """Generate MCQ session checkpoint via the mcq_service pipeline.

    Accepts SessionAssessmentRequest body.
    Validates student context exists before generation.
    Returns AssessmentResponse.
    """
    import asyncio

    try:
        _ensure_mcq_imports()
        from mcq.models import SessionAssessmentRequest  # type: ignore
        from mcq.orchestrator import generate_session_assessment  # type: ignore

        session_req = SessionAssessmentRequest(**req)

        # Validate chunks are non-empty
        if not session_req.chunks:
            raise HTTPException(
                status_code=422,
                detail="Chunks list is empty — cannot generate questions.",
            )

        # Validate student context exists
        store = get_student_context_store()
        student_context = store.load(session_req.student_id, session_req.course_id)
        if student_context is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No student context found for student={session_req.student_id}, "
                    f"course={session_req.course_id}. Complete placement test first."
                ),
            )

        # Verify request context matches stored context
        if (session_req.context.student_id != session_req.student_id or
                session_req.context.course_id != session_req.course_id):
            raise HTTPException(
                status_code=422,
                detail="context.student_id/course_id must match request student_id/course_id.",
            )

        settings = _get_mcq_settings()
        response = await asyncio.to_thread(
            generate_session_assessment, session_req, settings,
        )
        return response.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("MCQ session generation failed")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════════════
# POST /assessments/submit
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/submit")
async def mcq_submit_endpoint(req: dict):
    """Score a checkpoint submission and update student context.

    1. Score answers via score_checkpoint
    2. Update topic_performance via weighted moving average
    3. Append incorrect answers to student context
    4. Return CheckpointResult
    """
    try:
        _ensure_mcq_imports()
        from mcq.models import CheckpointSubmission  # type: ignore
        from mcq.scoring import score_checkpoint  # type: ignore

        submission = CheckpointSubmission(**req)

        # ── 1. Score the submission ──────────────────────────────
        result = score_checkpoint(submission)

        # ── 2. Update student context ────────────────────────────
        if result.per_topic_scores:
            store = get_student_context_store()
            context = store.load(submission.student_id, submission.course_id)

            if context is not None:
                from services.topic_mastery import update_topic_performance_scores

                settings = _get_mcq_settings()
                weight = settings.TOPIC_PERFORMANCE_UPDATE_WEIGHT

                update_result = update_topic_performance_scores(
                    current_performance=context.profile.topic_performance,
                    session_scores=result.per_topic_scores,
                    weight=weight,
                )

                context.profile.topic_performance = update_result["topic_performance"]
                context.profile.strengths = update_result["strengths"]
                context.profile.weaknesses = update_result["weaknesses"]

                # ── 3. Append incorrect answers ──────────────────
                for qr in result.question_results:
                    if not qr["correct"]:
                        context.profile.incorrectly_answered.append({
                            "question": qr.get("chosen_answer", ""),
                            "chosen_option": qr.get("chosen_answer", ""),
                            "correct_option": qr.get("correct_answer", ""),
                            "question_type": qr.get("question_type", ""),
                            "topic": qr.get("topic", ""),
                        })

                # Regenerate summary
                mastery = context.profile.mastery_level
                intent = context.profile.course_intent or submission.course_id
                parts = [f"{mastery} learner in {intent}."]
                if context.profile.strengths:
                    parts.append(f"Strong in: {', '.join(context.profile.strengths)}.")
                if context.profile.weaknesses:
                    parts.append(f"Needs work on: {', '.join(context.profile.weaknesses)}.")
                context.profile.student_profile_summary = " ".join(parts)

                # Persist atomically
                store.save(submission.student_id, submission.course_id, context)

                logger.info(
                    "mcq_submit_context_updated student=%s course=%s session=%d "
                    "checkpoint=%d score=%.2f",
                    submission.student_id, submission.course_id,
                    submission.session_number, submission.checkpoint_index,
                    result.score,
                )

        return result.model_dump()

    except Exception as e:
        logger.exception("MCQ submission scoring failed")
        raise HTTPException(status_code=500, detail=str(e))
