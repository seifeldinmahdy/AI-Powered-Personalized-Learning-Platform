"""Question Generator (QG) — generates a single MCQ question from a chunk.

Uses Ollama during development.  When QG_MODEL_PATH is set in settings,
loads a fine-tuned T5 model instead.  No factory, no abstract classes.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import structlog

from mcq.models import GeneratedQuestion
from mcq.prompts.mcq_prompts import build_qg_prompt, build_qg_t5_input

logger = structlog.get_logger(__name__)

# Lazy-loaded singletons
_ollama_client = None
_t5_model = None
_t5_tokenizer = None


def _get_ollama_client(settings):
    """Lazy-initialise the OllamaClient singleton."""
    global _ollama_client
    if _ollama_client is not None:
        return _ollama_client

    # Reuse OllamaClient from course_pathway
    pathway_src = str(
        Path(__file__).resolve().parent.parent.parent.parent / "course_pathway" / "src"
    )
    if pathway_src not in sys.path:
        sys.path.insert(0, pathway_src)

    from pathway.llm.naming import OllamaClient  # type: ignore

    _ollama_client = OllamaClient(
        host=settings.OLLAMA_HOST,
        model=settings.OLLAMA_MODEL,
        api_key=settings.OLLAMA_API_KEY,
        max_retries=3,
        timeout=120,
    )
    return _ollama_client


def _load_t5_model(model_path: str):
    """Load fine-tuned T5 model and tokenizer from disk."""
    global _t5_model, _t5_tokenizer
    if _t5_model is not None:
        return _t5_model, _t5_tokenizer

    from transformers import T5ForConditionalGeneration, T5Tokenizer

    _t5_tokenizer = T5Tokenizer.from_pretrained(model_path)
    _t5_model = T5ForConditionalGeneration.from_pretrained(model_path)
    _t5_model.eval()

    logger.info("qg_t5_model_loaded", path=model_path)
    return _t5_model, _t5_tokenizer


def generate_question(
    chunk_text: str,
    topic: str,
    question_type: str,
    mastery_level: str,
    score_category: str,
    settings,
) -> GeneratedQuestion | None:
    """Generate a single MCQ question for the given chunk.

    Parameters
    ----------
    chunk_text :
        Source text from which the question is derived.
    topic :
        Topic tag.
    question_type :
        Type ID from the taxonomy (e.g. "1", "4a").
    mastery_level :
        Student's global mastery level.
    score_category :
        Per-topic score category.
    settings :
        MCQSettings instance.

    Returns
    -------
    GeneratedQuestion or None
        None if generation fails after all retry attempts.
    """
    use_t5 = bool(settings.QG_MODEL_PATH)
    generation_mode = "t5" if use_t5 else "ollama"

    for attempt in range(1, settings.MCQ_MAX_REGENERATION_ATTEMPTS + 1):
        try:
            if use_t5:
                result = _generate_with_t5(
                    chunk_text, topic, question_type, mastery_level,
                    score_category, settings.QG_MODEL_PATH,
                )
            else:
                result = _generate_with_ollama(
                    chunk_text, topic, question_type, mastery_level,
                    score_category, settings,
                )

            if result is None:
                logger.warning(
                    "qg_attempt_failed",
                    attempt=attempt,
                    topic=topic,
                    type=question_type,
                    reason="empty_result",
                )
                continue

            return GeneratedQuestion(
                question=result["question"],
                correct_answer=result["correct_answer"],
                question_type=question_type,
                topic=topic,
                explanation=result.get("explanation", ""),
                mastery_used=mastery_level,
                score_category_used=score_category,
                generation_mode=generation_mode,
            )

        except Exception:
            logger.exception(
                "qg_attempt_error",
                attempt=attempt,
                topic=topic,
                type=question_type,
            )

    logger.error(
        "qg_all_attempts_failed",
        topic=topic,
        type=question_type,
        max_attempts=settings.MCQ_MAX_REGENERATION_ATTEMPTS,
    )
    return None


def _generate_with_ollama(
    chunk_text: str,
    topic: str,
    question_type: str,
    mastery_level: str,
    score_category: str,
    settings,
) -> dict | None:
    """Generate question via Ollama LLM."""
    prompt = build_qg_prompt(
        chunk_text, topic, question_type, mastery_level, score_category,
    )

    client = _get_ollama_client(settings)
    data = client.chat_json(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        timeout_override=120,
    )

    if not isinstance(data, dict):
        return None

    if "question" not in data or "correct_answer" not in data:
        logger.warning("qg_ollama_missing_keys", keys=list(data.keys()))
        return None

    return data


def _generate_with_t5(
    chunk_text: str,
    topic: str,
    question_type: str,
    mastery_level: str,
    score_category: str,
    model_path: str,
) -> dict | None:
    """Generate question via fine-tuned T5 model."""
    import torch

    model, tokenizer = _load_t5_model(model_path)
    input_text = build_qg_t5_input(
        chunk_text, topic, question_type, mastery_level, score_category,
    )

    inputs = tokenizer(
        input_text,
        return_tensors="pt",
        max_length=512,
        truncation=True,
    )

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=256,
            num_beams=4,
            early_stopping=True,
        )

    decoded = tokenizer.decode(outputs[0], skip_special_tokens=True)

    try:
        result = json.loads(decoded)
        if "question" in result and "correct_answer" in result:
            return result
    except json.JSONDecodeError:
        logger.warning("qg_t5_invalid_json", output=decoded[:200])

    return None
