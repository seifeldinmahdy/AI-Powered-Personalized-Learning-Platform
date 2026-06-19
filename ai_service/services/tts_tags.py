"""Paralinguistic tag handling shared across the voice pipeline.

Chatterbox Turbo understands a fixed set of bracketed non-verbal cues. The tutor
LLM may weave them into its speech, but they must be handled per-consumer:

  - **Chatterbox**: keep the VALID cues (it speaks them), drop any invalid
    bracketed token the model hallucinated.
  - **Edge TTS** (fallback): strip ALL bracketed tags — Edge would otherwise read
    "[sigh]" out loud.
  - **Display / transcript / durable log / profiler**: strip ALL tags — the
    student should never see them and they must not pollute profiler claims.

This single module is the source of truth for the tag set so the prompt, the two
TTS backends, and the transcript path can never drift.
"""

from __future__ import annotations

import re

# The ONLY non-verbal cues Chatterbox Turbo actually interprets.
VALID_PARALINGUISTIC_TAGS = [
    "clear throat", "sigh", "shush", "cough",
    "groan", "sniff", "gasp", "chuckle", "laugh",
]
_VALID_SET = {t.lower() for t in VALID_PARALINGUISTIC_TAGS}

# Any short bracketed token, e.g. "[sigh]" / "[clear throat]" / "[pause]".
_ANY_TAG_RE = re.compile(r"\[[^\]\n]{1,40}\]")


def _tidy(text: str) -> str:
    """Collapse the whitespace/punctuation a removed tag can leave behind."""
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)  # no space before punctuation
    return text.strip()


def strip_all_tags(text: str) -> str:
    """Remove EVERY bracketed cue — for display, transcript, and Edge TTS."""
    if not text:
        return text
    return _tidy(_ANY_TAG_RE.sub("", text))


def keep_valid_tags(text: str) -> str:
    """Keep only the cues Chatterbox understands; drop any other bracketed token."""
    if not text:
        return text

    def _repl(m: "re.Match") -> str:
        inner = m.group(0)[1:-1].strip().lower()
        return m.group(0) if inner in _VALID_SET else ""

    return _tidy(_ANY_TAG_RE.sub(_repl, text))


# Prompt fragment listing the allowed cues — imported by the tutor prompts so the
# instruction and the interpreter can never disagree on the tag set.
TAG_PROMPT_GUIDANCE = (
    "SPOKEN CUES: You may VERY OCCASIONALLY include ONE of these exact non-verbal "
    "cues, written in square brackets, ONLY where it genuinely fits the moment "
    "(often you will use none or clear throat in the beginning): "
    + " ".join(f"[{t}]" for t in VALID_PARALINGUISTIC_TAGS) + ". "
    "They are spoken sounds, not text — at most one per turn. Do NOT invent any "
    "other bracketed tag, and do NOT use asterisks or written stage directions "
    "like '(pauses)' or '(laughs)'."
)
