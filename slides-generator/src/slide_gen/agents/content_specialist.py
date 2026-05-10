"""
Content Specialist Agent — Fine-tuned Flan-T5-Large wrapper.

Performs abstractive summarization of raw text into structured
slide content (title + bullets + definitions), conditioned on the student profile
via tag-based conditioning: [MASTERY: X] [MODE: Y] [LANG: Z].

Output format trained on:
    TITLE: ...
    DEFINE [term]: description
    BULLET [key_concept]: ...
    BULLET [example]: ...
    BULLET [attention]: ...
"""

import os
import re
from pathlib import Path
import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

# Auto-detect device: prefer CUDA, fallback to MPS, then CPU
_device = torch.device("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")

# Resolve absolute path to local model folder
CURRENT_DIR = Path(__file__).parent
PROJECT_ROOT = CURRENT_DIR.parent.parent.parent
DEFAULT_MODEL_PATH = str(PROJECT_ROOT / "models" / "content_specialist")

# Lazy-loaded model
_model = None
_tokenizer = None


def _load_model(model_path: str = DEFAULT_MODEL_PATH):
    """Lazy-load T5 model and tokenizer from local directory."""
    global _model, _tokenizer
    if _model is None:
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"Model path {model_path} doesn't exist. "
                "Add your downloaded model files here."
            )

        _tokenizer = AutoTokenizer.from_pretrained(model_path, legacy=False)
        _model = AutoModelForSeq2SeqLM.from_pretrained(model_path)
        _model.to(_device)
        _model.eval()
        print(f"🚀 Content Specialist loaded on: {_device}")
    return _model, _tokenizer


def format_input(chunk: str, profile_dict: dict) -> str:
    """
    Format input for the T5 model using the tag-based format.

    Args:
        chunk: Raw text chunk
        profile_dict: Dict with mastery_level, composition_mode, etc.

    Returns:
        Formatted input string matching training format
    """
    mastery = profile_dict.get("mastery_level", "Intermediate")
    mode = profile_dict.get("composition_mode", "Balanced")
    lang = profile_dict.get("language_proficiency", "Intermediate")

    return (
        f"[MASTERY: {mastery}] [MODE: {mode}] "
        f"[LANG: {lang}]\n"
        f"Context: {chunk}"
    )


# Tag patterns for parsing (matches training data format)
_TITLE_RE = re.compile(r"^TITLE:\s*(.+)", re.IGNORECASE)
_DEFINE_RE = re.compile(r"^DEFINE\s*\[([^\]]+)\]:\s*(.+)", re.IGNORECASE)
_BULLET_RE = re.compile(r"^BULLET\s*\[([^\]]+)\]:\s*(.+)", re.IGNORECASE)

# Map tag names to HighlightType values
_TAG_TO_HIGHLIGHT = {
    "key_concept": "key_concept",
    "example": "example",
    "attention": "attention",
    "code": "code",
}


def parse_output(text: str) -> dict:
    """
    Parse T5 output into structured data.

    Handles the full trained output format:
        TITLE: Some Title Here
        DEFINE [term]: description of the term
        BULLET [key_concept]: First bullet point
        BULLET [example]: An example
        BULLET [attention]: A warning

    Returns:
        Dict with:
        - 'title' (str)
        - 'items' (list[dict]) — each has 'text', 'highlight_type',
          and optionally 'term' for definitions
    """
    title = "Untitled"
    items = []
    found_any_tag = False  # Track if we've seen at least one structured tag

    # T5 might generate tags inline (separated by spaces instead of newlines)
    # Insert newlines before any known tags to ensure proper splitting
    text = re.sub(r"(?<!^)(\bTITLE:|\bDEFINE \[|\bBULLET \[|\bDEFINE:|\bBULLET:)", r"\n\1", text, flags=re.IGNORECASE)

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        # Try TITLE
        m = _TITLE_RE.match(line)
        if m:
            title = m.group(1).strip()
            found_any_tag = True
            continue

        # Try DEFINE [term]: description
        m = _DEFINE_RE.match(line)
        if m:
            term = m.group(1).strip()
            description = m.group(2).strip()
            items.append({
                "text": description,
                "highlight_type": "definition",
                "term": term,
            })
            found_any_tag = True
            continue

        # Try BULLET [tag]: text
        m = _BULLET_RE.match(line)
        if m:
            tag = m.group(1).strip().lower()
            bullet_text = m.group(2).strip()
            highlight = _TAG_TO_HIGHLIGHT.get(tag, "none")
            items.append({
                "text": bullet_text,
                "highlight_type": highlight,
                "term": None,
            })
            found_any_tag = True
            continue

        # Fallback: plain BULLET: or TITLE: (old format compat)
        if line.upper().startswith("BULLET:"):
            bullet_text = line[7:].strip()
            if bullet_text:
                items.append({
                    "text": bullet_text,
                    "highlight_type": "none",
                    "term": None,
                })
                found_any_tag = True
            continue

        # If we've already seen structured tags, discard any unmatched
        # lines — they are raw source text that leaked from the model.
        # Only keep untagged lines if NO tags have been found yet.

    # Ultimate fallback: if no structured output was found at all,
    # treat the whole text as a single bullet.
    if not found_any_tag and not items and text.strip():
        items.append({
            "text": text.strip(),
            "highlight_type": "none",
            "term": None,
        })

    return {"title": title, "items": items}


def generate_content(
    chunk: str,
    profile_dict: dict,
    model_path: str = DEFAULT_MODEL_PATH,
    max_length: int = 256,
) -> dict:
    """
    Generate slide content from a text chunk and student profile.

    Args:
        chunk: Raw text chunk from the document
        profile_dict: Student profile as dict
        model_path: Path to fine-tuned T5 model
        max_length: Maximum output token length

    Returns:
        Dict with 'title' (str) and 'items' (list[dict])
        Each item has 'text', 'highlight_type', and optionally 'term'
    """
    model, tokenizer = _load_model(model_path)

    input_text = format_input(chunk, profile_dict)
    inputs = tokenizer(
        input_text,
        return_tensors="pt",
        max_length=512,
        truncation=True,
    )
    # Move inputs to same device as model
    inputs = {k: v.to(_device) for k, v in inputs.items()}
    try:
        outputs = _model.generate(
            **inputs,
            max_length=150,
            num_beams=4,
            early_stopping=True,
            no_repeat_ngram_size=3,
        )
        text = _tokenizer.decode(outputs[0], skip_special_tokens=True)
        print("====== RAW T5 GENERATED TEXT ======")
        print(repr(text))
        print("===================================")
        return parse_output(text)
    except Exception as e:
        raise e
