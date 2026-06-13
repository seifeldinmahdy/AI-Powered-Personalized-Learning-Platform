"""Format QG training data — converts cleaned JSONL into chat-formatted examples.

Reads cleaned MCQ data and writes qg_formatted.jsonl with a single ``text`` field
containing the complete chat conversation (system + user + assistant) formatted
with the tokenizer's chat template.  This is the format TRL's SFTTrainer
expects when using ``dataset_text_field="text"``.

The system message is the simplified training system prompt (~150 tokens) that
replaced the full taxonomy (~1000 tokens) from prior runs.  The user turn uses
a compact pipe-delimited format that is faster to tokenize than prose.

These prompts are used ONLY for generating training data — the inference prompts
in ``mcq_prompts.py`` are unchanged and can be richer.

Usage::

    python -m mcq.training.format_qg \\
        --input  data/mcq_training/mcq_final_cleaned.jsonl \\
        --output data/mcq_training/qg_formatted.jsonl \\
        --tokenizer unsloth/Qwen3-4B-Instruct
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

# ── Box-drawing detection ─────────────────────────────────────────────────────
_BOX_DRAWING_RE = re.compile(r'[\u2500-\u257f]')

# ── Simplified QG training system prompt ─────────────────────────────────────
# ~150 tokens — replaces the full taxonomy (~1000 tokens) that caused 10-12 h
# training sessions.  The model learns the full taxonomy from the examples.
# Do NOT use this prompt for inference; use build_qg_chat_prompt() instead.
_QG_TRAINING_SYSTEM_PROMPT = """\
You are an expert MCQ generator for a personalized CS learning platform.

TWO SIGNALS — TWO DIFFERENT JOBS:
  mastery_level controls HOW you frame the question:
    vocabulary depth, cognitive register, distractor sophistication
  score_category controls HOW HARD the question is:
    difficulty level, and whether mastery type is overridden

Question types:
1=Method/API, 2=Code Output, 3=Code Completion,
4a=Definition, 4b=Distinction, 4c=Application,
4d=Reasoning, 4e=Misconception

Mastery framing:
  Novice: simple vocabulary, what IS or DOES, no cross-concept reasoning
  Intermediate: standard CS terms, connect ideas, never pure definition
  Expert: precise technical language, WHY it works, tradeoffs

Score category difficulty:
  very_weak: TYPE is always 4a -- ignore mastery for type only,
             keep mastery vocabulary; difficulty minimum
  weak: one level easier than mastery standard
  moderate: standard for mastery
  strong: hardest type mastery allows

OUTPUT FORMAT (required, no exceptions):
QUESTION: <question text>
ANSWER: <correct answer>
EXPLANATION: <why this is correct, testing the concept not a textbook example>

