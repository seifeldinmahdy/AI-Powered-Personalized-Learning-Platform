"""Question Generator (QG) — generates a single MCQ question from a chunk.

Uses Ollama during development.  When QG_LORA_PATH is set in settings,
loads the Llama base model + QG LoRA adapter via Unsloth for inference.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import structlog

from mcq.models import GeneratedQuestion
from mcq.prompts.mcq_prompts import (
    build_qg_chat_prompt,
    build_qg_prompt,
    extract_qg_output,
    format_chat_for_training,
)

logger = structlog.get_logger(__name__)

# Lazy-loaded singletons — loaded once, reused for every call
_ollama_client = None
_llama_model = None
_llama_tokenizer = None


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


def _load_llama_model(settings):
    """Load the Llama base model + QG LoRA adapter once at startup.

    Uses Unsloth's FastLanguageModel for optimized inference.
    The base model is loaded with the same quantization settings used
    during training, and the LoRA adapter is applied on top.
    """
    global _llama_model, _llama_tokenizer
    if _llama_model is not None:
        return _llama_model, _llama_tokenizer

    from unsloth import FastLanguageModel

    logger.info(
        "qg_loading_llama_model",
        base_model=settings.LLAMA_BASE_MODEL,
        lora_path=settings.QG_LORA_PATH,
        load_in_4bit=settings.LOAD_IN_4BIT,
    )

    # Load base model + LoRA adapter in one call
    _llama_model, _llama_tokenizer = FastLanguageModel.from_pretrained(
        model_name=settings.QG_LORA_PATH,
        max_seq_length=settings.MAX_SEQ_LENGTH,
        load_in_4bit=settings.LOAD_IN_4BIT,
    )

    # Optimize for inference speed (Unsloth-specific)
    FastLanguageModel.for_inference(_llama_model)

    logger.info(
        "qg_llama_model_loaded",
        base_model=settings.LLAMA_BASE_MODEL,
        lora_path=settings.QG_LORA_PATH,
    )
    return _llama_model, _llama_tokenizer


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
    use_llama = bool(settings.QG_LORA_PATH)
    generation_mode = "llama_lora" if use_llama else "ollama"

    for attempt in range(1, settings.MCQ_MAX_REGENERATION_ATTEMPTS + 1):
        try:
            if use_llama:
                result = _generate_with_llama(
                    chunk_text, topic, question_type, mastery_level,
                    score_category, settings, attempt,
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
                    mode=generation_mode,
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
                mode=generation_mode,
            )

    logger.error(
        "qg_all_attempts_failed",
        topic=topic,
        type=question_type,
        max_attempts=settings.MCQ_MAX_REGENERATION_ATTEMPTS,
        mode=generation_mode,
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


def _generate_with_llama(
    chunk_text: str,
    topic: str,
    question_type: str,
    mastery_level: str,
    score_category: str,
    settings,
    attempt: int,
) -> dict | None:
    """Generate question via Llama + QG LoRA adapter.

    Uses greedy decoding for deterministic output.  On retry (attempt > 1),
    adds a format-enforcement hint to the system message.
    """
    import torch

    model, tokenizer = _load_llama_model(settings)

    messages = build_qg_chat_prompt(
        chunk_text, topic, question_type, mastery_level, score_category,
    )

    # On retry, reinforce the format constraint
    if attempt > 1:
        messages[0]["content"] += "\n\nOutput only in the specified format."

    input_text = format_chat_for_training(messages, tokenizer)
    inputs = tokenizer(
        input_text,
        return_tensors="pt",
        truncation=True,
        max_length=settings.MAX_SEQ_LENGTH,
    )
    inputs = {k: v.to(model.device) for k, v in inputs.items()}
    input_len = inputs["input_ids"].shape[1]

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=150,
            temperature=0.0,
            do_sample=False,
        )

    # Extract only generated tokens (not the input prompt)
    new_tokens = outputs[0][input_len:]
    raw_output = tokenizer.decode(new_tokens, skip_special_tokens=True)

    logger.debug(
        "qg_llama_raw_output",
        output=raw_output[:200],
        topic=topic,
        type=question_type,
    )

    parsed = extract_qg_output(raw_output)
    if parsed is None:
        logger.warning(
            "qg_llama_parse_failed",
            attempt=attempt,
            output=raw_output[:200],
            topic=topic,
            type=question_type,
        )
        return None

    return parsed
