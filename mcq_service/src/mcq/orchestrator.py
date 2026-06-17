"""MCQ Orchestrator — coordinates the full question generation pipeline.

Pipeline per chunk:
  1. selector.select_question_type()  →  question type + score category
  2. qg.generate_question()           →  GeneratedQuestion
  3. dg.generate_mcq()                →  MCQQuestion (with distractors)

Handles both placement tests (no student context) and session assessments
(full three-signal personalization).
"""

from __future__ import annotations

import sys
from pathlib import Path

import structlog

from mcq.dg import generate_mcq
from mcq.models import (
    AssessmentContext,
    AssessmentResponse,
    MCQQuestion,
    PlacementTestRequest,
    SessionAssessmentRequest,
)
from mcq.qg import generate_question
from mcq.selector import select_question_type

logger = structlog.get_logger(__name__)

# Lazy-loaded embedder singleton
_embedder = None


def _get_embedder():
    """Load the sentence-transformer embedder singleton.

    Reuses the same model loaded by ai_service's category_service if available,
    otherwise loads a lightweight model directly.
    """
    global _embedder
    if _embedder is not None:
        return _embedder

    try:
        ai_service_dir = str(
            Path(__file__).resolve().parent.parent.parent.parent / "ai_service"
        )
        if ai_service_dir not in sys.path:
            sys.path.insert(0, ai_service_dir)

        from services.category_service import _get_embedder as _ai_get_embedder
        _embedder = _ai_get_embedder()
    except Exception:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("mcq_embedder_loaded_standalone", model="all-MiniLM-L6-v2")

    return _embedder


def generate_placement_assessment(
    request: PlacementTestRequest,
    settings,
) -> AssessmentResponse:
    """Generate a placement test — no student context, uses Novice defaults.

    Parameters
    ----------
    request :
        The placement test request with chunks and course ID.
    settings :
        MCQSettings instance.

    Returns
    -------
    AssessmentResponse
        Generated questions ready for the frontend.
    """
    context = AssessmentContext(
        mastery_level="Novice",
        topic_performance={},
        incorrectly_answered=[],
        student_id="placement",
        course_id=request.course_id,
    )

    questions: list[MCQQuestion] = []
    embedder = _get_embedder()

    # Group chunks by topic
    topic_chunks: dict[str, list[dict]] = {}
    for chunk in request.chunks:
        topic = chunk.get("topic", "General")
        topic_chunks.setdefault(topic, []).append(chunk)

    for topic, chunks in topic_chunks.items():
        generated_for_topic = 0
        for chunk in chunks:
            if generated_for_topic >= request.questions_per_topic:
                break

            mcq = _generate_single_mcq(
                chunk_text=chunk.get("text", ""),
                chunk_topic=topic,
                context=context,
                embedder=embedder,
                settings=settings,
            )
            if mcq is not None:
                questions.append(mcq)
                generated_for_topic += 1

    generation_mode = "llama_lora" if settings.QG_LORA_PATH else "ollama"

    logger.info(
        "placement_assessment_generated",
        course_id=request.course_id,
        total_questions=len(questions),
        mode=generation_mode,
    )

    return AssessmentResponse(
        questions=questions,
        total_questions=len(questions),
        generation_mode=generation_mode,
    )


def generate_session_assessment(
    request: SessionAssessmentRequest,
    settings,
) -> AssessmentResponse:
    """Generate a session checkpoint assessment with full personalization.

    Uses the three signals: global mastery, per-topic score category,
    and incorrectly-answered history.

    Parameters
    ----------
    request :
        Session assessment request with chunks and student context.
    settings :
        MCQSettings instance.

    Returns
    -------
    AssessmentResponse
        Generated questions with session metadata.
    """
    context = request.context
    questions: list[MCQQuestion] = []
    embedder = _get_embedder()

    for chunk in request.chunks:
        for _ in range(request.questions_per_chunk):
            mcq = _generate_single_mcq(
                chunk_text=chunk.get("text", ""),
                chunk_topic=chunk.get("topic", request.session_topic),
                chunk_concept_id=chunk.get("concept_id"),
                context=context,
                embedder=embedder,
                settings=settings,
            )
            if mcq is not None:
                questions.append(mcq)

    generation_mode = "llama_lora" if settings.QG_LORA_PATH else "ollama"

    logger.info(
        "session_assessment_generated",
        student_id=request.student_id,
        course_id=request.course_id,
        session_number=request.session_number,
        checkpoint_index=request.checkpoint_index,
        total_questions=len(questions),
        mode=generation_mode,
    )

    return AssessmentResponse(
        questions=questions,
        total_questions=len(questions),
        generation_mode=generation_mode,
        session_topic=request.session_topic,
        checkpoint_index=request.checkpoint_index,
    )


def _generate_single_mcq(
    chunk_text: str,
    chunk_topic: str,
    context: AssessmentContext,
    embedder,
    settings,
    chunk_concept_id: str | None = None,
) -> MCQQuestion | None:
    """Full pipeline for a single chunk → MCQQuestion.

    1. Select question type
    2. Generate question (QG)
    3. Generate distractors (DG)

    Returns None if any stage fails.
    """
    # ── 1. Type selection ───────────────────────────────────────────
    question_type, score_category, topic_score = select_question_type(
        chunk_text=chunk_text,
        chunk_topic=chunk_topic,
        mastery_level=context.mastery_level,
        topic_performance=context.topic_performance,
        incorrectly_answered=context.incorrectly_answered,
        embedder=embedder,
        settings=settings,
        chunk_concept_id=chunk_concept_id,
        concept_mastery=context.concept_mastery,
    )

    # ── 2. Question generation ──────────────────────────────────────
    generated_q = generate_question(
        chunk_text=chunk_text,
        topic=chunk_topic,
        question_type=question_type,
        mastery_level=context.mastery_level,
        score_category=score_category,
        settings=settings,
    )

    if generated_q is None:
        logger.warning(
            "mcq_qg_failed",
            topic=chunk_topic,
            type=question_type,
        )
        return None

    # ── 3. Distractor generation ────────────────────────────────────
    mcq = generate_mcq(
        generated_q=generated_q,
        settings=settings,
        chunk_text=chunk_text,
    )

    if mcq is None:
        logger.warning(
            "mcq_dg_failed",
            topic=chunk_topic,
            question=generated_q.question[:60],
        )
        return None

    # Carry the source chunk's concept so the checkpoint can write per-concept
    # mastery on submission (closing the difficulty loop without topic fuzzing).
    if chunk_concept_id:
        mcq.concept_id = str(chunk_concept_id)

    return mcq
