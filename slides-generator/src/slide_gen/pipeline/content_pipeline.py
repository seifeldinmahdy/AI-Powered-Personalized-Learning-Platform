"""
Content Pipeline — Stage 3 of the presentation pipeline.

Orchestrates the 4 agents for each text chunk to produce a content slide:
1. Content Specialist (T5) → title + bullets
2. Visual Classifier (DistilBERT) → template_id + confidence
3. Visual Gate (rule-based) → render or skip
4. Code Extractor (deterministic) → code_block or null
5. Accessibility Worker (deterministic) → alt_text or null
"""

from slide_gen.agents.content_specialist import generate_content
from slide_gen.agents.visual_classifier import classify_visual, should_render_visual
from slide_gen.agents.code_extractor import extract_code
from slide_gen.agents.accessibility import generate_alt_text
from slide_gen.agents.visual_param_generator import generate_visual_params
from slide_gen.core.slide_schema import (
    CodeBlock,
    ContentItem,
    HighlightType,
    Layout,
    SlideInstruction,
    SlideType,
    VisualTemplate,
)
from slide_gen.core.profile_schema import StudentProfile


def _assign_highlight_types(bullets: list[str]) -> list[ContentItem]:
    """
    Assign highlight types to bullets using simple heuristics.

    In the fine-tuned model, we'd train for this. For now, use keywords.
    """
    items = []
    for bullet in bullets:
        lower = bullet.lower()

        if any(w in lower for w in ["defined as", "is a", "refers to", "means"]):
            ht = HighlightType.DEFINITION
        elif any(w in lower for w in ["for example", "such as", "e.g.", "like"]):
            ht = HighlightType.EXAMPLE
        elif any(w in lower for w in ["important", "key", "critical", "essential", "must"]):
            ht = HighlightType.KEY_CONCEPT
        elif any(w in lower for w in ["warning", "caution", "note", "careful"]):
            ht = HighlightType.ATTENTION
        else:
            ht = HighlightType.NONE

        items.append(ContentItem(text=bullet, highlight_type=ht))

    return items


def _choose_layout(
    has_visual: bool,
    has_code: bool,
    composition_mode: str,
) -> Layout:
    """
    Choose slide layout based on content and preference.
    """
    if has_code:
        return Layout.CODE_MAIN
    if has_visual:
        return Layout.CONTENT_VISUAL
    # Text-only → always List_View
    return Layout.LIST_VIEW


def process_chunk(
    chunk: str,
    profile: StudentProfile,
    t5_model_path: str = "t5-base",
    classifier_model_path: str = "distilbert-base-uncased",
) -> SlideInstruction:
    """
    Process a single text chunk through the compound AI pipeline.

    Args:
        chunk: Raw text chunk
        profile: Student profile for personalization
        t5_model_path: Path to fine-tuned T5 model
        classifier_model_path: Path to fine-tuned DistilBERT

    Returns:
        A complete SlideInstruction for this chunk
    """
    profile_dict = profile.to_prompt_dict()

    # ---- Agent 1: Content Specialist ----
    content = generate_content(chunk, profile_dict, model_path=t5_model_path)
    title = content["title"]
    bullets = content["bullets"]

    # ---- Agent 2: Visual Classifier (runs on raw chunk for richer signal) ----
    classification = classify_visual(chunk, model_path=classifier_model_path)

    # ---- Agent 3: Visual Gate ----
    visual_decision = should_render_visual(
        classification, profile.composition_mode.value
    )

    visual = None
    template_id = None
    visual_params = {}
    if visual_decision:
        template_id = visual_decision["template_id"]
        # LLM-based param generation (with deterministic fallback)
        visual_params = generate_visual_params(template_id, bullets, title)
        visual = VisualTemplate(template=template_id, params=visual_params)

    # ---- Agent 4: Code Extractor ----
    code_data = extract_code(chunk)
    code_block = None
    if code_data:
        code_block = CodeBlock(
            language=code_data["language"],
            code=code_data["code"],
        )

    # ---- Agent 5: Accessibility Worker ----
    alt_text = generate_alt_text(
        template_id=template_id,
        params=visual_params,
        slide_title=title,
        screen_reader_active=profile.screen_reader_active,
    )

    # ---- Assemble ----
    body_content = _assign_highlight_types(bullets)
    layout = _choose_layout(
        has_visual=visual is not None,
        has_code=code_block is not None,
        composition_mode=profile.composition_mode.value,
    )

    return SlideInstruction(
        slide_type=SlideType.CONTENT,
        layout=layout,
        title=title,
        body_content=body_content,
        visual=visual,
        code_block=code_block,
        alt_text=alt_text,
    )




def process_section_chunks(
    chunks: list[str],
    profile: StudentProfile,
    t5_model_path: str = "t5-base",
    classifier_model_path: str = "distilbert-base-uncased",
) -> list[SlideInstruction]:
    """
    Process all chunks in a section.

    Args:
        chunks: List of text chunks for this section
        profile: Student profile
        t5_model_path: Path to fine-tuned T5
        classifier_model_path: Path to fine-tuned DistilBERT

    Returns:
        List of content SlideInstructions
    """
    slides = []
    for i, chunk in enumerate(chunks):
        print(f"    Processing chunk {i+1}/{len(chunks)}...")
        slide = process_chunk(
            chunk, profile, t5_model_path, classifier_model_path
        )
        slides.append(slide)
    return slides
