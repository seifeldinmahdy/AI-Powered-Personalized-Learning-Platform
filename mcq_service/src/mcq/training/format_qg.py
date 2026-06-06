"""Format QG training data — converts raw JSONL into Llama chat-formatted examples.

Reads cleaned MCQ data and writes qg_train.jsonl with a single ``text`` field
containing the complete chat conversation (system + user + assistant) formatted
with the Llama tokenizer's chat template.  This is the format TRL's SFTTrainer
expects when using ``dataset_text_field="text"``.

Usage::

    python -m mcq.training.format_qg \\
        --input data/mcq_training/mcq_final_cleaned.jsonl \\
        --output data/mcq_training/qg_formatted.jsonl \\
        --tokenizer unsloth/Llama-3.2-3B-Instruct
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

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


def _build_qg_messages(sample: dict) -> list[dict[str, str]]:
    """Build chat messages for a single QG training example.

    Returns the system + user + assistant message list.
    The assistant response uses the structured QUESTION/ANSWER/EXPLANATION format.
    """
    # Lazy import to avoid circular dependency at module level
    mcq_src = str(Path(__file__).resolve().parent.parent.parent)
    if mcq_src not in sys.path:
        sys.path.insert(0, mcq_src)

    from mcq.prompts.mcq_prompts import build_qg_chat_prompt

    messages = build_qg_chat_prompt(
        chunk_text=sample.get("chunk", ""),
        question_type=sample.get("question_type", "4a"),
        mastery_level=sample.get("mastery_level", "Intermediate"),
        score_category=sample.get("score_category", "moderate"),
    )

    explanation = sample.get('explanation', 'No explanation provided.')
    explanation = _normalize_explanation(explanation)

    # Build assistant response in the structured output format
    assistant_content = (
        f"QUESTION: {sample['question']}\n"
        f"ANSWER: {sample['correct_answer']}\n"
        f"EXPLANATION: {explanation}"
    )

    messages.append({"role": "assistant", "content": assistant_content})
    return messages


def format_qg_data(
    input_path: str,
    output_path: str,
    tokenizer_name: str = "unsloth/Llama-3.2-3B-Instruct",
) -> int:
    """Convert raw QG training data to Llama chat-formatted examples.

    Parameters
    ----------
    input_path :
        Path to mcq_raw.jsonl (output of data_generator.py).
    output_path :
        Path to write formatted qg_train.jsonl.
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

                messages = _build_qg_messages(sample)

                # Apply chat template to get the full formatted string
                text = tokenizer.apply_chat_template(
                    messages,
                    tokenize=False,
                    add_generation_prompt=False,
                )

                formatted = {
                    "text": text,
                    "question_type": sample.get("question_type", "unknown"),
                    "mastery_level": sample.get("mastery_level", "unknown"),
                    "score_category": sample.get("score_category", "unknown"),
                }
                fout.write(json.dumps(formatted) + "\n")
                count += 1

            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("format_qg_skip_invalid_line", line=line[:100], error=str(e))

    logger.info("format_qg_complete", samples=count, output=str(out_p))
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Format raw MCQ data into Llama chat-formatted QG training examples.",
    )
    parser.add_argument(
        "--input", default="data/mcq_training/mcq_final_cleaned.jsonl",
        help="Path to cleaned MCQ JSONL (default: mcq_final_cleaned.jsonl).",
    )
    parser.add_argument(
        "--output", required=True,
        help="Path to write formatted qg_train.jsonl.",
    )
    parser.add_argument(
        "--tokenizer", default="unsloth/Llama-3.2-3B-Instruct",
        help="HuggingFace tokenizer to use for chat template formatting.",
    )
    args = parser.parse_args()

    count = format_qg_data(args.input, args.output, args.tokenizer)
    print(f"Formatted {count} QG training examples → {args.output}")


if __name__ == "__main__":
    main()
