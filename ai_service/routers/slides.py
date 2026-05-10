"""Slide Orchestrator Router — generates a full slide deck for a session.

Takes session chunks from the pathway generator and runs them through
the compound AI pipeline: content specialist + visual classifier +
code extractor + structural slides + summary slide.

When a ``session_id`` is provided, tutor context (current topic,
running summary, slide title) is auto-read from SharedSessionStore
and injected into the content specialist prompt so regenerated slides
reflect what the tutor has already covered.

Endpoints
---------
POST /slides/generate  — Generate slides for a single session
GET  /slides/health     — Health check
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from schemas.student_context import UnifiedStudentContext

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/slides", tags=["Slides"])

# ── Resolve paths ───────────────────────────────────────────────

_AI_SERVICE_DIR = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _AI_SERVICE_DIR.parent
_SLIDES_SRC = str(_PROJECT_ROOT / "slides-generator" / "src")
_SLIDES_PROJECT = str(_PROJECT_ROOT / "slides-generator")

if _SLIDES_SRC not in sys.path:
    sys.path.insert(0, _SLIDES_SRC)

_T5_PATH = str(_PROJECT_ROOT / "slides-generator" / "models" / "content_specialist")
_CLASSIFIER_PATH = str(_PROJECT_ROOT / "slides-generator" / "models" / "visual_classifier")


# ── Request / Response schemas ──────────────────────────────────


class SessionChunkIn(BaseModel):
    chunk_id: str = ""
    raw_text: str
    topic: str = ""
    page_start: int = 0
    page_end: int = 0


class SlideGenerateRequest(BaseModel):
    session_number: int
    session_title: str
    topics_covered: list[str] = Field(default_factory=list)
    book: str = ""
    chunks: list[SessionChunkIn]
    # Deprecated: use student_context instead. Kept for backward compatibility.
    mastery_level: str | None = "Novice"
    composition_mode: str | None = "visual_heavy"
    language_proficiency: str | None = "Elementary"
    student_context: Optional[UnifiedStudentContext] = None
    session_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional session ID.  When provided, tutor context (topic, "
            "summary, slide title) is auto-read from SharedSessionStore "
            "and injected into the content specialist prompt."
        ),
    )


class ContentItemOut(BaseModel):
    text: str
    highlight_type: str = "none"
    term: Optional[str] = None


class CodeBlockOut(BaseModel):
    language: str
    code: str


class EquationItemOut(BaseModel):
    latex: str
    label: str
    display: bool = True


class VisualOut(BaseModel):
    template: str
    params: dict[str, Any] = Field(default_factory=dict)


class SlideMasteryMetadata(BaseModel):
    """Per-slide mastery provenance — tracks how mastery was derived."""
    mastery_used: Literal["Novice", "Intermediate", "Expert"]
    global_mastery: Literal["Novice", "Intermediate", "Expert"]
    topic_score: float | None = None
    topic_matched: str | None = None
    mastery_source: Literal["topic_performance", "global_fallback"]


class SlideOut(BaseModel):
    slide_number: int
    slide_type: str
    layout: str
    title: str
    body_content: list[ContentItemOut] = Field(default_factory=list)
    visual: Optional[VisualOut] = None
    code_block: Optional[CodeBlockOut] = None
    equation_block: Optional[list[EquationItemOut]] = None
    alt_text: Optional[str] = None
    source_chunk_id: str = ""
    source_topic: str = ""
    source_page_start: int = 0
    source_page_end: int = 0
    visual_type: str = ""
    mastery_metadata: Optional[SlideMasteryMetadata] = None


class SlideGenerateResponse(BaseModel):
    session_number: int
    session_title: str
    total_slides: int
    slides: list[SlideOut]
    generation_time_seconds: float


# ── Lazy model loading ──────────────────────────────────────────

_models_loaded = False


def _ensure_models():
    """Warm up the content specialist and visual classifier models."""
    global _models_loaded
    if _models_loaded:
        return

    try:
        from slide_gen.agents.content_specialist import _load_model  # type: ignore
        _load_model(_T5_PATH)
        logger.info("slides_content_model_loaded: %s", _T5_PATH)
    except Exception as e:
        logger.warning("slides_content_model_load_failed: %s", str(e))

    try:
        from slide_gen.agents.visual_classifier import _load_level1  # type: ignore
        _load_level1(_CLASSIFIER_PATH)
        logger.info("slides_classifier_model_loaded: %s", _CLASSIFIER_PATH)
    except Exception as e:
        logger.warning("slides_classifier_model_load_failed: %s", str(e))

    _models_loaded = True


# ── Core orchestration ──────────────────────────────────────────


def _clean_chunk_text(raw: str) -> str:
    """Clean raw chunk text: collapse whitespace, strip artifacts.

    Returns lightly-cleaned text that RETAINS Unicode math symbols.
    Used by the math extractor and visual classifier.
    """
    import re
    text = raw.strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\f", "", text)
    return text


# Unicode Math/Symbol/Greek → ASCII for T5 input normalization.
# Prevents the content specialist from learning/reproducing raw math notation
# in bullet text (the math extractor handles rendering separately via KaTeX).
_UNICODE_SYMBOL_MAP = {
    # Arrows
    "\u2192": "->", "\u2190": "<-", "\u2191": "^", "\u2193": "v",
    "\u21D2": "=>", "\u2194": "<->",
    # Math operators
    "\u2212": "-", "\u00D7": "x", "\u00F7": "/",
    "\u2211": "sum", "\u221A": "sqrt",
    "\u2264": "<=", "\u2265": ">=", "\u2248": "~=",
    "\u226B": ">>", "\u226A": "<<",
    "\u2208": "in", "\u2209": "not in",
    "\u00B1": "+/-", "\u2225": "||", "\u2217": "*",
    "\u2032": "'", "\u00B7": ".", "\u00AF": "-",
    "\u2044": "/", "\u2026": "...",
    # Modifiers / combining
    "\u02C6": "^", "\u0302": "", "\u0304": "",
    "\u00B5": "u", "\u2113": "l", "\u00DF": "ss",
    "\u00B0": " degrees",
    # Superscripts → ^N
    "\u00B2": "^2", "\u00B3": "^3", "\u00B9": "^1",
    "\u207F": "^n", "\u207B": "^-", "\u207A": "^+",
    "\u2070": "^0", "\u2074": "^4", "\u2075": "^5",
    "\u2076": "^6", "\u2077": "^7", "\u2078": "^8", "\u2079": "^9",
    # Subscripts → _N
    "\u2080": "_0", "\u2081": "_1", "\u2082": "_2", "\u2083": "_3",
    "\u2084": "_4", "\u2085": "_5", "\u2086": "_6", "\u2087": "_7",
    "\u2088": "_8", "\u2089": "_9",
    # Greek → spelled out
    "\u03B1": "alpha", "\u03B2": "beta", "\u03B3": "gamma",
    "\u03B4": "delta", "\u03B5": "epsilon", "\u03F5": "epsilon",
    "\u03B6": "zeta", "\u03B7": "eta", "\u03B8": "theta",
    "\u03B9": "iota", "\u03BA": "kappa", "\u03BB": "lambda",
    "\u03BC": "mu", "\u03BD": "nu", "\u03BE": "xi",
    "\u03C0": "pi", "\u03C1": "rho", "\u03C3": "sigma",
    "\u03C4": "tau", "\u03C5": "upsilon", "\u03C6": "phi",
    "\u03C7": "chi", "\u03C8": "psi", "\u03C9": "omega",
    "\u0393": "Gamma", "\u0394": "Delta", "\u0398": "Theta",
    "\u039B": "Lambda", "\u03A0": "Pi", "\u03A3": "Sigma",
    "\u03A6": "Phi", "\u03A8": "Psi", "\u03A9": "Omega",
    # Accented Latin / formatting
    "\u0177": "y", "\u00EF": "i", "\u202F": " ",
    # OCR ligatures
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl",
    "\ufb03": "ffi", "\ufb04": "ffl",
    "\u2011": "-", "\u00a0": " ",
    "\u2019": "'", "\u2018": "'",
    "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-",
}


def _normalize_for_t5(text: str) -> str:
    """Normalize Unicode math/symbols to ASCII for T5 input.

    The content specialist must receive text where Greek letters and math
    operators are spelled out so it learns to produce prose explanations
    rather than raw Unicode formulas (which would duplicate the math
    extractor's KaTeX output).
    """
    for sym, repl in _UNICODE_SYMBOL_MAP.items():
        if sym in text:
            text = text.replace(sym, repl)
    return text



def _generate_session_slides(
    request: SlideGenerateRequest,
    tutor_context: Optional[dict] = None,
) -> list[SlideOut]:
    """Run the full orchestrator pipeline for one session.

    Parameters
    ----------
    request : SlideGenerateRequest
        The incoming API request.
    tutor_context : dict or None
        If provided, a dict from SharedSessionStore with keys like
        ``current_topic``, ``running_summary``, ``current_slide_title``.
        Injected into the content specialist prompt so regenerated slides
        reflect what the tutor has already covered.
    """
    from slide_gen.agents.content_specialist import generate_content  # type: ignore
    from slide_gen.agents.visual_classifier import classify_visual, should_render_visual  # type: ignore
    from slide_gen.agents.code_extractor import extract_code  # type: ignore
    from slide_gen.core.slide_schema import SlideType, Layout, HighlightType  # type: ignore

    _ensure_models()

    if request.student_context:
        if not request.student_context.profile.is_fully_hydrated():
            logger.warning("slides: Received UnifiedStudentContext but profile is NOT fully hydrated. Using defaults.")
        profile_dict = request.student_context.to_slides_prompt_dict()
    else:
        # Legacy path — keep working for internal callers
        profile_dict = {
            "mastery_level": request.mastery_level or "Novice",
            "composition_mode": {
                "visual_heavy": "Visual_Heavy",
                "text_heavy": "Text_Heavy",
                "balanced": "Balanced",
            }.get(request.composition_mode or "visual_heavy", "Balanced"),
            "language_proficiency": request.language_proficiency or "Elementary",
        }

    composition_mode_display = profile_dict.get("composition_mode", "Balanced")

    slides: list[SlideOut] = []
    slide_num = 1

    # ── Slide 1: Title Slide ────────────────────────────────────
    slides.append(SlideOut(
        slide_number=slide_num,
        slide_type="Title",
        layout="Content_Visual",
        title=request.session_title,
        body_content=[
            ContentItemOut(text=f"Session {request.session_number}", highlight_type="none"),
            ContentItemOut(text=f"Topics: {', '.join(request.topics_covered)}", highlight_type="none"),
            ContentItemOut(text=f"Source: {request.book}", highlight_type="none") if request.book else ContentItemOut(text="", highlight_type="none"),
        ],
    ))
    slide_num += 1

    # ── Slide 2: Agenda Slide ───────────────────────────────────
    agenda_items = [
        ContentItemOut(text=topic, highlight_type="none")
        for topic in request.topics_covered
    ]
    slides.append(SlideOut(
        slide_number=slide_num,
        slide_type="Agenda",
        layout="List_View",
        title="What We'll Cover",
        body_content=agenda_items,
    ))
    slide_num += 1

    # ── Slides 3..N-1: Content Slides ───────────────────────────
    all_titles = []
    all_bullets = []

    # ── Build tutor-context prefix for the content specialist ───
    tutor_prefix = ""
    if tutor_context:
        parts = []
        if tutor_context.live.current_topic:
            parts.append(f"Tutor is currently covering: {tutor_context.live.current_topic}")
        if tutor_context.live.current_slide_title:
            parts.append(f"Current slide: {tutor_context.live.current_slide_title}")
        if tutor_context.live.running_summary:
            parts.append(
                f"Summary of what the tutor has explained so far:\n"
                f"{tutor_context.live.running_summary}"
            )
        if parts:
            tutor_prefix = "\n".join(parts) + "\n\n"

    # ── Per-slide mastery derivation ────────────────────────────
    # Pre-filter valid chunks and pre-compute per-chunk mastery
    # so smooth_mastery_sequence can operate on the full list.

    from services.topic_mastery import (
        derive_topic_mastery,
        match_topic_to_performance,
        smooth_mastery_sequence,
    )

    global_mastery = profile_dict.get("mastery_level", "Novice")

    # Retrieve topic_performance from student context (if available)
    topic_performance: dict[str, float] | None = None
    if request.student_context and request.student_context.profile.topic_performance:
        topic_performance = request.student_context.profile.topic_performance

    # Load thresholds from settings (if accessible), else use defaults
    expert_thresh = 0.75
    intermediate_thresh = 0.45
    match_thresh = 0.75
    try:
        _pathway_src = str(_PROJECT_ROOT / "course_pathway" / "src")
        if _pathway_src not in sys.path:
            sys.path.insert(0, _pathway_src)
        from pathway.config import get_settings as _get_pathway_settings  # type: ignore
        _pw_settings = _get_pathway_settings()
        expert_thresh = _pw_settings.topic_mastery_expert_threshold
        intermediate_thresh = _pw_settings.topic_mastery_intermediate_threshold
        match_thresh = _pw_settings.topic_match_threshold
    except Exception:
        pass  # Use defaults — non-critical

    # Filter valid chunks first (same filter as the old loop)
    valid_chunks = []
    for chunk_in in request.chunks:
        cleaned = _clean_chunk_text(chunk_in.raw_text)
        if cleaned and len(cleaned) >= 20:
            valid_chunks.append((chunk_in, cleaned))

    # Match topics and derive raw masteries for all valid chunks
    raw_masteries: list[str] = []
    match_results: list[tuple[float | None, str | None]] = []

    for chunk_in, _ in valid_chunks:
        score, matched_key = match_topic_to_performance(
            chunk_in.topic, topic_performance, similarity_threshold=match_thresh,
        )
        mastery = derive_topic_mastery(
            score, global_mastery,
            expert_threshold=expert_thresh,
            intermediate_threshold=intermediate_thresh,
        )
        raw_masteries.append(mastery)
        match_results.append((score, matched_key))

    # Smooth jarring transitions across the full sequence
    smoothed_masteries = smooth_mastery_sequence(raw_masteries)

    # Log session-level mastery derivation summary
    topic_matched_count = sum(1 for s, _ in match_results if s is not None)
    logger.info(
        "slides_mastery_derivation: global=%s total_chunks=%d topic_matched=%d global_fallback=%d",
        global_mastery, len(valid_chunks), topic_matched_count,
        len(valid_chunks) - topic_matched_count,
    )

    # ── Process each valid chunk ────────────────────────────────
    for i, (chunk_in, cleaned) in enumerate(valid_chunks):
        slide_mastery = smoothed_masteries[i]
        topic_score, topic_matched = match_results[i]

        # Build per-chunk profile dict with the derived mastery
        chunk_profile_dict = dict(profile_dict)
        chunk_profile_dict["mastery_level"] = slide_mastery

        # T5 gets Unicode-normalized text (Greek→spelled, math→ASCII)
        # so it produces prose bullets, not raw formulas.
        # Math extractor and visual classifier keep the original Unicode.
        cleaned_for_t5 = _normalize_for_t5(cleaned)

        # Inject tutor context into the chunk text so the content
        # specialist is aware of what has already been covered.
        enriched_text = tutor_prefix + cleaned_for_t5 if tutor_prefix else cleaned_for_t5

        mastery_source = "topic_performance" if topic_score is not None else "global_fallback"
        logger.info(
            "slides_processing_chunk: chunk_id=%s topic=%s matched_key=%s "
            "topic_score=%s mastery=%s (source=%s)",
            chunk_in.chunk_id, chunk_in.topic, topic_matched,
            f"{topic_score:.2f}" if topic_score is not None else "N/A",
            slide_mastery, mastery_source,
        )

        # 1. Content Specialist (T5) — receives normalized text with per-chunk mastery
        try:
            content = generate_content(enriched_text, chunk_profile_dict, model_path=_T5_PATH)
        except Exception as e:
            logger.error("content_specialist_failed: %s", str(e))
            content = {"title": "Untitled", "items": [{"text": cleaned_for_t5[:200], "highlight_type": "none"}]}

        title = content.get("title", "Untitled")
        items = content.get("items", [])
        all_titles.append(title)

        body = [
            ContentItemOut(
                text=it.get("text", ""),
                highlight_type=it.get("highlight_type", "none"),
                term=it.get("term"),
            )
            for it in items
        ]
        all_bullets.extend([it.get("text", "") for it in items])

        # 2. Visual Classifier
        visual_out = None
        visual_type = ""
        try:
            classification = classify_visual(cleaned, model_path=_CLASSIFIER_PATH)
            visual_decision = should_render_visual(classification, composition_mode_display)
            if visual_decision:
                visual_type = visual_decision["template_id"]
                visual_confidence = visual_decision.get("confidence", 1.0)
                # Try param generation
                try:
                    from slide_gen.agents.visual_param_generator import generate_visual_params  # type: ignore
                    bullet_texts = [it.get("text", "") for it in items]
                    params = generate_visual_params(
                        visual_type, bullet_texts, title,
                        classifier_confidence=visual_confidence,
                        raw_chunk=cleaned,
                    )
                    if params:
                        visual_out = VisualOut(template=visual_type, params=params)
                except Exception:
                    visual_out = VisualOut(template=visual_type, params={})
        except Exception as e:
            logger.warning("visual_classifier_failed: %s", str(e))

        # 3. Code Extractor
        code_out = None
        try:
            code_data = extract_code(cleaned)
            if code_data:
                code_out = CodeBlockOut(
                    language=code_data["language"],
                    code=code_data["code"],
                )
        except Exception as e:
            logger.warning("code_extractor_failed: %s", str(e))

        # 4. Math Extractor
        equation_block_out = None
        try:
            from slide_gen.agents.math_extractor import extract_math  # type: ignore
            equations = extract_math(cleaned)
            if equations:
                equation_block_out = [
                    EquationItemOut(
                        latex=eq.latex,
                        label=eq.label,
                        display=eq.display,
                    )
                    for eq in equations
                ]
        except Exception as e:
            logger.warning("math_extractor_failed: %s", str(e))

        # 5. Layout selection
        if code_out:
            layout = "Code_Main"
        elif visual_out:
            layout = "Content_Visual"
        else:
            layout = "List_View"

        # 6. Build mastery metadata
        mastery_meta = SlideMasteryMetadata(
            mastery_used=slide_mastery,
            global_mastery=global_mastery,
            topic_score=topic_score,
            topic_matched=topic_matched,
            mastery_source=mastery_source,
        )

        slides.append(SlideOut(
            slide_number=slide_num,
            slide_type="Content",
            layout=layout,
            title=title,
            body_content=body,
            visual=visual_out,
            code_block=code_out,
            equation_block=equation_block_out,
            source_chunk_id=chunk_in.chunk_id,
            source_topic=chunk_in.topic,
            source_page_start=chunk_in.page_start,
            source_page_end=chunk_in.page_end,
            visual_type=visual_type,
            mastery_metadata=mastery_meta,
        ))
        slide_num += 1


    # ── Slide N: Summary Slide ──────────────────────────────────
    summary_bullets = []
    if all_titles:
        for t in all_titles[:5]:
            if t and t != "Untitled":
                summary_bullets.append(ContentItemOut(text=t, highlight_type="key_concept"))

    if all_bullets:
        for b in all_bullets[:5]:
            if b and len(b) > 10:
                summary_bullets.append(ContentItemOut(text=b, highlight_type="key_concept"))

    # Deduplicate
    seen_texts: set[str] = set()
    deduped_summary: list[ContentItemOut] = []
    for item in summary_bullets:
        if item.text not in seen_texts:
            seen_texts.add(item.text)
            deduped_summary.append(item)
        if len(deduped_summary) >= 5:
            break

    if not deduped_summary:
        deduped_summary = [ContentItemOut(text="Session complete.", highlight_type="none")]

    slides.append(SlideOut(
        slide_number=slide_num,
        slide_type="Summary",
        layout="List_View",
        title=f"Key Takeaways: {request.session_title}",
        body_content=deduped_summary,
    ))

    return slides


# ── Endpoints ───────────────────────────────────────────────────


@router.post("/generate", response_model=SlideGenerateResponse)
async def generate_slides(request: SlideGenerateRequest):
    """Generate a full slide deck for a session from its chunks.

    When ``session_id`` is provided, tutor context is read from
    SharedSessionStore and injected into the content specialist prompt.
    """
    # --- DEBUG / TESTING OVERRIDE: Return saved deck if it exists for this session ---
    import os
    import json
    if os.path.exists("latest_deck.json"):
        try:
            with open("latest_deck.json", "r", encoding="utf-8") as f:
                saved_deck = json.load(f)
            if saved_deck.get("session_number") == request.session_number:
                logger.info("TESTING OVERRIDE: Returning latest_deck.json instantly to save generation time.")
                return SlideGenerateResponse(**saved_deck)
        except Exception as e:
            logger.warning(f"Could not load saved deck override: {e}")
    # ---------------------------------------------------------------------------------

    t0 = time.time()

    logger.info(
        "slides_generation_start: session=%d title=%s chunks=%d",
        request.session_number, request.session_title, len(request.chunks),
    )

    # ── Read tutor context from SharedSessionStore ──────────────
    tutor_context = None
    if request.session_id:
        try:
            from services.session_store import get_session_store
            store = get_session_store()
            tutor_context = store.get_session(request.session_id)
            if tutor_context:
                logger.info(
                    "slides: loaded tutor context from SharedSessionStore for session %s",
                    request.session_id,
                )
        except Exception as exc:
            logger.warning("slides: failed to read SharedSessionStore: %s", exc)

    try:
        slides = _generate_session_slides(request, tutor_context=tutor_context)
    except Exception as e:
        logger.error("slides_generation_failed: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Slide generation failed: {e}")

    elapsed = round(time.time() - t0, 2)

    logger.info(
        "slides_generation_complete: session=%d total_slides=%d elapsed=%.2fs",
        request.session_number, len(slides), elapsed,
    )

    response = SlideGenerateResponse(
        session_number=request.session_number,
        session_title=request.session_title,
        total_slides=len(slides),
        slides=slides,
        generation_time_seconds=elapsed,
    )

    # Save a debug copy to the ai_service root
    try:
        import json
        with open("latest_deck.json", "w", encoding="utf-8") as f:
            f.write(response.model_dump_json(indent=2))
        logger.info("Saved raw output to latest_deck.json")
    except Exception as e:
        logger.warning(f"Could not save latest_deck.json: {e}")

    return response


@router.get("/health")
async def slides_health():
    """Check if slide generation models are loadable."""
    status_info: dict[str, Any] = {"status": "healthy"}
    try:
        _ensure_models()
        status_info["content_model"] = "loaded"
        status_info["classifier_model"] = "loaded"
    except Exception as e:
        status_info["status"] = "unhealthy"
        status_info["error"] = str(e)
    return status_info