HARD RULE: When score_category is very_weak -> always Type 4a.
HARD RULE: Questions test transferable concepts, never textbook-specific examples.
HARD RULE: Never reproduce more than 5 lines of code in a question.\
"""

# ── Explanation normalization — strip letter-based option references ───────────
# Order matters: longer/more-specific patterns first to avoid partial matches.
_EXPLANATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    # "Options A, B, and C" / "options B, C, and D" (3 letters with commas)
    (re.compile(
        r'\boptions?\s+[A-D],\s*[A-D],?\s*and\s+[A-D]\b',
        re.IGNORECASE,
    ), 'the other options'),
    # "Options A and B" / "options C and D" (2 letters)
    (re.compile(
        r'\boptions?\s+[A-D]\s+and\s+[A-D]\b',
        re.IGNORECASE,
    ), 'the other options'),
    # "Choices A, B, and C" (3 letters with commas)
    (re.compile(
        r'\bchoices?\s+[A-D],\s*[A-D],?\s*and\s+[A-D]\b',
        re.IGNORECASE,
    ), 'the other choices'),
    # "Choices A and B" (2 letters)
    (re.compile(
        r'\bchoices?\s+[A-D]\s+and\s+[A-D]\b',
        re.IGNORECASE,
    ), 'the other choices'),
    # "Option A" / "option D" (single letter)
    (re.compile(r'\boption\s+[A-D]\b', re.IGNORECASE), 'this option'),
    # "Choice A" / "choice D" (single letter)
    (re.compile(r'\bchoice\s+[A-D]\b', re.IGNORECASE), 'this choice'),
    # Standalone "(A)" / "(B)" etc. used as inline references
    (re.compile(r'\(([A-D])\)(?=\s)'), 'it'),
]


def _normalize_explanation(text: str) -> str:
    """Remove letter-based answer-option references from an explanation."""
    for pattern, replacement in _EXPLANATION_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _build_qg_training_messages(sample: dict) -> list[dict[str, str]]:
    """Build chat messages for a single QG training example.

    Returns the [system, user, assistant] message list using the compact
    pipe-delimited format.  Does NOT use build_qg_chat_prompt() — the
    training system prompt is intentionally shorter than the inference one.
    """
    question_type  = sample.get("question_type", "4a")
    mastery        = sample.get("mastery_level", "Intermediate")
    score_category = sample.get("score_category", "moderate")
    chunk          = sample.get("chunk", "")

    user_content = (
        f"generate question: type: {question_type} | mastery: {mastery} | "
        f"score_category: {score_category} | content: {chunk}"
    )

    explanation = sample.get("explanation", "No explanation provided.")
    explanation = _normalize_explanation(explanation)

    assistant_content = (
        f"QUESTION: {sample['question']}\n"
        f"ANSWER: {sample['correct_answer']}\n"
        f"EXPLANATION: {explanation}"
    )

    return [
        {"role": "system",    "content": _QG_TRAINING_SYSTEM_PROMPT},
        {"role": "user",      "content": user_content},
        {"role": "assistant", "content": assistant_content},
    ]


def format_qg_data(
    input_path: str,
    output_path: str,
    tokenizer_name: str = "unsloth/Qwen3-4B-Instruct",
) -> int:
    """Convert cleaned QG data to chat-formatted training examples.

    Parameters
    ----------
    input_path :
        Path to mcq_final_cleaned.jsonl (output of clean_dataset.py).
    output_path :
        Path to write formatted qg_formatted.jsonl.
    tokenizer_name :
        HuggingFace tokenizer identifier for applying the chat template.

    Returns
    -------
    int
        Number of formatted samples written.
    """
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
    logger.info("format_qg_tokenizer_loaded", tokenizer=tokenizer_name)

    in_p = Path(input_path)
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    box_drawing_warnings = 0

    with open(in_p, "r", encoding="utf-8") as fin, \
         open(out_p, "w", encoding="utf-8") as fout:

        for line in fin:
            line = line.strip()
            if not line:
                continue

            try:
                sample = json.loads(line)

                # Validate required fields
                if not sample.get("question") or not sample.get("correct_answer"):
                    logger.warning("format_qg_skip_missing_fields", line=line[:100])
                    continue

                messages = _build_qg_training_messages(sample)

                # Apply chat template to get the full formatted string.
                # Qwen3 supports enable_thinking=False for non-thinking mode
                # (direct structured output, no chain-of-thought overhead).
                try:
                    text = tokenizer.apply_chat_template(
                        messages,
                        tokenize=False,
                        add_generation_prompt=False,
                        enable_thinking=False,
                    )
                except TypeError:
                    # Fallback for tokenizers that don't support enable_thinking
                    text = tokenizer.apply_chat_template(
                        messages,
                        tokenize=False,
                        add_generation_prompt=False,
                    )

                # Strip any residual box-drawing characters from the rendered text.
                # This catches any that may have leaked through the chunk field.
                if _BOX_DRAWING_RE.search(text):
                    text = _BOX_DRAWING_RE.sub('', text)
                    box_drawing_warnings += 1

                formatted = {
                    "text": text,
                    "question_type":  sample.get("question_type", "unknown"),
                    "mastery_level":  sample.get("mastery_level", "unknown"),
                    "score_category": sample.get("score_category", "unknown"),
                }
                fout.write(json.dumps(formatted) + "\n")
                count += 1

            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("format_qg_skip_invalid_line", line=line[:100], error=str(e))

    if box_drawing_warnings:
        logger.warning(
            "format_qg_box_drawing_stripped",
            count=box_drawing_warnings,
            note="Box-drawing chars found in rendered text and stripped",
        )

    logger.info("format_qg_complete", samples=count, output=str(out_p))
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Format cleaned MCQ data into Qwen3 chat-formatted QG training examples.",
    )
    parser.add_argument(
        "--input", default="data/mcq_training/mcq_final_cleaned.jsonl",
        help="Path to cleaned MCQ JSONL (default: mcq_final_cleaned.jsonl).",
    )
    parser.add_argument(
        "--output", required=True,
        help="Path to write formatted qg_formatted.jsonl.",
    )
    parser.add_argument(
        "--tokenizer", default="unsloth/Qwen3-4B-Instruct",
        help="HuggingFace tokenizer to use for chat template formatting.",
    )
    args = parser.parse_args()

    count = format_qg_data(args.input, args.output, args.tokenizer)
    print(f"Formatted {count} QG training examples -> {args.output}")


if __name__ == "__main__":
    main()
