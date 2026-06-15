"""Format DG training data — converts cleaned JSONL into chat-formatted examples.

Each raw MCQ produces THREE training examples — one per distractor.
Each example has a single ``text`` field containing the complete chat
conversation (system + user + assistant) formatted with the tokenizer.

The system message is the simplified training system prompt (~100 tokens).
The user turn uses a compact pipe-delimited format.

These prompts are used ONLY for generating training data — the inference prompts
in ``mcq_prompts.py`` are unchanged and can be richer.

Usage::

    python -m mcq.training.format_dg \\
        --input  data/mcq_training/mcq_final_cleaned.jsonl \\
        --output data/mcq_training/dg_formatted.jsonl \\
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

# ── Simplified DG training system prompt ─────────────────────────────────────
# ~100 tokens — replaces the full taxonomy that caused 17 h training sessions.
# Do NOT use this prompt for inference; use build_dg_chat_prompt() instead.
_DG_TRAINING_SYSTEM_PROMPT = """\
You are an expert distractor generator for CS multiple-choice questions.

Generate ONE plausible but incorrect answer that a student with a
specific misconception might choose.

TWO SIGNALS CONTROL THE DISTRACTOR:
  mastery_level controls distractor sophistication:
    Novice: clearly wrong to anyone who read carefully
    Intermediate: requires careful reasoning to eliminate
    Expert: plausible to someone with partial understanding,
            technically adjacent but ultimately wrong

  score_category controls distractor difficulty:
    very_weak: easy to eliminate -- student needs confidence
    weak: plausible but distinguishable with effort
    moderate: standard plausibility
    strong: as subtle and tricky as mastery allows

OUTPUT FORMAT (required):
DISTRACTOR: <the incorrect answer>

The distractor must be factually wrong, distinct from the correct
answer, and match the sophistication and difficulty specified above.\
"""


def _build_dg_training_messages(
    sample: dict,
    distractor: str,
    distractor_category: str,
) -> list[dict[str, str]]:
    """Build chat messages for a single DG training example.

    Each example teaches the model to generate one distractor given
    the question, correct answer, and conditioning fields.
    """
    question_type      = sample.get("question_type", "4a")
    mastery            = sample.get("mastery_level", "Intermediate")
    score_category     = sample.get("score_category", "moderate")
    question           = sample.get("question", "")
    correct_answer     = sample.get("correct_answer", "")
    chunk              = sample.get("chunk", "")

    user_content = (
        f"generate distractor: type: {question_type} | mastery: {mastery} | "
        f"score_category: {score_category} | category: {distractor_category} | "
        f"question: {question} | answer: {correct_answer} | content: {chunk}"
    )

    assistant_content = f"DISTRACTOR: {distractor}"

    return [
        {"role": "system",    "content": _DG_TRAINING_SYSTEM_PROMPT},
        {"role": "user",      "content": user_content},
        {"role": "assistant", "content": assistant_content},
    ]


def format_dg_data(
    input_path: str,
    output_path: str,
    tokenizer_name: str = "unsloth/Qwen3-4B-Instruct-2507",
) -> int:
    """Convert cleaned DG data to chat-formatted training examples.

    Each raw MCQ produces 3 training examples — one per distractor.

    Parameters
    ----------
    input_path :
        Path to mcq_final_cleaned.jsonl (output of clean_dataset.py).
    output_path :
        Path to write formatted dg_formatted.jsonl.
    tokenizer_name :
        HuggingFace tokenizer identifier for applying the chat template.

    Returns
    -------
    int
        Number of formatted samples written.
    """
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
    logger.info("format_dg_tokenizer_loaded", tokenizer=tokenizer_name)

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

                distractors = sample.get("distractors", [])
                if not distractors or not sample.get("question") or not sample.get("correct_answer"):
                    logger.warning("format_dg_skip_missing_fields", line=line[:100])
                    continue

                # distractors_meta carries per-distractor category labels when
                # present (set by data_generator.py).  Fall back gracefully.
                distractors_meta: list[dict] = sample.get("distractors_meta", [])

                # One training example per distractor
                for idx, distractor in enumerate(distractors):
                    distractor = str(distractor).strip()
                    if not distractor:
                        continue

                    # Resolve distractor category from meta or default
                    if idx < len(distractors_meta) and isinstance(distractors_meta[idx], dict):
                        distractor_category = distractors_meta[idx].get("category", "general")
                    else:
                        distractor_category = "general"

                    messages = _build_dg_training_messages(sample, distractor, distractor_category)

                    # Apply chat template.
                    # Qwen3 supports enable_thinking=False for non-thinking mode.
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

                    # Qwen3-2507's template injects an empty "<think></think>"
                    # block into every assistant turn even with enable_thinking
                    # =False. Strip it so the DG model learns to emit the answer
                    # directly (saves ~8 tokens/gen; inference anchors at
                    # "assistant\n" with no think block, so this stays consistent).
                    text = text.replace("<think>\n\n</think>\n\n", "")

                    # Strip any residual box-drawing characters.
                    if _BOX_DRAWING_RE.search(text):
                        text = _BOX_DRAWING_RE.sub('', text)
                        box_drawing_warnings += 1

                    formatted = {
                        "text":             text,
                        "question_type":    sample.get("question_type", "unknown"),
                        "mastery_level":    sample.get("mastery_level", "unknown"),
                        "score_category":   sample.get("score_category", "unknown"),
                        "distractor_category": distractor_category,
                    }
                    fout.write(json.dumps(formatted) + "\n")
                    count += 1

            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("format_dg_skip_invalid_line", line=line[:100], error=str(e))

    if box_drawing_warnings:
        logger.warning(
            "format_dg_box_drawing_stripped",
            count=box_drawing_warnings,
            note="Box-drawing chars found in rendered text and stripped",
        )

    logger.info("format_dg_complete", samples=count, output=str(out_p))
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Format cleaned MCQ data into Qwen3 chat-formatted DG training examples.",
    )
    parser.add_argument(
        "--input", default="data/mcq_training/mcq_final_cleaned.jsonl",
        help="Path to cleaned MCQ JSONL (default: mcq_final_cleaned.jsonl).",
    )
    parser.add_argument(
        "--output", required=True,
        help="Path to write formatted dg_formatted.jsonl.",
    )
    parser.add_argument(
        "--tokenizer", default="unsloth/Qwen3-4B-Instruct-2507",
        help="HuggingFace tokenizer to use for chat template formatting.",
    )
    args = parser.parse_args()

    count = format_dg_data(args.input, args.output, args.tokenizer)
    print(f"Formatted {count} DG training examples -> {args.output}")


if __name__ == "__main__":
    main()
