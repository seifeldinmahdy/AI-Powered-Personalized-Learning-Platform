"""Training data generator — creates QG/DG training pairs from chunk data.

Generates synthetic training samples by calling the Ollama LLM to produce
question-answer pairs for each question type, then formats them for T5
fine-tuning using format_qg.py and format_dg.py.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import structlog

from mcq.prompts.mcq_prompts import build_qg_prompt, build_dg_prompt
from mcq.question_types import (
    MASTERY_TYPE_ELIGIBILITY,
    QUESTION_TYPE_TAXONOMY,
    SCORE_CATEGORY_DISTRACTOR_MODIFIER,
)

logger = structlog.get_logger(__name__)

# Lazy-loaded Ollama client
_client = None


def _get_ollama_client():
    """Lazy-initialise the OllamaClient singleton for data generation."""
    global _client
    if _client is not None:
        return _client

    pathway_src = str(
        Path(__file__).resolve().parent.parent.parent.parent.parent / "course_pathway" / "src"
    )
    if pathway_src not in sys.path:
        sys.path.insert(0, pathway_src)

    from pathway.llm.naming import OllamaClient  # type: ignore

    _client = OllamaClient(
        host=os.getenv("OLLAMA_HOST", "https://ollama.com"),
        model=os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
        api_key=os.getenv("OLLAMA_API_KEY", ""),
        max_retries=3,
        timeout=180,
    )
    return _client


def generate_training_pairs(
    chunks: list[dict],
    output_dir: str,
    mastery_levels: list[str] | None = None,
    score_categories: list[str] | None = None,
) -> dict:
    """Generate QG and DG training data from chunks.

    For each chunk, iterates over mastery levels and eligible question types
    to produce training pairs.

    Parameters
    ----------
    chunks :
        List of dicts with ``text``, ``topic``, ``metadata`` keys.
    output_dir :
        Directory to write output JSONL files.
    mastery_levels :
        Override mastery levels to generate for (default: all three).
    score_categories :
        Override score categories (default: all four).

    Returns
    -------
    dict
        Summary: ``{"qg_samples": int, "dg_samples": int, "errors": int}``.
    """
    if mastery_levels is None:
        mastery_levels = ["Novice", "Intermediate", "Expert"]
    if score_categories is None:
        score_categories = ["very_weak", "weak", "moderate", "strong"]

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    qg_path = out_path / "qg_training_data.jsonl"
    dg_path = out_path / "dg_training_data.jsonl"

    client = _get_ollama_client()
    stats = {"qg_samples": 0, "dg_samples": 0, "errors": 0}

    with open(qg_path, "w", encoding="utf-8") as qg_f, \
         open(dg_path, "w", encoding="utf-8") as dg_f:

        for chunk in chunks:
            text = chunk.get("text", "")
            topic = chunk.get("topic", "General")

            if not text.strip():
                continue

            for mastery in mastery_levels:
                eligible_types = MASTERY_TYPE_ELIGIBILITY.get(mastery, ["4a"])

                for qtype in eligible_types:
                    for category in score_categories:
                        try:
                            # Generate question
                            qg_prompt = build_qg_prompt(
                                text, topic, qtype, mastery, category,
                            )
                            qg_result = client.chat_json(
                                messages=[{"role": "user", "content": qg_prompt}],
                                temperature=0.7,
                                timeout_override=180,
                            )

                            if not isinstance(qg_result, dict):
                                stats["errors"] += 1
                                continue

                            if "question" not in qg_result or "correct_answer" not in qg_result:
                                stats["errors"] += 1
                                continue

                            # Write QG training sample
                            qg_sample = {
                                "input": f"generate question: type={qtype} topic={topic} "
                                         f"mastery={mastery} score_category={category} "
                                         f"context: {text}",
                                "output": json.dumps({
                                    "question": qg_result["question"],
                                    "correct_answer": qg_result["correct_answer"],
                                    "explanation": qg_result.get("explanation", ""),
                                }),
                                "metadata": {
                                    "question_type": qtype,
                                    "mastery": mastery,
                                    "score_category": category,
                                    "topic": topic,
                                },
                            }
                            qg_f.write(json.dumps(qg_sample) + "\n")
                            stats["qg_samples"] += 1

                            # Generate distractors
                            dg_prompt = build_dg_prompt(
                                question=qg_result["question"],
                                correct_answer=qg_result["correct_answer"],
                                question_type=qtype,
                                topic=topic,
                                mastery_level=mastery,
                                score_category=category,
                                num_distractors=3,
                                chunk_text=text,
                            )
                            dg_result = client.chat_json(
                                messages=[{"role": "user", "content": dg_prompt}],
                                temperature=0.8,
                                timeout_override=180,
                            )

                            if isinstance(dg_result, dict) and isinstance(
                                dg_result.get("distractors"), list
                            ):
                                dg_sample = {
                                    "input": f"generate distractors: type={qtype} topic={topic} "
                                             f"mastery={mastery} score_category={category} "
                                             f"question: {qg_result['question']} "
                                             f"answer: {qg_result['correct_answer']}",
                                    "output": json.dumps({
                                        "distractors": dg_result["distractors"],
                                    }),
                                    "metadata": {
                                        "question_type": qtype,
                                        "mastery": mastery,
                                        "score_category": category,
                                        "topic": topic,
                                    },
                                }
                                dg_f.write(json.dumps(dg_sample) + "\n")
                                stats["dg_samples"] += 1
                            else:
                                stats["errors"] += 1

                        except Exception:
                            logger.exception(
                                "training_pair_generation_error",
                                topic=topic,
                                qtype=qtype,
                                mastery=mastery,
                                category=category,
                            )
                            stats["errors"] += 1

    logger.info("training_data_generated", **stats)
    return stats
