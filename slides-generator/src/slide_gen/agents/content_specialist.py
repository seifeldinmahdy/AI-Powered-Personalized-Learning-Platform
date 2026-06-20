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


# Highlight types a BULLET tag may carry (the bracket content for a bullet)
_BULLET_HIGHLIGHTS = {"key_concept", "example", "attention", "code"}

# Canonical tag words the model is trained to emit.
_TAG_CANON = {"TITLE": "title", "DEFINE": "define", "BULLET": "bullet"}

# A tag line / inline tag: a leading word, an optional [bracket], then a colon.
# Deliberately loose on the word so we can fuzzy-repair beam-search corruptions
# (BUFLET, BONUS, DEFOrm, BINE, EFINE, ULLET, …) in _classify_tag_word.
_TAG_RE = re.compile(r"^([A-Za-z]{3,})\s*(?:\[([^\]]*)\])?\s*:\s*(.*)$")
_TAG_SPLIT_RE = re.compile(r"([A-Za-z]{3,})\s*(?:\[([^\]]{0,40})\])?\s*:")


def _classify_tag_word(word: str, bracket: str | None) -> str | None:
    """Map a possibly-garbled tag word to 'title' / 'define' / 'bullet'.

    The fine-tuned T5 sometimes emits a tag with a wrong sub-token from beam
    search — e.g. ``DEFINE``→``DEFOrm``/``BINE``, ``BULLET``→``BUFLET``/
    ``BONUS``. We recover intent from (1) distinctive prefixes, (2) a known
    highlight bracket, and (3) fuzzy similarity. Returns None when it is not a
    tag (so ordinary prose like ``Note:`` is left alone).
    """
    import difflib

    w = "".join(c for c in word.upper() if c.isalpha())
    if len(w) < 3:
        return None

    # (1) Distinctive 3-letter prefixes — strongest, cheapest signal.
    if w.startswith("TIT"):
        return "title"
    if w.startswith("DEF"):     # DEFINE, DEFOrm, …
        return "define"
    if w.startswith("BUL"):     # BULLET, BULLLET, …
        return "bullet"

    # (2) A recognized highlight bracket means it is a BULLET regardless of the
    #     (garbled) word — catches "BONUS [example]:", "BUFLET [example]:".
    if bracket and bracket.strip().lower() in _BULLET_HIGHLIGHTS:
        return "bullet"

    # (3) Fuzzy match against the canonical tag words (catches BINE→DEFINE etc.)
    best, score = None, 0.0
    for cand, kind in _TAG_CANON.items():
        r = difflib.SequenceMatcher(None, w, cand).ratio()
        if r > score:
            best, score = kind, r
    return best if score >= 0.6 else None


def _append_tag_item(kind: str, bracket: str | None, body: str, items: list) -> None:
    """Turn a classified tag + its text into a structured item."""
    body = body.strip()
    bracket_l = (bracket or "").strip().lower()

    if kind == "define":
        # DEFINE [term]: description. A garbled DEFINE with no usable term
        # (e.g. "DEFOrm: ...") still keeps its text — as a key_concept bullet
        # so it is never silently merged into the previous bullet or lost.
        if bracket and bracket.strip():
            items.append({"text": body, "highlight_type": "definition", "term": bracket.strip()})
        elif body:
            items.append({"text": body, "highlight_type": "key_concept", "term": None})
        return

    # bullet
    highlight = bracket_l if bracket_l in _BULLET_HIGHLIGHTS else "none"
    if body:
        items.append({"text": body, "highlight_type": highlight, "term": None})


def parse_output(text: str) -> dict:
    """
    Parse T5 output into structured data, tolerant of garbled tags.

    Handles the trained output format and its beam-search corruptions:
        TITLE: Some Title Here
        DEFINE [term]: description of the term
        BULLET [key_concept]: First bullet point
        BULLET [example]: An example
        BUFLET [example]: ...   ← repaired to a BULLET (example)
        DEFOrm: ...             ← repaired to a DEFINE-style item

    Returns:
        Dict with:
        - 'title' (str)
        - 'items' (list[dict]) — each has 'text', 'highlight_type',
          and optionally 'term' for definitions
    """
    title = "Untitled"
    items: list[dict] = []
    found_any_tag = False

    # The model often runs tags together on one line. Insert a newline before any
    # token that classifies as a real tag so each becomes its own item. (A bare
    # prose "word:" is left untouched because _classify_tag_word returns None.)
    def _split_repl(m: "re.Match") -> str:
        if _classify_tag_word(m.group(1), m.group(2)) is None:
            return m.group(0)
        return "\n" + m.group(0)

    text = _TAG_SPLIT_RE.sub(_split_repl, text)

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        m = _TAG_RE.match(line)
        kind = _classify_tag_word(m.group(1), m.group(2)) if m else None

        if kind == "title":
            title = m.group(3).strip() or title
            found_any_tag = True
            continue
        if kind in ("define", "bullet"):
            _append_tag_item(kind, m.group(2), m.group(3), items)
            found_any_tag = True
            continue

        # Untagged line: keep it only if we haven't locked into structured mode
        # yet (otherwise it is leaked source text). Mirrors prior behavior.
        if not found_any_tag:
            items.append({"text": line, "highlight_type": "none", "term": None})

    # Ultimate fallback: nothing structured at all → whole text as one bullet.
    if not found_any_tag and not items and text.strip():
        items.append({"text": text.strip(), "highlight_type": "none", "term": None})

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
