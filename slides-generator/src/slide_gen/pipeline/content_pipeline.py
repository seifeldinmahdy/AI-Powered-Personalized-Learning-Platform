"""
Content Pipeline — Stage 3 of the presentation pipeline.

Orchestrates the agents for each text chunk to produce a content slide:
1. Content Specialist (Flan-T5-Large) → title + structured items
2. Visual Classifier (DistilBERT) → template_id + confidence
3. Visual Gate (rule-based) → render or skip
4. Code Extractor (deterministic) → code_block or null
5. Accessibility Worker (deterministic) → alt_text
"""

from pathlib import Path

from slide_gen.agents.content_specialist import generate_content
from slide_gen.agents.visual_classifier import classify_visual, should_render_visual
from slide_gen.agents.code_extractor import extract_code
from slide_gen.agents.accessibility import generate_alt_text
from slide_gen.agents.visual_param_generator import generate_visual_params
from slide_gen.agents.judge import judge_template, judge_params
from slide_gen.agents.math_extractor import extract_math
from slide_gen.core.slide_schema import (
    CodeBlock,
    ContentItem,
    EquationItem,
    HighlightType,
    Layout,
    SlideInstruction,
    SlideType,
    VisualTemplate,
)
from slide_gen.core.profile_schema import StudentProfile

# Resolve local model paths
_PIPELINE_DIR = Path(__file__).parent
_PROJECT_ROOT = _PIPELINE_DIR.parent.parent.parent
DEFAULT_T5_PATH = str(_PROJECT_ROOT / "models" / "content_specialist")
DEFAULT_CLASSIFIER_PATH = str(_PROJECT_ROOT / "models" / "visual_classifier")


def _highlight_from_string(ht_str: str) -> HighlightType:
    """Convert a highlight type string to the enum value."""
    mapping = {
        "none": HighlightType.NONE,
        "definition": HighlightType.DEFINITION,
        "example": HighlightType.EXAMPLE,
        "key_concept": HighlightType.KEY_CONCEPT,
        "attention": HighlightType.ATTENTION,
        "code": HighlightType.CODE,
    }
    return mapping.get(ht_str, HighlightType.NONE)


def _items_to_content(items: list[dict]) -> list[ContentItem]:
    """
    Convert the structured items from Content Specialist into ContentItem objects.

    Each item dict has: text, highlight_type, and optionally term.
    """
    content_items = []
    for item in items:
        content_items.append(ContentItem(
            text=item["text"],
            highlight_type=_highlight_from_string(item.get("highlight_type", "none")),
            term=item.get("term"),
        ))
    return content_items


def _assign_highlight_types_heuristic(bullets: list[str]) -> list[ContentItem]:
    """
    Fallback: assign highlight types using simple heuristics.
    Used when the model returns plain text without tags.
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
    has_math: bool,
    composition_mode: str,
) -> Layout:
    """
    Choose slide layout based on content and preference.

    Priority (highest → lowest):
      1. Code present                → Code_Main
      2. Math + visual present       → Equation_Visual
      3. Math only (no visual)       → Equation_Focus  (text first, equations below)
      4. Visual only (no math)       → Content_Visual
      5. Text only                   → List_View
    """
    if has_code:
        return Layout.CODE_MAIN
    if has_math and has_visual:
        return Layout.EQUATION_VISUAL
    if has_math:
        return Layout.EQUATION_FOCUS
    if has_visual:
        return Layout.CONTENT_VISUAL
    return Layout.LIST_VIEW


def process_chunk(
    chunk: str,
    profile: StudentProfile,
    t5_model_path: str = DEFAULT_T5_PATH,
    classifier_model_path: str = DEFAULT_CLASSIFIER_PATH,
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
    items = content["items"]

    # Convert structured items to ContentItem objects
    body_content = _items_to_content(items)

    # ---- Agent 2: Visual Classifier (runs on raw chunk for richer signal) ----
    classification = classify_visual(chunk, model_path=classifier_model_path)
    bullet_texts = [item["text"] for item in items]

    # ---- Agent 2.5: Inference Visual Judge — arbitrate the template ----
    # The trained classifier (core contribution) proposes a top-3 shortlist; the
    # fast judge LLM picks the final template and can correct a wrong top-1.
    # Falls back to the classifier's own ranking if the judge is disabled/fails.
    candidates = [
        {"template_id": c["template_id"], "confidence": c["confidence"]}
        for c in classification.get("top_3", [])
    ]
    judged = judge_template(
        chunk, bullet_texts, title, [c["template_id"] for c in candidates]
    )
    if judged:
        jid = judged["template_id"]
        rest = [c for c in candidates if c["template_id"] != jid]
        candidates = [{"template_id": jid, "confidence": judged["confidence"]}] + rest

    # ---- Agent 3: Visual Gate & Fallback Generation ----
    visual = None
    template_id = None
    visual_params = {}

    # Try the (judge-reordered) candidates in order
    for candidate in candidates:
        candidate_classification = {
            "template_id": candidate["template_id"],
            "confidence": candidate["confidence"],
            "category": classification.get("category", "none"),
        }

        visual_decision = should_render_visual(
            candidate_classification, profile.composition_mode.value
        )

        if visual_decision is not None:
            attempted_template_id = visual_decision["template_id"]
            attempted_confidence = visual_decision.get("confidence", 1.0)

            # Generate visual params (with deterministic fallback)
            attempted_params = generate_visual_params(
                attempted_template_id, bullet_texts, title,
                classifier_confidence=attempted_confidence,
                raw_chunk=chunk,
            )

            if attempted_params is not None:
                # ---- Agent 3.5: Params faithfulness — regenerate once if unfaithful ----
                verdict = judge_params(
                    attempted_template_id, attempted_params, bullet_texts, title
                )
                if not verdict.get("faithful", True):
                    retry_params = generate_visual_params(
                        attempted_template_id, bullet_texts, title,
                        classifier_confidence=attempted_confidence,
                        raw_chunk=chunk,
                    )
                    if retry_params is not None:
                        attempted_params = retry_params  # accept the regen regardless

                template_id = attempted_template_id
                visual_params = attempted_params
                visual = VisualTemplate(template=template_id, params=visual_params)
                break

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

    # ---- Agent 6: Math Extractor (runs on raw chunk, parallel-safe) ----
    equation_block = None
    try:
        equation_block = extract_math(chunk)
    except Exception:
        equation_block = None

    # ---- Layout Selection (Component 4) ----
    has_math = equation_block is not None and len(equation_block) > 0
    layout = _choose_layout(
        has_visual=visual is not None,
        has_code=code_block is not None,
        has_math=has_math,
        composition_mode=profile.composition_mode.value,
    )

    return SlideInstruction(
        slide_type=SlideType.CONTENT,
        layout=layout,
        title=title,
        body_content=body_content,
        visual=visual,
        code_block=code_block,
        equation_block=equation_block,
        alt_text=alt_text,
    )


def process_section_chunks(
    chunks: list[str],
    profile: StudentProfile,
    t5_model_path: str = DEFAULT_T5_PATH,
    classifier_model_path: str = DEFAULT_CLASSIFIER_PATH,
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
