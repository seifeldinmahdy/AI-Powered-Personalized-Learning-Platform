"""Question type selector — chooses the question type for each chunk.

Applies the three-signal decision logic:
1. Global mastery level → hard ceiling from MASTERY_TYPE_ELIGIBILITY
2. Per-topic score category → force or bias from SCORE_CATEGORY_TYPE_OVERRIDE
3. Incorrectly answered history → escalation on repeated topic failures

Tier-0 pre-conditioning guards run first so the question type handed to QG is
always safe:
- Content gate: code types (1, 2, 3) are removed on prose-only chunks so the
  generator cannot hallucinate ungrounded code.
- Hard override: ``very_weak`` forces Type 4a regardless of the mastery ceiling.

No randomness — the selection is deterministic and fully explainable.
"""

from __future__ import annotations

import structlog

from mcq.question_types import (
    CODE_QUESTION_TYPES,
    CONCEPTUAL_QUESTION_TYPES,
    MASTERY_TYPE_ELIGIBILITY,
    SCORE_CATEGORY_TYPE_OVERRIDE,
    TYPE_COGNITIVE_LEVEL,
)
from mcq.scoring_categories import get_effective_score, get_score_category

logger = structlog.get_logger(__name__)


def select_question_type(
    chunk_text: str,
    chunk_topic: str,
    mastery_level: str,
    topic_performance: dict[str, float],
    incorrectly_answered: list[dict],
    embedder,
    settings,
    chunk_concept_id: str | None = None,
    concept_mastery: dict[str, float] | None = None,
) -> tuple[str, str, float]:
    """Select the best question type for a given chunk.

    Parameters
    ----------
    chunk_text :
        The raw text of the content chunk.
    chunk_topic :
        Topic tag associated with the chunk.
    mastery_level :
        Student's global mastery level.
    topic_performance :
        Student's per-topic score dict.
    incorrectly_answered :
        List of previously incorrectly answered question dicts.
    embedder :
        Sentence-transformer model for semantic topic matching.
    settings :
        MCQSettings instance.
    chunk_concept_id :
        The chunk's Concept id, when known. Enables resolving difficulty from
        concept mastery directly instead of fuzzy topic matching.
    concept_mastery :
        Authoritative ``concept_id → score`` (0–1) map for the student.

    Returns
    -------
    (question_type, score_category, topic_score)
        The selected type ID, the score category label, and the raw topic score.
    """
    # ── 1. Resolve score → category (concept mastery preferred) ─────
    topic_score, source = get_effective_score(
        chunk_topic, topic_performance, mastery_level, embedder, settings,
        concept_id=chunk_concept_id, concept_mastery=concept_mastery,
    )
    score_category = get_score_category(topic_score, settings)

    logger.debug(
        "selector_score_resolved",
        topic=chunk_topic,
        score=topic_score,
        source=source,
        category=score_category,
    )

    # ── 2. Get mastery ceiling ──────────────────────────────────────
    eligible = list(MASTERY_TYPE_ELIGIBILITY.get(mastery_level, ["4a"]))

    # ── 2b. Tier-0 content-eligibility gate ─────────────────────────
    # Code question types (1, 2, 3) require actual code in the chunk; on a
    # prose-only chunk the generator otherwise hallucinates code that isn't
    # grounded in the source. Strip them when the chunk has no code, always
    # keeping the conceptual types (answerable from any explanatory text).
    has_code = _chunk_has_code(chunk_text)
    if not has_code:
        gated = [t for t in eligible if t not in CODE_QUESTION_TYPES]
        if len(gated) != len(eligible):
            logger.debug(
                "selector_code_types_gated_out",
                topic=chunk_topic,
                removed=[t for t in eligible if t in CODE_QUESTION_TYPES],
            )
        eligible = gated or ["4a"]

    # ── 3. Apply score category override ────────────────────────────
    override = SCORE_CATEGORY_TYPE_OVERRIDE.get(score_category)
    if override is not None:
        # Force to the override list. The override (e.g. very_weak → 4a) is a
        # HARD rule that wins regardless of the mastery ceiling: 4a is the
        # universal floor, so a struggling Intermediate/Expert student still
        # gets a definition question even though 4a sits outside their ceiling.
        # Prefer an override type that is also content-eligible; fall back to
        # the override as written if the gate removed all of them.
        forced = [t for t in override if t in eligible] or list(override)
        if forced:
            selected = forced[0]
            logger.info(
                "selector_type_forced",
                topic=chunk_topic,
                category=score_category,
                forced_type=selected,
            )
            return selected, score_category, topic_score

    # ── 4. Bias by score category ───────────────────────────────────
    if score_category == "weak":
        # Prefer the lowest cognitive level within the ceiling
        eligible.sort(key=lambda t: TYPE_COGNITIVE_LEVEL.get(t, 99))
    elif score_category == "strong":
        # Prefer the highest cognitive level within the ceiling
        eligible.sort(key=lambda t: TYPE_COGNITIVE_LEVEL.get(t, 0), reverse=True)

    # ── 5. Check for escalation from incorrectly_answered ───────────
    topic_lower = chunk_topic.strip().lower() if chunk_topic else ""
    failed_types_on_topic: set[str] = set()
    for item in incorrectly_answered:
        item_topic = str(item.get("topic", "")).strip().lower()
        item_type = str(item.get("question_type", ""))
        if item_topic == topic_lower and item_type:
            failed_types_on_topic.add(item_type)

    if failed_types_on_topic:
        # Try to escalate: pick the next higher cognitive level type
        # that the student hasn't already failed on this topic
        failed_levels = {
            TYPE_COGNITIVE_LEVEL.get(t, 0) for t in failed_types_on_topic
        }
        max_failed_level = max(failed_levels) if failed_levels else 0

        escalation_candidates = [
            t for t in eligible
            if TYPE_COGNITIVE_LEVEL.get(t, 0) > max_failed_level
            and t not in failed_types_on_topic
        ]

        if escalation_candidates:
            escalation_candidates.sort(
                key=lambda t: TYPE_COGNITIVE_LEVEL.get(t, 99),
            )
            selected = escalation_candidates[0]
            logger.info(
                "selector_type_escalated",
                topic=chunk_topic,
                failed_types=list(failed_types_on_topic),
                escalated_to=selected,
            )
            return selected, score_category, topic_score

    # ── 6. Content-based hint ───────────────────────────────────────
    # ``has_code`` was resolved in step 2b (the content gate).
    if has_code:
        code_eligible = [t for t in eligible if t in CODE_QUESTION_TYPES]
        if code_eligible:
            selected = code_eligible[0]
            logger.debug(
                "selector_type_code_hint",
                topic=chunk_topic,
                selected=selected,
            )
            return selected, score_category, topic_score

    # ── 7. Default: first eligible type (already sorted by bias) ────
    selected = eligible[0] if eligible else "4a"
    logger.debug(
        "selector_type_default",
        topic=chunk_topic,
        selected=selected,
    )
    return selected, score_category, topic_score


def _chunk_has_code(text: str) -> bool:
    """Quick heuristic: does the chunk contain code-like patterns?"""
    if not text:
        return False
    code_signals = [
        "def ", "class ", "import ", "from ",
        "print(", "return ", "if __name__",
        ">>>", "```", "    #",
    ]
    text_lower = text.lower()
    return any(sig in text_lower for sig in code_signals)
