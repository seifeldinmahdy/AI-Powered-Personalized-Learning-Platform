"""
Summary Generator — Stage 4 of the presentation pipeline.

Uses Flan-T5-Small (77M params, pre-trained, NO fine-tuning) to generate
profile-aware section summaries from the content slides' key points.
"""

from transformers import T5ForConditionalGeneration, T5Tokenizer

from slide_gen.core.slide_schema import (
    ContentItem,
    HighlightType,
    Layout,
    SlideInstruction,
    SlideType,
)
from slide_gen.core.profile_schema import StudentProfile


# Lazy-loaded model (separate from the content specialist's T5)
_summary_model = None
_summary_tokenizer = None


def _load_summary_model():
    """Lazy-load Flan-T5-Small for summarization."""
    global _summary_model, _summary_tokenizer
    if _summary_model is None:
        model_name = "google/flan-t5-small"
        _summary_tokenizer = T5Tokenizer.from_pretrained(model_name, legacy=True)
        _summary_model = T5ForConditionalGeneration.from_pretrained(model_name)
        _summary_model.eval()
    return _summary_model, _summary_tokenizer


def _collect_key_points(slides: list[SlideInstruction]) -> list[str]:
    """
    Collect key points from content slides for summarization.

    Prioritizes key_concept and definition highlight types,
    falls back to all bullets if those are sparse.
    """
    priority_points = []
    all_points = []

    for slide in slides:
        for item in slide.body_content:
            all_points.append(item.text)
            if item.highlight_type in (
                HighlightType.KEY_CONCEPT,
                HighlightType.DEFINITION,
            ):
                priority_points.append(item.text)

    # Use priority points if we have enough, otherwise all
    if len(priority_points) >= 3:
        return priority_points
    return all_points


def _build_prompt(
    key_points: list[str],
    section_title: str,
    profile: StudentProfile,
) -> str:
    """
    Build an instruction prompt for Flan-T5-Small.

    The prompt includes student context so the summary is personalized.
    """
    mastery = profile.mastery_level.value
    lang = profile.language_proficiency.value

    # Adjust style instructions based on profile
    style_hints = {
        "Novice": "Use simple language and explain each point clearly.",
        "Intermediate": "Be concise but include important details.",
        "Expert": "Be brief and technical, assume strong background knowledge.",
    }
    style = style_hints.get(mastery, "Be concise.")

    lang_hints = {
        "Elementary": " Use very simple words and short sentences.",
        "Intermediate": "",
        "Advanced": "",
        "Native": "",
    }
    lang_note = lang_hints.get(lang, "")

    points_str = "\n".join(f"- {p}" for p in key_points[:10])  # Cap at 10

    return (
        f"Summarize the following key concepts from the section "
        f"'{section_title}' for a {mastery.lower()}-level student. "
        f"{style}{lang_note}\n\n"
        f"Key points covered:\n{points_str}\n\n"
        f"Write 3-4 concise summary bullet points:"
    )


def _parse_summary_output(text: str) -> list[str]:
    """
    Parse Flan-T5 output into individual bullet points.
    """
    bullets = []

    for line in text.strip().split("\n"):
        line = line.strip()
        # Remove common bullet prefixes
        for prefix in ["- ", "• ", "* ", "1. ", "2. ", "3. ", "4. ", "5. "]:
            if line.startswith(prefix):
                line = line[len(prefix):]
                break

        if line and len(line) > 5:
            bullets.append(line)

    # If no line breaks, try splitting by period
    if not bullets and text.strip():
        sentences = [s.strip() for s in text.split(".") if s.strip()]
        bullets = sentences[:4]

    return bullets[:4]  # Cap at 4 bullets


def generate_summary_slide(
    section_slides: list[SlideInstruction],
    section_title: str,
    profile: StudentProfile,
) -> SlideInstruction:
    """
    Generate a summary slide for a section.

    Uses Flan-T5-Small with the student profile context to create
    a personalized summary of the section's key points.

    Args:
        section_slides: All content slides from this section
        section_title: Title of the section being summarized
        profile: Student profile for personalization

    Returns:
        Summary SlideInstruction
    """
    model, tokenizer = _load_summary_model()

    # Collect key points from the content slides
    key_points = _collect_key_points(section_slides)

    if not key_points:
        return SlideInstruction(
            slide_type=SlideType.SUMMARY,
            layout=Layout.LIST_VIEW,
            title=f"Key Takeaways: {section_title}",
            body_content=[
                ContentItem(
                    text="No key points to summarize.",
                    highlight_type=HighlightType.NONE,
                )
            ],
        )

    # Build prompt with student context
    prompt = _build_prompt(key_points, section_title, profile)

    # Generate summary
    inputs = tokenizer(
        prompt,
        return_tensors="pt",
        max_length=512,
        truncation=True,
    )

    outputs = model.generate(
        **inputs,
        max_length=200,
        num_beams=4,
        early_stopping=True,
        no_repeat_ngram_size=3,
    )

    decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)
    summary_bullets = _parse_summary_output(decoded)

    # Build the summary slide
    body_content = [
        ContentItem(text=bullet, highlight_type=HighlightType.KEY_CONCEPT)
        for bullet in summary_bullets
    ]

    # Fallback: if model output was unhelpful, use extractive approach
    if not body_content:
        body_content = [
            ContentItem(text=p, highlight_type=HighlightType.KEY_CONCEPT)
            for p in key_points[:4]
        ]

    return SlideInstruction(
        slide_type=SlideType.SUMMARY,
        layout=Layout.LIST_VIEW,
        title=f"Key Takeaways: {section_title}",
        body_content=body_content,
    )
