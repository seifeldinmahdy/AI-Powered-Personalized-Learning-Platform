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
    pathway_ready: bool = False  # True once the pathway was generated server-side
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
        # Guard: if every category came back empty (e.g. the upstream LLM is
        # rate-limited or down), fail loudly with a 502 instead of returning a
        # valid-but-empty 200 that the client would silently render as a blank quiz.
        total_generated = sum(len(c.get("questions", [])) for c in result)
        if total_generated == 0:
            logger.error(
                "Categorized generation produced 0 questions for course '%s' "
                "(%d categories) — upstream LLM likely unavailable or rate-limited",
                req.course_title, len(categories),
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    "Question generation produced no questions. The AI model may be "
                    "unavailable or rate-limited. Please try again."
                ),
            )

        return {"categories": result}

    except HTTPException:
        raise
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

    # ── Seed the single knowledge signal via the ONE writer ──
    # Placement results are recorded as 'assessment' events (alpha=1.0 → the
    # server fold from the 0.5 prior lands exactly on the observed score).
    from services.mastery import (
        fetch_concept_mastery, post_mastery_events, derive_mastery_level,
    )

    events = [
        {"concept_id": cid, "outcome": score, "source": "assessment", "alpha": 1.0}
        for cid, score in concept_scores.items()
    ]
    if events:
        await post_mastery_events(req.student_id, events)

    # Re-read the updated projection to derive the live mastery_level.
    merged_cm = await fetch_concept_mastery(req.student_id)
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

    # ── Durable, immutable PlacementAttempt event ────────────────
    # Append-only: a re-take is a NEW row, never an overwrite. The
    # UnifiedStudentContext snapshot persisted below is DERIVED from this (the
    # latest) submission; prior attempts stay immutable + auditable in Django.
    try:
        from services.artifact_client import post_placement_attempt
        await post_placement_attempt(
            req.student_id, req.course_id,
            answers=[a.model_dump() for a in req.answers],
            per_question=[{
                "question": a.question, "chosen_option": a.chosen_option,
                "correct_option": a.correct_option, "is_correct": a.is_correct,
                "concept_id": str(a.concept_id) if a.concept_id else None,
            } for a in req.answers],
            score=score_pct, concept_results=concept_scores,
        )
    except Exception:
        logger.warning("placement: could not record PlacementAttempt event", exc_info=True)

    # ── Persist (derived snapshot) ───────────────────────────────
    store = get_student_context_store()
    store.save(req.student_id, req.course_id, context)

    logger.info(
        "placement_submitted student=%s course=%s score=%s mastery=%s "
        "concepts_scored=%d strengths=%s weaknesses=%s",
        req.student_id, req.course_id, score_pct, mastery_level,
        len(concept_scores), strengths, weaknesses,
    )

    # ── Generate the pathway ONCE, server-side, now (UX shows "building…") ──
    # This is the single trigger and the single writer of is_pathway_ready.
    pathway_ready = False
    try:
        import asyncio
        from services.pathway_trigger import generate_after_placement, mark_pathway_ready
        pathway_ready = await asyncio.to_thread(
            generate_after_placement, req.student_id, req.course_id, profile,
        )
        if pathway_ready:
            await asyncio.to_thread(mark_pathway_ready, req.enrollment_id, req.student_id)
    except Exception:
        logger.exception("placement: pathway generation trigger failed")

    return PlacementResultResponse(
        score_pct=score_pct,
        mastery_level=mastery_level,
        pathway_ready=pathway_ready,
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

        # ── Enrich with the authoritative per-concept knowledge signal ──
        # Difficulty is resolved from concept mastery when a chunk is concept-
        # tagged (same 0–1 scale → same score categories the generator was
        # trained on). We fill both server-side so callers don't have to:
        #   (1) concept_mastery from the single mastery projection, and
        #   (2) concept_id per chunk via exact concept-label match.
        # Best-effort: on any failure we silently keep the topic-based path.
        try:
            from services.mastery import fetch_concept_mastery, fetch_course_concepts

            if not session_req.context.concept_mastery:
                cm = await fetch_concept_mastery(session_req.student_id)
                session_req.context.concept_mastery = {
                    str(cid): float(v["score"])
                    for cid, v in cm.items()
                    if isinstance(v, dict) and v.get("score") is not None
                }

            if any(not c.get("concept_id") for c in session_req.chunks):
                concepts = await fetch_course_concepts(session_req.course_id)
                label_to_id = {
                    str(c["label"]).strip().lower(): str(c["id"]) for c in concepts
                }
                for c in session_req.chunks:
                    if not c.get("concept_id"):
                        cid = label_to_id.get(str(c.get("topic", "")).strip().lower())
                        if cid:
                            c["concept_id"] = cid
        except Exception:
            logger.warning(
                "MCQ concept-mastery enrichment failed; using topic path",
                exc_info=True,
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
    """Score an in-session MCQ checkpoint and record concept-mastery events.

    When the checkpoint questions are concept-tagged, the per-CONCEPT scores are
    written to the SINGLE mastery writer as ``source="checkpoint"`` events keyed
    by ``concept_id`` — the authoritative, no-fuzzing path (same as placement,
    just a lighter alpha). Questions that carried no concept fall back to the
    legacy topic-keyed write (mapped server-side, floored).
    """
    try:
        _ensure_mcq_imports()
        from mcq.models import CheckpointSubmission  # type: ignore
        from mcq.scoring import score_checkpoint  # type: ignore
        from services.mastery import post_mastery_events

        submission = CheckpointSubmission(**req)
        result = score_checkpoint(submission)

        # Prefer concept-keyed events (direct, no topic→concept fuzzing). Fall
        # back to topic-keyed only for questions that carried no concept_id.
        per_concept = getattr(result, "per_concept_scores", None) or {}
        per_topic = getattr(result, "per_topic_scores", None) or {}
        events = [
            {
                "concept_id": cid,
                "course_id": str(submission.course_id),
                "outcome": float(score),
                "source": "checkpoint",
                "alpha": 0.3,
            }
            for cid, score in per_concept.items()
        ]
        if not events and per_topic:
            events = [
                {
                    "topic": topic,
                    "course_id": str(submission.course_id),
                    "outcome": float(score),
                    "source": "checkpoint",
                    "alpha": 0.3,
                }
                for topic, score in per_topic.items()
            ]
        if events:
            await post_mastery_events(submission.student_id, events)

        # Keep recording incorrect answers for the profiler (unchanged).
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
                            "concept_id": qr.get("concept_id") or None,
                        })
                store.save(submission.student_id, submission.course_id, context)

        return result.model_dump()

    except Exception as e:
        logger.exception("MCQ submission scoring failed")
        raise HTTPException(status_code=500, detail=str(e))
