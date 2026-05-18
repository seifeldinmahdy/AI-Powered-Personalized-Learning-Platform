"""Per-slide mastery derivation and topic performance update utilities.

Provides independently testable functions for:

- Converting per-topic placement test scores into per-slide mastery
  levels (``derive_topic_mastery``, ``match_topic_to_performance``,
  ``smooth_mastery_sequence``).
- Updating topic performance scores after session assessments using
  a weighted moving average (``update_topic_performance_scores``).
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# ── 1. derive_topic_mastery ─────────────────────────────────────


def derive_topic_mastery(
    topic_score: Optional[float],
    global_mastery: str,
    *,
    expert_threshold: float = 0.75,
    intermediate_threshold: float = 0.45,
) -> str:
    """Convert a raw topic performance score into a mastery label.

    Parameters
    ----------
    topic_score :
        Per-topic score (0.0–1.0) from the student's placement test.
        ``None`` means no topic match was found → fall back to
        *global_mastery*.
    global_mastery :
        The student's global mastery level ("Novice" / "Intermediate" /
        "Expert") used as the fallback.
    expert_threshold :
        Score at or above which the student is labelled Expert.
    intermediate_threshold :
        Score at or above which (but below *expert_threshold*) the
        student is labelled Intermediate.

    Returns
    -------
    str
        "Expert", "Intermediate", or "Novice".
    """
    if topic_score is None:
        return global_mastery

    if topic_score >= expert_threshold:
        return "Expert"
    if topic_score >= intermediate_threshold:
        return "Intermediate"
    return "Novice"


# ── 2. match_topic_to_performance ───────────────────────────────


def match_topic_to_performance(
    chunk_topic: str,
    topic_performance: dict[str, float] | None,
    *,
    similarity_threshold: float = 0.75,
    _embedder=None,
) -> tuple[Optional[float], Optional[str]]:
    """Fuzzy-match a chunk's topic string to the student's performance dict.

    Uses the sentence-transformers embedder singleton already loaded by
    ``category_service._get_embedder()``.  If the embedder is not
    available, falls back gracefully.

    Parameters
    ----------
    chunk_topic :
        The topic tag attached to the chunk being processed.
    topic_performance :
        Student's ``topic_name → score`` dict from the placement test.
    similarity_threshold :
        Minimum cosine similarity to consider a match confident.
    _embedder :
        Override for testing — pass a mock embedder.  If *None*, the
        real singleton is loaded.

    Returns
    -------
    (score, matched_key)
        The matched performance score and the exact key from
        *topic_performance*, or ``(None, None)`` if no confident match.

    Notes
    -----
    This function **never** raises an exception.  Any failure is logged
    and ``(None, None)`` is returned.
    """
    try:
        if not chunk_topic or not chunk_topic.strip():
            return None, None

        if not topic_performance:
            return None, None

        perf_keys = list(topic_performance.keys())
        if not perf_keys:
            return None, None

        # Exact match (case-insensitive) — skip embedding entirely
        chunk_topic_lower = chunk_topic.strip().lower()
        for key in perf_keys:
            if key.strip().lower() == chunk_topic_lower:
                logger.debug(
                    "topic_match_exact: chunk_topic=%s matched_key=%s score=%.2f",
                    chunk_topic, key, topic_performance[key],
                )
                return topic_performance[key], key

        # Load embedder
        if _embedder is None:
            from services.category_service import _get_embedder  # type: ignore
            _embedder = _get_embedder()

        # Embed chunk topic and all performance keys together
        all_texts = [chunk_topic.strip()] + [k.strip() for k in perf_keys]
        embeddings = _embedder.encode(
            all_texts, convert_to_numpy=True, show_progress_bar=False,
        )

        # Cosine similarity between the chunk topic (index 0) and all keys
        from sklearn.metrics.pairwise import cosine_similarity as cos_sim
        sims = cos_sim([embeddings[0]], embeddings[1:])[0]

        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])
        best_key = perf_keys[best_idx]

        if best_sim >= similarity_threshold:
            logger.debug(
                "topic_match_semantic: chunk_topic=%s matched_key=%s sim=%.3f score=%.2f",
                chunk_topic, best_key, best_sim, topic_performance[best_key],
            )
            return topic_performance[best_key], best_key

        logger.debug(
            "topic_match_none: chunk_topic=%s best_key=%s best_sim=%.3f (below threshold %.2f)",
            chunk_topic, best_key, best_sim, similarity_threshold,
        )
        return None, None

    except Exception:
        logger.exception("topic_match_error: chunk_topic=%s", chunk_topic)
        return None, None


# ── 3. smooth_mastery_sequence ──────────────────────────────────

_TIER_MAP = {"Novice": 0, "Intermediate": 1, "Expert": 2}
_TIER_LABELS = ["Novice", "Intermediate", "Expert"]


def smooth_mastery_sequence(masteries: list[str]) -> list[str]:
    """Smooth jarring mastery transitions across consecutive slides.

    If two consecutive slides differ by more than one tier
    (e.g. Expert → Novice), the lower one is nudged up by one tier.
    Applied left-to-right in a single pass.

    Parameters
    ----------
    masteries :
        List of mastery strings, one per content slide.

    Returns
    -------
    list[str]
        Smoothed mastery list (same length).
    """
    if len(masteries) <= 1:
        return list(masteries)

    tiers = [_TIER_MAP.get(m, 1) for m in masteries]

    for i in range(1, len(tiers)):
        diff = abs(tiers[i] - tiers[i - 1])
        if diff > 1:
            original = tiers[i]
            # Nudge the current slide one tier toward the previous
            if tiers[i] < tiers[i - 1]:
                tiers[i] = tiers[i] + 1
            else:
                tiers[i] = tiers[i] - 1
            logger.debug(
                "mastery_smoothed: slide_idx=%d original=%s smoothed=%s",
                i, _TIER_LABELS[original], _TIER_LABELS[tiers[i]],
            )

    return [_TIER_LABELS[t] for t in tiers]


# ── 4. update_topic_performance_scores ──────────────────────────


# Thresholds mirroring assessments.py submit_placement logic:
#   strengths = [t for t, s in topic_performance.items() if s > 0.7]
#   weaknesses = [t for t, s in topic_performance.items() if s < 0.5]
_STRENGTH_THRESHOLD = 0.7
_WEAKNESS_THRESHOLD = 0.5


def update_topic_performance_scores(
    current_performance: dict[str, float],
    session_scores: dict[str, float],
    weight: float = 0.3,
) -> dict:
    """Update topic performance scores using a weighted moving average.

    For each topic in *session_scores*:

    - If it already exists in *current_performance*, apply::

          updated = (1 - weight) * current + weight * session_score

    - If it does not exist (new topic not in placement test), add it
      directly with the session score as the initial value.

    After updating scores, recompute strengths and weaknesses using the
    same thresholds as the placement-test scoring in ``assessments.py``:

    - Strengths: score > 0.7
    - Weaknesses: score < 0.5

    Parameters
    ----------
    current_performance :
        The student's existing ``topic → score`` dict.  **Not mutated.**
    session_scores :
        New ``topic → score`` dict from the session assessment.
    weight :
        Blending factor (0.0 = keep current, 1.0 = fully replace).

    Returns
    -------
    dict
        ``{"topic_performance": {…}, "strengths": [...], "weaknesses": [...]}``
    """
    # Deep copy — never mutate input
    updated = dict(current_performance)

    for topic, new_score in session_scores.items():
        if topic in updated:
            updated[topic] = round(
                (1 - weight) * updated[topic] + weight * new_score, 4,
            )
        else:
            updated[topic] = round(new_score, 4)

    strengths = sorted(t for t, s in updated.items() if s > _STRENGTH_THRESHOLD)
    weaknesses = sorted(t for t, s in updated.items() if s < _WEAKNESS_THRESHOLD)

    return {
        "topic_performance": updated,
        "strengths": strengths,
        "weaknesses": weaknesses,
    }
