"""Text sanitation shared by the generators.

Deterministic emoji removal: prompts ask the model to avoid emojis, but this is
the GUARANTEE — generated lab/problem-set content is stripped before it is
validated and saved as an artifact, so no emoji can ever reach a student.

The ranges target emoji / pictographs / dingbats / symbol blocks and the emoji
modifiers (variation selectors, ZWJ, regional indicators). They deliberately do
NOT include the arrow (U+2190–U+21FF) or math-operator blocks, so legitimate
characters like "->", "<=", ">=" in explanations and code are preserved.
"""

from __future__ import annotations

import re

_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"   # symbols & pictographs, emoticons, transport, supplemental, ext-A
    "\U0001F000-\U0001F0FF"   # mahjong / dominoes / playing cards
    "\U00002600-\U000026FF"   # miscellaneous symbols (☀ ⚠ ★ ☑ …)
    "\U00002700-\U000027BF"   # dingbats (✅ ✔ ✂ …)
    "\U00002B00-\U00002BFF"   # misc symbols & arrows (⭐ ⬛ …)
    "\U0001F1E6-\U0001F1FF"   # regional indicators (flags)
    "\U0000FE00-\U0000FE0F"   # variation selectors
    "\U0000200D"              # zero-width joiner
    "\U000020E3"              # combining enclosing keycap
    "\U00002B50\U00002B55"    # star / heavy circle
    "]+",
    flags=re.UNICODE,
)


def strip_emojis(text: str) -> str:
    """Remove emoji/pictographic characters from a string and tidy whitespace."""
    if not isinstance(text, str) or not text:
        return text
    cleaned = _EMOJI_RE.sub("", text)
    if cleaned == text:
        return text
    # Collapse intra-line double spaces a removed emoji may have left behind,
    # and drop now-trailing spaces per line — but keep newlines/structure.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+(\n|$)", r"\1", cleaned)
    return cleaned


def strip_emojis_deep(obj):
    """Recursively strip emojis from every string in a dict/list/str structure.

    Used on a generated model's ``model_dump()`` before re-validation, so every
    text field (titles, narrative, tips, prompts, rubric text, code) is cleaned.
    """
    if isinstance(obj, str):
        return strip_emojis(obj)
    if isinstance(obj, list):
        return [strip_emojis_deep(x) for x in obj]
    if isinstance(obj, dict):
        return {k: strip_emojis_deep(v) for k, v in obj.items()}
    return obj
