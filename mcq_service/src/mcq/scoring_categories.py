"""Scoring categories — maps raw topic performance floats to named categories.

Provides utilities for resolving a topic name to a performance score using
exact string matching, semantic matching (via the existing topic_mastery.py
in ai_service), or mastery-based defaults.  Never raises.
"""

from __future__ import annotations

import logging

import structlog

logger = structlog.get_logger(__name__)
_stdlib_logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# MASTERY → DEFAULT SCORE
# ═══════════════════════════════════════════════════════════════════════════════

_MASTERY_DEFAULT_SCORES: dict[str, float] = {
    "Novice": 0.3,
    "Intermediate": 0.6,
    "Expert": 0.85,
}


# ═══════════════════════════════════════════════════════════════════════════════
# CORE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


def get_score_category(score: float, settings) -> str:
    """Convert a raw topic performance float to a named category.

    Uses configurable thresholds from the settings object — never hardcoded.

    Parameters
    ----------
    score :
        Per-topic score (0.0–1.0).
    settings :
        An MCQSettings instance (or any object with the threshold attributes).

    Returns
    -------
    str
        One of ``"very_weak"``, ``"weak"``, ``"moderate"``, ``"strong"``.
    """
    if score < settings.SCORE_VERY_WEAK_THRESHOLD:
        return "very_weak"
    if score < settings.SCORE_WEAK_THRESHOLD:
        return "weak"
    if score < settings.SCORE_MODERATE_THRESHOLD:
        return "moderate"
    return "strong"


def get_effective_score(
    topic: str,
    topic_performance: dict[str, float],
    global_mastery: str,
    embedder,
    settings,
) -> tuple[float, str]:
    """Resolve a topic name to a performance score.

    Resolution order:
    1. Exact case-insensitive string match against ``topic_performance`` keys.
    2. Semantic match via ``match_topic_to_performance`` from ai_service.
    3. Mastery-based default (Novice=0.3, Intermediate=0.6, Expert=0.85).

    Parameters
    ----------
    topic :
        Topic name to look up.
    topic_performance :
        Student's ``topic → score`` dict from placement / session assessments.
    global_mastery :
        The student's global mastery level.
    embedder :
        A sentence-transformers model (or mock) for semantic matching.
    settings :
        MCQSettings instance (unused currently, reserved for threshold tuning).

    Returns
    -------
    (score, source)
        ``score`` is 0.0–1.0, ``source`` is one of
        ``"direct_match"``, ``"semantic_match"``, ``"mastery_fallback"``.
    """
    fallback_score = _MASTERY_DEFAULT_SCORES.get(global_mastery, 0.3)

    try:
        if not topic or not topic.strip():
            return fallback_score, "mastery_fallback"

        if not topic_performance:
            return fallback_score, "mastery_fallback"

        # ── 1. Exact case-insensitive match ─────────────────────────────
        topic_lower = topic.strip().lower()
        for key, score in topic_performance.items():
            if key.strip().lower() == topic_lower:
                logger.debug(
                    "topic_score_resolved",
                    topic=topic,
                    matched_key=key,
                    score=score,
                    source="direct_match",
                )
                return score, "direct_match"

        # ── 2. Semantic match via topic_mastery.py ──────────────────────
        try:
            import sys
            from pathlib import Path

            ai_service_dir = str(
                Path(__file__).resolve().parent.parent.parent.parent / "ai_service"
            )
            if ai_service_dir not in sys.path:
                sys.path.insert(0, ai_service_dir)

            from services.topic_mastery import match_topic_to_performance

            matched_score, matched_key = match_topic_to_performance(
                topic,
                topic_performance,
                _embedder=embedder,
            )

            if matched_score is not None and matched_key is not None:
                logger.debug(
                    "topic_score_resolved",
                    topic=topic,
                    matched_key=matched_key,
                    score=matched_score,
                    source="semantic_match",
                )
                return matched_score, "semantic_match"

        except Exception:
            _stdlib_logger.debug(
                "semantic_match_failed for topic=%s, falling back to mastery default",
                topic,
                exc_info=True,
            )

        # ── 3. Mastery fallback ─────────────────────────────────────────
        logger.debug(
            "topic_score_fallback",
            topic=topic,
            mastery=global_mastery,
            score=fallback_score,
        )
        return fallback_score, "mastery_fallback"

    except Exception:
        _stdlib_logger.exception("get_effective_score failed for topic=%s", topic)
        return fallback_score, "mastery_fallback"


def score_category_description(category: str) -> str:
    """Return a human-readable description of a score category for LLM prompts.

    Each description explains what the category means for question generation
    specifically, not merely what the score range is.

    Parameters
    ----------
    category :
        One of ``"very_weak"``, ``"weak"``, ``"moderate"``, ``"strong"``.

    Returns
    -------
    str
        Multi-sentence description suitable for prompt injection.
    """
    descriptions = {
        "very_weak": (
            "The student has very weak understanding of this topic (scored below 30%). "
            "Generate a simple definition or recall question to rebuild foundational "
            "knowledge.  The question must be answerable from the source text alone.  "
            "Distractors should be clearly distinguishable from the correct answer to "
            "build confidence rather than frustrate."
        ),
        "weak": (
            "The student has weak understanding of this topic (scored 30-50%).  "
            "Generate a question at the lowest cognitive level available within the "
            "mastery ceiling.  The student is still building fundamentals, so the "
            "question should reinforce basic knowledge with slightly plausible "
            "distractors that test whether the student confuses related concepts."
        ),
        "moderate": (
            "The student has moderate understanding of this topic (scored 50-75%).  "
            "Generate a question at the standard cognitive level for the student's "
            "mastery ceiling.  The student understands basics and is ready for "
            "questions that require application or comparison.  Distractors should "
            "match the expected difficulty level."
        ),
        "strong": (
            "The student has strong understanding of this topic (scored above 75%).  "
            "Generate a question at the highest cognitive level available within the "
            "mastery ceiling.  Push the student with reasoning, inference, or "
            "misconception questions.  Distractors should be subtle and require "
            "careful analysis to eliminate."
        ),
    }
    return descriptions.get(category, descriptions["moderate"])
