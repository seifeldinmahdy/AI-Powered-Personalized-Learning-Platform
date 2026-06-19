"""Distractor Generator (DG) — generates wrong-but-plausible answer options.

Uses Ollama during development.  When DG_MODEL_PATH is set in settings,
loads the Qwen3-4B base model + DG LoRA adapter via Unsloth for inference.
Falls back to DG_LORA_PATH for legacy Llama-3.2-3B adapters.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import structlog

from mcq.models import GeneratedQuestion, MCQOption, MCQQuestion
from mcq.prompts.mcq_prompts import (
    build_dg_chat_prompt,
    build_dg_prompt,
    extract_dg_output,
    format_chat_for_training,
)

logger = structlog.get_logger(__name__)

# Lazy-loaded singletons — loaded once, reused for every call
_ollama_client = None
_model = None
_tokenizer = None


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

    # When DG_OLLAMA_MODEL is set we serve the local fine-tuned GGUF model
    # (e.g. "mcq-dg") from a local Ollama daemon; otherwise fall back to cloud.
    local_model = getattr(settings, "DG_OLLAMA_MODEL", "") or ""
    is_local = bool(local_model)
    _ollama_client = OllamaClient(
        host="http://localhost:11434" if is_local else settings.OLLAMA_HOST,
        model=local_model or settings.OLLAMA_MODEL,
        api_key="" if is_local else settings.OLLAMA_API_KEY,
        max_retries=3,
        timeout=120,
    )
    return _ollama_client


def _load_model(settings):
    """Load the base model + DG LoRA adapter once at startup.

    Uses Unsloth's FastLanguageModel for optimized inference.
    Prefers ``DG_MODEL_PATH`` (Qwen3-4B adapter); falls back to the
    legacy ``DG_LORA_PATH`` for Llama-3.2-3B adapters.
    """
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer

    from unsloth import FastLanguageModel

    # Prefer the new path field; fall back to the legacy one
    adapter_path = settings.DG_MODEL_PATH or settings.DG_LORA_PATH
    max_seq = getattr(settings, 'MAX_SEQ_LENGTH_DG', settings.MAX_SEQ_LENGTH)

    logger.info(
        "dg_loading_model",
        base_model=settings.LLAMA_BASE_MODEL,
        adapter_path=adapter_path,
        load_in_4bit=settings.LOAD_IN_4BIT,
    )

    # Load base model + LoRA adapter
    _model, _tokenizer = FastLanguageModel.from_pretrained(
        model_name=adapter_path,
        max_seq_length=max_seq,
        load_in_4bit=settings.LOAD_IN_4BIT,
    )

    # Optimize for inference speed (Unsloth-specific)
    FastLanguageModel.for_inference(_model)

    logger.info(
        "dg_model_loaded",
        base_model=settings.LLAMA_BASE_MODEL,
        adapter_path=adapter_path,
    )
    return _model, _tokenizer


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
    use_llama = bool(settings.DG_MODEL_PATH or settings.DG_LORA_PATH)

    distractors: list[str] = []

    for attempt in range(1, settings.MCQ_MAX_REGENERATION_ATTEMPTS + 1):
        try:
            if use_llama:
                distractors = _generate_with_llama(
                    generated_q, settings, num_distractors, chunk_text,
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
    """Generate distractors via Ollama LLM.

    Local fine-tuned mode (DG_OLLAMA_MODEL set): the model emits ONE distractor
    per call ("DISTRACTOR: …"), so we call it repeatedly and dedupe — mirroring
    how it was trained. Cloud fallback asks for all distractors as JSON at once.
    """
    client = _get_ollama_client(settings)
    correct_lower = generated_q.correct_answer.strip().lower()

    if getattr(settings, "DG_OLLAMA_MODEL", ""):
        distractors: list[str] = []
        # A couple of extra attempts to absorb dupes / answer-equal rejections.
        for _ in range(num_distractors + 2):
            if len(distractors) >= num_distractors:
                break
            messages = build_dg_chat_prompt(
                question=generated_q.question,
                correct_answer=generated_q.correct_answer,
                question_type=generated_q.question_type,
                mastery_level=generated_q.mastery_used,
                score_category=generated_q.score_category_used,
                chunk_text=chunk_text,
            )
            raw = client.chat(
                messages=messages,
                temperature=0.8,
                json_mode=False,
                timeout_override=120,
                num_predict=80,
            )
            parsed = extract_dg_output(raw)
            if not parsed:
                continue
            d = parsed.strip()
            if d.lower() == correct_lower:
                continue
            if any(d.lower() == x.strip().lower() for x in distractors):
                continue
            distractors.append(d)
        return distractors

    prompt = build_dg_prompt(
        question=generated_q.question,
        correct_answer=generated_q.correct_answer,
        question_type=generated_q.question_type,
        mastery_level=generated_q.mastery_used,
        score_category=generated_q.score_category_used,
        num_distractors=num_distractors,
        chunk_text=chunk_text,
    )
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
    cleaned = [
        str(d).strip()
        for d in raw
        if str(d).strip().lower() != correct_lower and str(d).strip()
    ]

    return cleaned


def _generate_with_llama(
    generated_q: GeneratedQuestion,
    settings,
    num_distractors: int,
    chunk_text: str = "",
) -> list[str]:
    """Generate distractors via Llama + DG LoRA adapter.

    Generates one distractor per call (each with a separate prompt).
    Uses greedy decoding for deterministic output.
    """
    import torch

    model, tokenizer = _load_model(settings)
    distractors: list[str] = []
    correct_lower = generated_q.correct_answer.strip().lower()

    # Generate slightly more than needed to account for failures
    max_attempts = num_distractors + 2

    for i in range(max_attempts):
        if len(distractors) >= num_distractors:
            break

        messages = build_dg_chat_prompt(
            question=generated_q.question,
            correct_answer=generated_q.correct_answer,
            question_type=generated_q.question_type,
            mastery_level=generated_q.mastery_used,
            score_category=generated_q.score_category_used,
            chunk_text=chunk_text,
        )

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
                max_new_tokens=80,
                temperature=0.0,
                do_sample=False,
            )

        new_tokens = outputs[0][input_len:]
        raw_output = tokenizer.decode(new_tokens, skip_special_tokens=True)

        logger.debug(
            "dg_llama_raw_output",
            output=raw_output[:150],
            distractor_idx=i,
            topic=generated_q.topic,
        )

        parsed = extract_dg_output(raw_output)
        if parsed is None:
            logger.warning(
                "dg_llama_parse_failed",
                output=raw_output[:150],
                distractor_idx=i,
            )
            continue

        # Validate: not identical to correct answer
        if parsed.strip().lower() == correct_lower:
            logger.warning(
                "dg_llama_matches_correct",
                distractor=parsed[:80],
                distractor_idx=i,
            )
            continue

        # Validate: not duplicate of existing distractors
        if any(parsed.strip().lower() == d.strip().lower() for d in distractors):
            logger.debug(
                "dg_llama_duplicate_skipped",
                distractor=parsed[:80],
                distractor_idx=i,
            )
            continue

        distractors.append(parsed)

    if len(distractors) < num_distractors:
        logger.warning(
            "dg_llama_insufficient_distractors",
            got=len(distractors),
            need=num_distractors,
            topic=generated_q.topic,
        )

        # Fallback: generate simple variations
        fallbacks = [
            f"Not {generated_q.correct_answer}",
            f"None of the above",
            f"All of the above",
        ]
        for fb in fallbacks:
            if len(distractors) >= num_distractors:
                break
            if fb.strip().lower() != correct_lower and fb not in distractors:
                distractors.append(fb)
                logger.info("dg_llama_fallback_used", fallback=fb)

    return distractors
