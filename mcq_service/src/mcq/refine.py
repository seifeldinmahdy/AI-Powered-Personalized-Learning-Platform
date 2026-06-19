"""In-session MCQ refinement — make served MCQs reliable and personalized.

A post-generation pass applied to every MCQ before it reaches the student. It
fixes the failure modes the evaluation surfaced (paraphrase-of-answer
distractors that create two-correct items, generic fallback padding, near-
duplicate distractors, leaked prefixes/option-labels, source-text echo) WITHOUT
retraining either model.

Three tiers, cheapest first:

  Tier 1 — rule/regex cleanup (deterministic, ~0 ms)
      Strip leaked prefixes ("DISTRACTOR:", "Wrong answer:", option labels),
      source-reference phrases, and a verbatim chunk sentence echoed into the
      stem. Normalise whitespace.

  Tier 2 — embedding cleanup (deterministic, ~ms; reuses the loaded embedder)
      Drop distractors that are paraphrases of the correct answer (two-correct
      bug), near-duplicates of each other (low diversity), implausible, or
      generic fallbacks.

  Tier 3 — NVIDIA NIM (nemotron) judge + repair (1 LLM call, only when needed)
      When the deterministic tiers leave fewer than the required number of
      distractors, or validation is requested, ask nemotron to (a) confirm the
      answer is correct and exactly one option is right, and (b) supply
      replacement distractors — distinct, plausible, wrong, each targeting a
      different misconception (one targeting ``misconception_context`` when
      given). Runs against NVIDIA NIM, never Ollama.

``refine_mcq`` is the single entry point. It never raises: on any internal
failure it returns the original MCQ so generation degrades gracefully.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

import structlog

from mcq.models import MCQOption, MCQQuestion
from mcq.nvidia_client import get_refine_client

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG / CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

_GENERIC_FALLBACKS = {
    "none of the above",
    "all of the above",
    "not defined in this context",
    "none of these",
    "all of these",
    "no correct answer",
}

# Leading noise that leaks from training data into model output.
_PREFIX_RE = re.compile(
    r"^\s*(?:DISTRACTOR|ANSWER|CORRECT ANSWER|WRONG ANSWER|OPTION|CHOICE)\s*[:\-]\s*",
    re.IGNORECASE,
)
# A leading option label: "A) ", "B. ", "(C) ", "d) ".
_OPTION_LABEL_RE = re.compile(r"^\s*[\(\[]?\s*[A-Da-d]\s*[\)\].:]\s+")
# Source-reference phrases that make a question un-answerable out of context.
_SOURCE_REF_RE = re.compile(
    r"\b(?:according to|as (?:stated|shown|mentioned|described) in|based on|"
    r"in|from)\s+the\s+(?:passage|text|chunk|excerpt|paragraph|above|snippet)\b"
    r"|\bthe (?:passage|text|chunk|excerpt|paragraph) (?:above|states|says)\b",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class _Signals:
    question_type: str
    mastery: str
    score_category: str
    misconception_context: str | None


# ═══════════════════════════════════════════════════════════════════════════════
# TIER 1 — RULE / REGEX CLEANUP
# ═══════════════════════════════════════════════════════════════════════════════

def _strip_wrappers(text: str) -> str:
    """Remove symmetric surrounding quotes / markdown emphasis and collapse WS."""
    t = text.strip()
    # Strip matched wrapping quotes or asterisks, possibly repeated.
    for _ in range(3):
        if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'`*":
            t = t[1:-1].strip()
        else:
            break
    return _WS_RE.sub(" ", t).strip()


def _clean_fragment(text: str) -> str:
    """Tier-1 cleanup for an answer or a distractor (a short fragment)."""
    if not text:
        return ""
    t = _PREFIX_RE.sub("", text.strip())
    t = _OPTION_LABEL_RE.sub("", t)
    t = _strip_wrappers(t)
    return t


def _clean_question(question: str, chunk_text: str) -> str:
    """Tier-1 cleanup for the question stem.

    Removes source-reference phrases and a leading sentence that is copied
    verbatim from the chunk (the model sometimes prepends the chunk's own
    definition before the actual question).
    """
    if not question:
        return ""
    q = _strip_wrappers(question)

    # Drop a leading sentence that is echoed verbatim from the chunk, as long as
    # a real question remains after it.
    sentences = _SENT_SPLIT_RE.split(q)
    if len(sentences) > 1 and chunk_text:
        chunk_norm = _WS_RE.sub(" ", chunk_text).lower()
        while len(sentences) > 1:
            head = sentences[0].strip()
            tail = " ".join(sentences[1:]).strip()
            # Only strip if the head is a declarative echo and the tail still
            # contains the actual question (a '?' or an interrogative opener).
            # Normalise the head (drop trailing terminal punctuation) so a
            # sentence echoed from the chunk still matches as a substring.
            head_norm = _WS_RE.sub(" ", head.rstrip(".!?").strip()).lower()
            head_is_echo = len(head_norm) > 25 and head_norm in chunk_norm
            tail_has_question = "?" in tail or bool(
                re.match(r"^(which|what|why|how|when|where|complete|select|"
                         r"identify|choose)\b", tail, re.IGNORECASE)
            )
            if head_is_echo and tail_has_question:
                sentences = sentences[1:]
            else:
                break
        q = " ".join(sentences).strip()

    q = _SOURCE_REF_RE.sub("", q).strip()
    q = _WS_RE.sub(" ", q).strip()
    # Tidy punctuation artifacts left by the phrase removals: a terminal mark
    # followed by a stray comma ("behavior. , which" -> "behavior. which"),
    # doubled commas, and spaces before punctuation.
    q = re.sub(r"([.!?])\s*,\s*", r"\1 ", q)
    q = re.sub(r",\s*,", ", ", q)
    q = re.sub(r"\s+([,.;:?!])", r"\1", q)
    q = re.sub(r"^[\s,;:\-]+", "", q)        # leading punctuation
    q = _WS_RE.sub(" ", q).strip()
    # Re-capitalise if the stem now starts lower-case after a strip.
    if q and q[0].islower():
        q = q[0].upper() + q[1:]
    return q


# ═══════════════════════════════════════════════════════════════════════════════
# TIER 2 — EMBEDDING CLEANUP
# ═══════════════════════════════════════════════════════════════════════════════

def _is_prose(text: str) -> bool:
    """True for natural-language answers; False for short symbolic/code answers.

    The plausibility floor only makes sense on prose — short answers like
    ``O(1)``, ``.pop()`` or ``[2, 3, 1]`` are legitimately symbol-heavy and
    embed poorly, so they must not be dropped for "low similarity".
    """
    if len(text) < 25:
        return False
    letters = sum(c.isalpha() or c.isspace() for c in text)
    return (letters / max(len(text), 1)) >= 0.75


def _cos_matrix(embedder, texts: list[str]):
    import numpy as np
    embs = embedder.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    norms = np.linalg.norm(embs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = embs / norms
    return unit @ unit.T


def _filter_distractors(
    correct: str,
    distractors: list[str],
    embedder,
    *,
    answer_dup: float,
    diversity: float,
    plausibility_floor: float,
) -> tuple[list[str], list[float]]:
    """Drop answer-paraphrases, near-duplicates, implausible & generic distractors.

    Returns (kept_distractors, similarity_to_answer_for_each_kept).
    """
    # Exact + generic removal first (no embedding needed).
    correct_norm = correct.strip().lower()
    pre: list[str] = []
    for d in distractors:
        dn = d.strip().lower()
        if not dn or dn == correct_norm or dn in _GENERIC_FALLBACKS:
            continue
        if any(dn == p.strip().lower() for p in pre):  # exact dup
            continue
        pre.append(d.strip())

    if not pre or embedder is None:
        return pre, [0.0] * len(pre)

    # One embedding matrix over [correct, *distractors].
    sim = _cos_matrix(embedder, [correct] + pre)
    answer_sims = sim[0, 1:]
    prose_answer = _is_prose(correct)

    # Greedy keep: skip paraphrase-of-answer, implausible, and near-duplicates.
    kept_idx: list[int] = []
    for i in range(len(pre)):
        a_sim = float(answer_sims[i])
        if a_sim >= answer_dup:
            logger.debug("refine_drop_answer_paraphrase", sim=round(a_sim, 3),
                         distractor=pre[i][:60])
            continue
        if prose_answer and _is_prose(pre[i]) and a_sim < plausibility_floor:
            logger.debug("refine_drop_implausible", sim=round(a_sim, 3),
                         distractor=pre[i][:60])
            continue
        # Diversity vs already-kept distractors.
        too_similar = any(
            float(sim[i + 1, j + 1]) >= diversity for j in kept_idx
        )
        if too_similar:
            logger.debug("refine_drop_low_diversity", distractor=pre[i][:60])
            continue
        kept_idx.append(i)

    kept = [pre[i] for i in kept_idx]
    kept_sims = [float(answer_sims[i]) for i in kept_idx]
    return kept, kept_sims


# ═══════════════════════════════════════════════════════════════════════════════
# TIER 3 — NVIDIA NIM (NEMOTRON) JUDGE + REPAIR
# ═══════════════════════════════════════════════════════════════════════════════

_REPAIR_SYSTEM = (
    "You are a meticulous computer-science assessment editor. You repair "
    "multiple-choice questions so that exactly one option is correct and the "
    "wrong options (distractors) are plausible but unambiguously incorrect. "
    "You reply with ONLY a JSON object, no prose, no markdown."
)


def _build_repair_prompt(
    question: str,
    correct: str,
    kept_distractors: list[str],
    needed: int,
    chunk_text: str,
    sig: _Signals,
) -> list[dict[str, str]]:
    n_new = max(0, needed - len(kept_distractors))
    misc = ""
    if sig.misconception_context:
        misc = (
            "\nThe student previously showed this misconception — make at least "
            f"one distractor appeal to it: \"{sig.misconception_context}\""
        )
    existing = "\n".join(f"- {d}" for d in kept_distractors) or "(none yet)"
    user = (
        f"QUESTION:\n{question}\n\n"
        f"CORRECT ANSWER:\n{correct}\n\n"
        f"SOURCE CONTENT (for grounding):\n\"\"\"\n{chunk_text[:1200]}\n\"\"\"\n\n"
        f"STUDENT PROFILE: mastery={sig.mastery}, difficulty={sig.score_category}, "
        f"question_type={sig.question_type}\n\n"
        f"EXISTING GOOD DISTRACTORS (keep, do not duplicate):\n{existing}\n"
        f"{misc}\n\n"
        "TASKS:\n"
        "1. Judge the item. Set \"answer_ok\" false ONLY if the CORRECT ANSWER is "
        "factually wrong or not answerable from general CS knowledge of the "
        "concept; otherwise true. If false, put a corrected answer in "
        "\"fixed_answer\" (else \"\").\n"
        f"2. Provide exactly {n_new} NEW distractor(s) that are factually WRONG, "
        "clearly distinct from the correct answer and from each other and from "
        "the existing distractors, plausible to a student with partial "
        "understanding, and matched to the student profile. Each should target a "
        "DIFFERENT misconception.\n\n"
        "Reply with this exact JSON shape:\n"
        '{"answer_ok": true, "fixed_answer": "", "new_distractors": ["...", "..."]}'
    )
    return [
        {"role": "system", "content": _REPAIR_SYSTEM},
        {"role": "user", "content": user},
    ]


def _llm_repair(
    question: str,
    correct: str,
    kept: list[str],
    needed: int,
    chunk_text: str,
    sig: _Signals,
    embedder,
    settings,
    *,
    answer_dup: float,
    diversity: float,
    plausibility_floor: float,
) -> tuple[str, list[str]]:
    """Run the nemotron judge+repair. Returns (correct_answer, distractors).

    Fails open: on any error returns the inputs unchanged.
    """
    client = get_refine_client(settings)
    if client is None:
        return correct, kept
    try:
        data = client.chat_json(
            _build_repair_prompt(question, correct, kept, needed, chunk_text, sig),
            temperature=0.4,
            timeout_override=60,
        )
    except Exception as exc:
        logger.warning("refine_llm_repair_failed", error=str(exc)[:160])
        return correct, kept

    # Honor a corrected answer only when the judge is confident it was wrong.
    new_correct = correct
    if data.get("answer_ok") is False:
        fixed = str(data.get("fixed_answer", "")).strip()
        if fixed:
            new_correct = _clean_fragment(fixed)
            logger.info("refine_answer_corrected", original=correct[:60],
                        fixed=new_correct[:60])

    raw_new = data.get("new_distractors", [])
    new_clean = [
        _clean_fragment(str(d)) for d in raw_new if str(d).strip()
    ] if isinstance(raw_new, list) else []

    # Merge existing kept + new, then re-run Tier-2 filtering over the union so
    # the LLM's additions are held to the same dedup/diversity bar.
    merged, _ = _filter_distractors(
        new_correct, kept + new_clean, embedder,
        answer_dup=answer_dup, diversity=diversity,
        plausibility_floor=plausibility_floor,
    )
    return new_correct, merged


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def refine_mcq(
    mcq: MCQQuestion,
    chunk_text: str,
    embedder,
    settings,
    *,
    misconception_context: str | None = None,
) -> MCQQuestion:
    """Refine a generated MCQ in place of serving the raw model output.

    Always returns a valid 4-option MCQ. Never raises — on internal failure the
    original ``mcq`` is returned unchanged.
    """
    if not getattr(settings, "MCQ_REFINE_ENABLED", True):
        return mcq

    try:
        needed = settings.MCQ_DISTRACTOR_COUNT
        answer_dup = settings.MCQ_REFINE_ANSWER_DUP_THRESHOLD
        diversity = settings.MCQ_REFINE_DIVERSITY_THRESHOLD
        plausibility_floor = settings.MCQ_REFINE_PLAUSIBILITY_FLOOR
        use_llm = getattr(settings, "MCQ_REFINE_USE_LLM", False)

        sig = _Signals(
            question_type=mcq.question_type,
            mastery=mcq.mastery_used,
            score_category=mcq.score_category_used,
            misconception_context=misconception_context,
        )

        # ── Tier 1 — rule/regex cleanup ──────────────────────────────────
        correct = _clean_fragment(mcq.correct_answer)
        question = _clean_question(mcq.question, chunk_text)
        raw_distractors = [
            _clean_fragment(o.text) for o in mcq.options if not o.is_correct
        ]

        if not correct or not question:
            # Cleanup nuked a required field — keep the original item.
            logger.warning("refine_abort_empty_field", topic=mcq.topic)
            return mcq

        # ── Tier 2 — embedding cleanup ───────────────────────────────────
        kept, _sims = _filter_distractors(
            correct, raw_distractors, embedder,
            answer_dup=answer_dup, diversity=diversity,
            plausibility_floor=plausibility_floor,
        )

        # ── Tier 3 — NVIDIA judge + repair (only when needed) ────────────
        if use_llm and len(kept) < needed:
            correct, kept = _llm_repair(
                question, correct, kept, needed, chunk_text, sig, embedder, settings,
                answer_dup=answer_dup, diversity=diversity,
                plausibility_floor=plausibility_floor,
            )

        # ── Last-resort padding (only if still short) ────────────────────
        used_fallback = False
        if len(kept) < needed:
            for fb in ("None of the above", "All of the above",
                       "Not defined in this context"):
                if len(kept) >= needed:
                    break
                if fb.lower() != correct.strip().lower() and fb not in kept:
                    kept.append(fb)
                    used_fallback = True
            if used_fallback:
                logger.warning("refine_fallback_padding_used",
                               topic=mcq.topic, got=len(kept))

        distractors = kept[:needed]
        if len(distractors) < needed:
            # Could not reach a full item even with padding — return original.
            logger.warning("refine_insufficient_options", topic=mcq.topic,
                           got=len(distractors))
            return mcq

        # ── Reassemble + reshuffle ───────────────────────────────────────
        scores = _cos_to_answer(correct, distractors, embedder)
        options = [MCQOption(text=correct, is_correct=True)]
        options.extend(MCQOption(text=d, is_correct=False) for d in distractors)
        random.shuffle(options)

        return MCQQuestion(
            question=question,
            options=options,
            correct_answer=correct,
            explanation=mcq.explanation,
            question_type=mcq.question_type,
            topic=mcq.topic,
            concept_id=mcq.concept_id,
            mastery_used=mcq.mastery_used,
            score_category_used=mcq.score_category_used,
            distractor_scores=scores,
            generation_mode=mcq.generation_mode + "+refined",
        )

    except Exception as exc:
        logger.warning("refine_failed_returning_original",
                       topic=getattr(mcq, "topic", "?"), error=str(exc)[:160])
        return mcq


def _cos_to_answer(correct: str, distractors: list[str], embedder) -> list[float] | None:
    if embedder is None or not distractors:
        return None
    try:
        sim = _cos_matrix(embedder, [correct] + distractors)
        return [round(float(sim[0, i + 1]), 4) for i in range(len(distractors))]
    except Exception:
        return None
