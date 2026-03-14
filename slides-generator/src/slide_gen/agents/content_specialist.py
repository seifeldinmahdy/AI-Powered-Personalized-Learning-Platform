"""
Content Specialist Agent — T5-Base wrapper.

Performs abstractive summarization of raw text into structured
slide content (title + bullets), conditioned on the student profile.
"""

from transformers import T5ForConditionalGeneration, T5Tokenizer


# Lazy-loaded model
_model = None
_tokenizer = None


def _load_model(model_path: str = "t5-base"):
    """Lazy-load T5 model and tokenizer."""
    global _model, _tokenizer
    if _model is None:
        _tokenizer = T5Tokenizer.from_pretrained(model_path, legacy=True)
        _model = T5ForConditionalGeneration.from_pretrained(model_path)
        _model.eval()
    return _model, _tokenizer


def format_input(chunk: str, profile_dict: dict) -> str:
    """
    Format input for the T5 model using the tag-based format.

    Args:
        chunk: Raw text chunk
        profile_dict: Dict with mastery_level, composition_mode, etc.

    Returns:
        Formatted input string
    """
    mastery = profile_dict.get("mastery_level", "Intermediate")
    mode = profile_dict.get("composition_mode", "Balanced")
    lang = profile_dict.get("language_proficiency", "Intermediate")

    return (
        f"[MASTERY: {mastery}] [MODE: {mode}] "
        f"[LANG: {lang}]\n"
        f"Context: {chunk}"
    )


def parse_output(text: str) -> dict:
    """
    Parse T5 plain-text output into structured data.

    Expected format:
        TITLE: Some Title Here
        BULLET: First bullet point
        BULLET: Second bullet point

    Returns:
        Dict with 'title' and 'bullets' list
    """
    title = "Untitled"
    bullets = []

    for line in text.strip().split("\n"):
        line = line.strip()
        if line.upper().startswith("TITLE:"):
            title = line[6:].strip()
        elif line.upper().startswith("BULLET:"):
            bullet_text = line[7:].strip()
            if bullet_text:
                bullets.append(bullet_text)

    # Fallback: if no structured output, treat the whole thing
    # as a single bullet point
    if not bullets and text.strip():
        bullets = [text.strip()]

    return {"title": title, "bullets": bullets}


def generate_content(
    chunk: str,
    profile_dict: dict,
    model_path: str = "t5-base",
    max_length: int = 256,
) -> dict:
    """
    Generate slide content from a text chunk and student profile.

    Args:
        chunk: Raw text chunk from the document
        profile_dict: Student profile as dict
        model_path: Path to fine-tuned T5 model (or base model name)
        max_length: Maximum output token length

    Returns:
        Dict with 'title' (str) and 'bullets' (list[str])
    """
    model, tokenizer = _load_model(model_path)

    input_text = format_input(chunk, profile_dict)
    inputs = tokenizer(
        input_text,
        return_tensors="pt",
        max_length=512,
        truncation=True,
    )

    outputs = model.generate(
        **inputs,
        max_length=max_length,
        num_beams=4,
        early_stopping=True,
        no_repeat_ngram_size=3,
    )

    decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)
    return parse_output(decoded)
