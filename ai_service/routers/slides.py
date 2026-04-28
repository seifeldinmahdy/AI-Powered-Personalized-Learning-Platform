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
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
    mastery_level: str = "Novice"
    composition_mode: str = "visual_heavy"
    language_proficiency: str = "Elementary"
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


class VisualOut(BaseModel):
    template: str
    params: dict[str, Any] = Field(default_factory=dict)


class SlideOut(BaseModel):
    slide_number: int
    slide_type: str
    layout: str
    title: str
    body_content: list[ContentItemOut] = Field(default_factory=list)
    visual: Optional[VisualOut] = None
    code_block: Optional[CodeBlockOut] = None
    alt_text: Optional[str] = None
    source_chunk_id: str = ""
    source_topic: str = ""
    source_page_start: int = 0
    source_page_end: int = 0
    visual_type: str = ""


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
        from slide_gen.agents.content_specialist import _load_model
        _load_model(_T5_PATH)
        logger.info("slides_content_model_loaded: %s", _T5_PATH)
    except Exception as e:
        logger.warning("slides_content_model_load_failed: %s", str(e))

    try:
        from slide_gen.agents.visual_classifier import _load_level1
        _load_level1(_CLASSIFIER_PATH)
        logger.info("slides_classifier_model_loaded: %s", _CLASSIFIER_PATH)
    except Exception as e:
        logger.warning("slides_classifier_model_load_failed: %s", str(e))

    _models_loaded = True


# ── Core orchestration ──────────────────────────────────────────


def _clean_chunk_text(raw: str) -> str:
    """Clean raw chunk text: collapse whitespace, strip artifacts."""
    import re
    text = raw.strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\f", "", text)
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
    from slide_gen.agents.content_specialist import generate_content
    from slide_gen.agents.visual_classifier import classify_visual, should_render_visual
    from slide_gen.agents.code_extractor import extract_code
    from slide_gen.core.slide_schema import SlideType, Layout, HighlightType

    _ensure_models()

    profile_dict = {
        "mastery_level": request.mastery_level,
        "composition_mode": {
            "visual_heavy": "Visual_Heavy",
            "text_heavy": "Text_Heavy",
            "balanced": "Balanced",
        }.get(request.composition_mode, "Balanced"),
        "language_proficiency": request.language_proficiency,
    }

    composition_mode_display = profile_dict["composition_mode"]

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
        if tutor_context.get("current_topic"):
            parts.append(f"Tutor is currently covering: {tutor_context['current_topic']}")
        if tutor_context.get("current_slide_title"):
            parts.append(f"Current slide: {tutor_context['current_slide_title']}")
        if tutor_context.get("running_summary"):
            parts.append(
                f"Summary of what the tutor has explained so far:\n"
                f"{tutor_context['running_summary']}"
            )
        if parts:
            tutor_prefix = "\n".join(parts) + "\n\n"

    for chunk_in in request.chunks:
        cleaned = _clean_chunk_text(chunk_in.raw_text)
        if not cleaned or len(cleaned) < 20:
            continue

        # Inject tutor context into the chunk text so the content
        # specialist is aware of what has already been covered.
        enriched_text = tutor_prefix + cleaned if tutor_prefix else cleaned

        logger.info("slides_processing_chunk: chunk_id=%s topic=%s", chunk_in.chunk_id, chunk_in.topic)

        # 1. Content Specialist (T5)
        try:
            content = generate_content(enriched_text, profile_dict, model_path=_T5_PATH)
        except Exception as e:
            logger.error("content_specialist_failed: %s", str(e))
            content = {"title": "Untitled", "items": [{"text": cleaned[:200], "highlight_type": "none"}]}

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
                # Try param generation
                try:
                    from slide_gen.agents.visual_param_generator import generate_visual_params
                    bullet_texts = [it.get("text", "") for it in items]
                    params = generate_visual_params(visual_type, bullet_texts, title)
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

        # 4. Layout selection
        if code_out:
            layout = "Code_Main"
        elif visual_out:
            layout = "Content_Visual"
        else:
            layout = "List_View"

        slides.append(SlideOut(
            slide_number=slide_num,
            slide_type="Content",
            layout=layout,
            title=title,
            body_content=body,
            visual=visual_out,
            code_block=code_out,
            source_chunk_id=chunk_in.chunk_id,
            source_topic=chunk_in.topic,
            source_page_start=chunk_in.page_start,
            source_page_end=chunk_in.page_end,
            visual_type=visual_type,
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
