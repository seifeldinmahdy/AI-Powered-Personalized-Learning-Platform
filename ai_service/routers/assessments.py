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
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.assessment_service import generate_assessment_questions
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
    topic: str  # concept label (kept for display); concept_id is authoritative
    concept_id: Optional[str] = None  # Django Concept.id this question probes
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
    """Generate a BACKWARD-DESIGNED placement test that probes the CLO concepts.

    The placement test now measures what the course's CLOs declare it must teach:
    the CLO concept set is fetched from Django, grouped per CLO, and questions are
    generated to COVER every concept (each question tagged with its concept_id) so
    the submission path can be concept-keyed. Questions are no longer generated
    from arbitrary discovered ChromaDB topics.
    """
    try:
        import asyncio
        from services.category_service import build_clo_assessment_plan
        from services.assessment_service import generate_clo_questions

        # Build the backward-designed plan from the course's CLO concept set.
        plan = await asyncio.to_thread(build_clo_assessment_plan, req.course_id, req.course_title)

        if not plan:
            # No CLOs/concepts authored yet — fall back to flat course-title
            # generation so placement still works (clearly not backward-designed).
            logger.warning(
                "No CLO concept plan for course '%s' — falling back to flat generation.",
                req.course_id,
            )
            flat = await generate_assessment_questions(req.course_title, req.total_questions)
            return {"categories": [{
                "name": "General",
                "description": f"General knowledge of {req.course_title}.",
                "questions": flat.get("questions", []),
            }]}

        n_concepts = sum(len(g["concepts"]) for g in plan)
        logger.info(
            "Backward-designed plan for course '%s': %d CLO group(s), %d concept(s)",
            req.course_id, len(plan), n_concepts,
        )

        result = await generate_clo_questions(
            course_title=req.course_title,
            plan=plan,
            total_questions=req.total_questions,
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
    """Score placement answers CONCEPT-KEYED, seed concept_mastery, persist context.

    Backward-designed: each question probes a CLO concept (concept_id). Results
    are aggregated per concept and written to the single knowledge signal
    (Django concept_mastery). mastery_level is DERIVED from concept mastery, and
    strengths/weaknesses are concept LABELS. topic_performance is no longer
    produced as a source of truth.
    """
    total = len(req.answers)
    if total == 0:
        raise HTTPException(status_code=400, detail="No answers provided")

    correct_count = sum(1 for a in req.answers if a.is_correct)
    score_pct = round((correct_count / total) * 100)

    # ── Per-concept scoring (concept_id authoritative; label for display) ──
    concept_stats: dict[str, dict] = {}
    label_by_concept: dict[str, str] = {}
    for a in req.answers:
        cid = str(a.concept_id) if a.concept_id else None
        if not cid:
            continue  # answers without a concept tag don't feed the knowledge signal
        st = concept_stats.setdefault(cid, {"correct": 0, "total": 0})
        st["total"] += 1
        if a.is_correct:
            st["correct"] += 1
        if a.topic:
            label_by_concept.setdefault(cid, a.topic)

    concept_scores = {
        cid: round(s["correct"] / s["total"], 4)
        for cid, s in concept_stats.items() if s["total"] > 0
    }

    # ── Seed the single knowledge signal: Django concept_mastery ──
    # Reuse the deterministic EMA entry shape so every existing reader (chart,
    # certificate, problem-set targeting, capstone) sees consistent data.
    from services.mastery import (
        fetch_concept_mastery, patch_concept_mastery, build_entry,
        derive_mastery_level,
    )

    existing_cm = await fetch_concept_mastery(req.student_id)
    cm_updates: dict[str, dict] = {}
    for cid, score in concept_scores.items():
        # Seed from a neutral prior toward the observed placement score.
        cm_updates[cid] = build_entry(existing_cm.get(cid, {}), outcome=score)
    if cm_updates:
        await patch_concept_mastery(req.student_id, cm_updates)

    # Merge for derivation/strength-weakness (existing + just-seeded)
    merged_cm = {**existing_cm, **cm_updates}
    course_concept_ids = set(concept_scores.keys()) or None
    mastery_level = derive_mastery_level(merged_cm, course_concept_ids)

    # ── strengths / weaknesses as CONCEPT LABELS (+ authoritative concept ids) ──
    strength_concept_ids = [cid for cid, s in concept_scores.items() if s > 0.7]
    weak_concept_ids = [cid for cid, s in concept_scores.items() if s < 0.5]
    strengths = sorted(label_by_concept.get(cid, cid) for cid in strength_concept_ids)
    weaknesses = sorted(label_by_concept.get(cid, cid) for cid in weak_concept_ids)

    # ── Build incorrectly_answered ───────────────────────────────
    incorrectly_answered = [
        {
            "question": a.question,
            "chosen_option": a.chosen_option,
            "correct_option": a.correct_option,
            "concept_id": str(a.concept_id) if a.concept_id else None,
        }
        for a in req.answers
        if not a.is_correct
    ]

    # ── Build UnifiedStudentContext (topic_performance intentionally empty) ──
    profile = StudentProfileState(
        student_id=req.student_id,
        course_id=req.course_id,
        mastery_level=mastery_level,
        composition_mode=req.composition_mode,
        language_proficiency=req.language_proficiency,
        strengths=strengths,
        weaknesses=weaknesses,
        strength_concept_ids=strength_concept_ids,
        weak_concept_ids=weak_concept_ids,
        topic_performance={},  # deprecated shim — concept_mastery is the source of truth
        incorrectly_answered=incorrectly_answered,
        use_synthetic_context=False,
        course_intent=req.course_title,
        student_profile_summary=(
            f"{mastery_level} learner in {req.course_title}. "
            f"Strong in: {', '.join(strengths) if strengths else 'no concepts yet'}. "
            f"Needs work on: {', '.join(weaknesses) if weaknesses else 'no concepts yet'}."
        ),
    )
    live = LiveSessionState()
    context = UnifiedStudentContext(profile=profile, live=live)

    # ── Persist ──────────────────────────────────────────────────
    store = get_student_context_store()
    store.save(req.student_id, req.course_id, context)

    logger.info(
        "placement_submitted student=%s course=%s score=%s mastery=%s "
        "concepts_scored=%d strengths=%s weaknesses=%s",
        req.student_id, req.course_id, score_pct, mastery_level,
        len(concept_scores), strengths, weaknesses,
    )

    return PlacementResultResponse(
        score_pct=score_pct,
        mastery_level=mastery_level,
        strengths=strengths,
        weaknesses=weaknesses,
        topic_performance={},  # deprecated; concept_mastery is authoritative
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
    """Score an in-session MCQ checkpoint and return the result.

    ╔════════════════════════════════════════════════════════════════════════╗
    ║ TODO(Batch 6): RE-WIRE THIS TO concept_mastery — IT IS CURRENTLY NEUTERED ║
    ╚════════════════════════════════════════════════════════════════════════╝
    This endpoint USED TO maintain a parallel ``topic_performance`` signal via a
    weighted moving average. Batch 5 collapsed the taxonomy onto concept_mastery
    (the single source of truth), so that parallel write has been REMOVED.

    Consequence (accepted, see Batch 5 plan): in-session MCQ checkpoints DO NOT
    contribute to mastery until Batch 6 closes this. Batch 6 must: tag checkpoint
    MCQs with concept_id and route per-concept outcomes through mastery.py
    (build_entry/EMA → patch_concept_mastery), exactly like the problem-set path.
    Until then we only score-and-return; we still record incorrect answers for
    the profiler, but we do NOT touch the knowledge signal.
    """
    try:
        _ensure_mcq_imports()
        from mcq.models import CheckpointSubmission  # type: ignore
        from mcq.scoring import score_checkpoint  # type: ignore

        submission = CheckpointSubmission(**req)

        # ── 1. Score the submission ──────────────────────────────
        result = score_checkpoint(submission)

        # ── 2. NEUTERED (Batch 6): do NOT write a parallel topic signal. ──
        # We still append incorrect answers so the profiler keeps working, but
        # mastery (concept_mastery) is intentionally NOT updated here yet.
        if result.question_results:
            store = get_student_context_store()
            context = store.load(submission.student_id, submission.course_id)
            if context is not None:
                for qr in result.question_results:
                    if not qr["correct"]:
                        context.profile.incorrectly_answered.append({
                            "question": qr.get("chosen_answer", ""),
                            "chosen_option": qr.get("chosen_answer", ""),
                            "correct_option": qr.get("correct_answer", ""),
                            "question_type": qr.get("question_type", ""),
                            "topic": qr.get("topic", ""),
                        })
                store.save(submission.student_id, submission.course_id, context)

        logger.warning(
            "mcq_submit NEUTERED (TODO Batch 6): scored checkpoint for student=%s "
            "course=%s session=%s but did NOT update mastery (no parallel "
            "topic_performance; concept_mastery wiring pending).",
            submission.student_id, submission.course_id,
            getattr(submission, "session_number", "?"),
        )
        return result.model_dump()

    except Exception as e:
        logger.exception("MCQ submission scoring failed")
        raise HTTPException(status_code=500, detail=str(e))
