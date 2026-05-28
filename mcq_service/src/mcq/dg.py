"""Distractor Generator (DG) — generates wrong-but-plausible answer options.

Uses Ollama during development.  When DG_MODEL_PATH is set in settings,
loads a fine-tuned T5 model instead.  No factory, no abstract classes.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import structlog

from mcq.models import GeneratedQuestion, MCQOption, MCQQuestion
from mcq.prompts.mcq_prompts import build_dg_prompt, build_dg_t5_input

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
    """Load fine-tuned T5 DG model and tokenizer from disk."""
    global _t5_model, _t5_tokenizer
    if _t5_model is not None:
        return _t5_model, _t5_tokenizer

    from transformers import T5ForConditionalGeneration, T5Tokenizer

    _t5_tokenizer = T5Tokenizer.from_pretrained(model_path)
    _t5_model = T5ForConditionalGeneration.from_pretrained(model_path)
    _t5_model.eval()

    logger.info("dg_t5_model_loaded", path=model_path)
    return _t5_model, _t5_tokenizer


def generate_mcq(
    generated_q: GeneratedQuestion,
    settings,
    chunk_text: str = "",
) -> MCQQuestion | None:
    """Attach distractors to a GeneratedQuestion and return a complete MCQQuestion.

    Parameters
    ----------
    generated_q :
        The question from the QG stage.
    settings :
        MCQSettings instance.
    chunk_text :
        Source text for context (optional).

    Returns
    -------
    MCQQuestion or None
        None if distractor generation fails completely.
    """
    num_distractors = settings.MCQ_DISTRACTOR_COUNT
    use_t5 = bool(settings.DG_MODEL_PATH)

    distractors: list[str] = []

    for attempt in range(1, settings.MCQ_MAX_REGENERATION_ATTEMPTS + 1):
        try:
            if use_t5:
                distractors = _generate_with_t5(
                    generated_q, settings.DG_MODEL_PATH, num_distractors,
                )
            else:
                distractors = _generate_with_ollama(
                    generated_q, settings, num_distractors, chunk_text,
                )

            if distractors and len(distractors) >= num_distractors:
                break

            logger.warning(
                "dg_attempt_insufficient",
                attempt=attempt,
                got=len(distractors),
                need=num_distractors,
            )

        except Exception:
            logger.exception(
                "dg_attempt_error",
                attempt=attempt,
                topic=generated_q.topic,
            )

    if not distractors:
        logger.error(
            "dg_all_attempts_failed",
            topic=generated_q.topic,
            question=generated_q.question[:80],
        )
        return None

    # Trim to exact count
    distractors = distractors[:num_distractors]

    # Build options: 1 correct + N distractors, shuffled
    options: list[MCQOption] = [
        MCQOption(text=generated_q.correct_answer, is_correct=True),
    ]
    for d in distractors:
        options.append(MCQOption(text=d, is_correct=False))

    random.shuffle(options)

    return MCQQuestion(
        question=generated_q.question,
        options=options,
        correct_answer=generated_q.correct_answer,
        explanation=generated_q.explanation,
        question_type=generated_q.question_type,
        topic=generated_q.topic,
        mastery_used=generated_q.mastery_used,
        score_category_used=generated_q.score_category_used,
        distractor_scores=None,
        generation_mode=generated_q.generation_mode,
    )


def _generate_with_ollama(
    generated_q: GeneratedQuestion,
    settings,
    num_distractors: int,
    chunk_text: str = "",
) -> list[str]:
    """Generate distractors via Ollama LLM."""
    prompt = build_dg_prompt(
        question=generated_q.question,
        correct_answer=generated_q.correct_answer,
        question_type=generated_q.question_type,
        topic=generated_q.topic,
        mastery_level=generated_q.mastery_used,
        score_category=generated_q.score_category_used,
        num_distractors=num_distractors,
        chunk_text=chunk_text,
    )

    client = _get_ollama_client(settings)
    data = client.chat_json(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
        timeout_override=120,
    )

    if not isinstance(data, dict):
        return []

    raw = data.get("distractors", [])
    if not isinstance(raw, list):
        return []

    # Filter: no distractor should match the correct answer
    correct_lower = generated_q.correct_answer.strip().lower()
    cleaned = [
        str(d).strip()
        for d in raw
        if str(d).strip().lower() != correct_lower and str(d).strip()
    ]

    return cleaned


def _generate_with_t5(
    generated_q: GeneratedQuestion,
    model_path: str,
    num_distractors: int,
) -> list[str]:
    """Generate distractors via fine-tuned T5 model."""
    import torch

    model, tokenizer = _load_t5_model(model_path)
    input_text = build_dg_t5_input(
        question=generated_q.question,
        correct_answer=generated_q.correct_answer,
        question_type=generated_q.question_type,
        topic=generated_q.topic,
        mastery_level=generated_q.mastery_used,
        score_category=generated_q.score_category_used,
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
        raw = result.get("distractors", [])
        if isinstance(raw, list):
            return [str(d).strip() for d in raw if str(d).strip()]
    except json.JSONDecodeError:
        logger.warning("dg_t5_invalid_json", output=decoded[:200])

    return []
