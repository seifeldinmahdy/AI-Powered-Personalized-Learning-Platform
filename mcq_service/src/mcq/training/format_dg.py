"""Format DG training data — converts raw JSONL into Llama chat-formatted examples.

Each raw MCQ produces THREE training examples — one per distractor.
Each example has a single ``text`` field containing the complete chat
conversation (system + user + assistant) formatted with the Llama tokenizer.

Usage::

    python -m mcq.training.format_dg \\
        --input data/mcq_training/mcq_raw.jsonl \\
        --output data/mcq_training/dg_train.jsonl \\
        --tokenizer unsloth/Llama-3.2-3B-Instruct
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


def _build_dg_messages(sample: dict, distractor: str) -> list[dict[str, str]]:
    """Build chat messages for a single DG training example.

    Each example teaches the model to generate one distractor given
    the question, correct answer, and conditioning fields.
    """
    mcq_src = str(Path(__file__).resolve().parent.parent.parent)
    if mcq_src not in sys.path:
        sys.path.insert(0, mcq_src)

    from mcq.prompts.mcq_prompts import build_dg_chat_prompt

    messages = build_dg_chat_prompt(
        question=sample.get("question", ""),
        correct_answer=sample.get("correct_answer", ""),
        question_type=sample.get("question_type", "4a"),
        mastery_level=sample.get("mastery_level", "Intermediate"),
        score_category=sample.get("score_category", "moderate"),
        chunk_text=sample.get("chunk", ""),
    )

    # Assistant response — single distractor in structured format
    assistant_content = f"DISTRACTOR: {distractor}"

    messages.append({"role": "assistant", "content": assistant_content})
    return messages


def format_dg_data(
    input_path: str,
    output_path: str,
    tokenizer_name: str = "unsloth/Llama-3.2-3B-Instruct",
) -> int:
    """Convert raw DG training data to Llama chat-formatted examples.

    Each raw MCQ produces 3 training examples — one per distractor.

    Parameters
    ----------
    input_path :
        Path to mcq_raw.jsonl (output of data_generator.py).
    output_path :
        Path to write formatted dg_train.jsonl.
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

                # One training example per distractor
                for distractor in distractors:
                    distractor = str(distractor).strip()
                    if not distractor:
                        continue

                    messages = _build_dg_messages(sample, distractor)

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
                logger.warning("format_dg_skip_invalid_line", line=line[:100], error=str(e))

    logger.info("format_dg_complete", samples=count, output=str(out_p))
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Format raw MCQ data into Llama chat-formatted DG training examples.",
    )
    parser.add_argument(
        "--input", required=True,
        help="Path to mcq_raw.jsonl.",
    )
    parser.add_argument(
        "--output", required=True,
        help="Path to write formatted dg_train.jsonl.",
    )
    parser.add_argument(
        "--tokenizer", default="unsloth/Llama-3.2-3B-Instruct",
        help="HuggingFace tokenizer to use for chat template formatting.",
    )
    args = parser.parse_args()

    count = format_dg_data(args.input, args.output, args.tokenizer)
    print(f"Formatted {count} DG training examples → {args.output}")


if __name__ == "__main__":
    main()
