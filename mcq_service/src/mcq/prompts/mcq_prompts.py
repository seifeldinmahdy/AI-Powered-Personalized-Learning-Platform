"""Prompt templates for question generation (QG) and distractor generation (DG).

All prompts produce chat-formatted message lists for Llama 3.2 Instruct.
The Ollama development path still uses the flat-string versions.
Includes output parsers for the structured QUESTION/ANSWER/EXPLANATION and
DISTRACTOR output formats used by the fine-tuned LoRA models.
"""

from __future__ import annotations

import re

from mcq.question_types import (
    QUESTION_TYPE_TAXONOMY,
    SCORE_CATEGORY_DISTRACTOR_MODIFIER,
)
from mcq.scoring_categories import score_category_description


# ═══════════════════════════════════════════════════════════════════════════════
# QG — OLLAMA PROMPT (flat string, unchanged for development use)
# ═══════════════════════════════════════════════════════════════════════════════

def build_qg_prompt(
    chunk_text: str,
    topic: str,
    question_type: str,
    mastery_level: str,
    score_category: str,
) -> str:
    """Build the full question generation prompt (Ollama / flat string).

    Parameters
    ----------
    chunk_text :
        Source text from which the question must be derivable.
    topic :
        Topic tag for the content.
    question_type :
        Selected type ID (e.g. "1", "4a", "4d").
    mastery_level :
        Student's global mastery level.
    score_category :
        The per-topic score category.

    Returns
    -------
    str
        Complete prompt ready for Ollama LLM.
    """
    category_desc = score_category_description(score_category)

    return f"""\
You are an expert educational question writer for a personalized learning platform.

{QUESTION_TYPE_TAXONOMY}

TASK: Generate exactly ONE multiple-choice question of Type {question_type} for the topic "{topic}".

STUDENT CONTEXT:
- Global mastery level: {mastery_level}
- Topic score category: {score_category}
- {category_desc}

SOURCE CONTENT:
\"\"\"
{chunk_text}
\"\"\"

REQUIREMENTS:
1. The question MUST be of Type {question_type} as defined in the taxonomy above.
2. The question MUST be answerable from the source content.
3. The question must match the difficulty appropriate for a {mastery_level} student \
with {score_category} understanding of this topic.
4. Provide a clear, educational explanation for the correct answer.

Return ONLY valid JSON with no markdown fences:
{{
  "question": "The question text",
  "correct_answer": "The correct answer",
  "explanation": "Why this is correct and why other options would be wrong"
}}
"""


# ═══════════════════════════════════════════════════════════════════════════════
# DG — OLLAMA PROMPT (flat string, unchanged for development use)
# ═══════════════════════════════════════════════════════════════════════════════

def build_dg_prompt(
    question: str,
    correct_answer: str,
    question_type: str,
    topic: str,
    mastery_level: str,
    score_category: str,
    num_distractors: int = 3,
    chunk_text: str = "",
) -> str:
    """Build the distractor generation prompt (Ollama / flat string).

    Parameters
    ----------
    question :
        The generated question text.
    correct_answer :
        The correct answer.
    question_type :
        Type ID of the question.
    topic :
        Topic tag.
    mastery_level :
        Student's global mastery level.
    score_category :
        Per-topic score category.
    num_distractors :
        Number of wrong answers to generate (default 3).
    chunk_text :
        Source content for context.

    Returns
    -------
    str
        Complete prompt ready for Ollama LLM.
    """
    modifier = SCORE_CATEGORY_DISTRACTOR_MODIFIER.get(score_category, "standard")
    category_desc = score_category_description(score_category)

    modifier_instructions = {
        "keep_moderate": (
            "Make distractors clearly distinguishable from the correct answer. "
            "The student has very weak understanding and needs to build confidence. "
            "Each distractor should be obviously wrong to someone who has read the "
            "source material, but still related to the topic."
        ),
        "slightly_below_standard": (
            "Make distractors plausible but not subtle. They should test whether "
            "the student confuses related concepts, but a student who understands "
            "the basics should be able to eliminate them."
        ),
        "standard": (
            "Make distractors that match the expected difficulty for this mastery "
            "level. They should represent common alternative answers that a student "
            "at this level might consider."
        ),
        "push_to_ceiling": (
            "Make distractors as challenging as possible within the mastery ceiling. "
            "Each distractor should be subtle and require careful analysis to "
            "eliminate. Use answers that are partially correct or correct in a "
            "different context."
        ),
    }
    modifier_text = modifier_instructions.get(modifier, modifier_instructions["standard"])

    return f"""\
You are an expert at creating wrong-but-plausible answer options for educational MCQs.

QUESTION: {question}
CORRECT ANSWER: {correct_answer}
QUESTION TYPE: {question_type}
TOPIC: {topic}
STUDENT MASTERY: {mastery_level}
TOPIC SCORE CATEGORY: {score_category}

DIFFICULTY CALIBRATION:
{modifier_text}

{f'SOURCE CONTENT (for context):' if chunk_text else ''}
{f'"""{chunk_text[:500]}"""' if chunk_text else ''}

Generate exactly {num_distractors} wrong answers (distractors).

REQUIREMENTS:
1. Each distractor must be the same format/length as the correct answer.
2. Each distractor must be wrong but plausible — it should represent a real \
mistake a student might make.
3. No distractor should be obviously absurd or unrelated to the topic.
4. Distractors should not overlap with each other or with the correct answer.

Return ONLY valid JSON with no markdown fences:
{{
  "distractors": ["wrong answer 1", "wrong answer 2", "wrong answer 3"]
}}
"""


# ═══════════════════════════════════════════════════════════════════════════════
# QG — LLAMA CHAT PROMPT (for LoRA fine-tuned inference)
# ═══════════════════════════════════════════════════════════════════════════════

def build_qg_chat_prompt(
    chunk_text: str,
    topic: str,
    question_type: str,
    mastery_level: str,
    score_category: str,
) -> list[dict[str, str]]:
    """Build the QG prompt as a Llama chat message list.

    Returns a list of message dicts with ``role`` and ``content`` keys
    following the standard chat template format used by Llama 3.2 Instruct.
    The system message contains the taxonomy, role description, and output
    format specification.  The user message contains all conditioning fields.

    Parameters
    ----------
    chunk_text :
        Source text from which the question must be derivable.
    topic :
        Topic tag for the content.
    question_type :
        Selected type ID (e.g. "1", "4a", "4d").
    mastery_level :
        Student's global mastery level.
    score_category :
        The per-topic score category.

    Returns
    -------
    list[dict[str, str]]
        Chat-formatted messages ready for ``tokenizer.apply_chat_template``.
    """
    category_desc = score_category_description(score_category)

    system_content = f"""\
You are an expert educational MCQ question generator for a personalized learning platform.

{QUESTION_TYPE_TAXONOMY}

OUTPUT FORMAT — you must output exactly this structure and nothing else:
QUESTION: <the question text>
ANSWER: <the correct answer text>
EXPLANATION: <why this is correct>

Do not output anything other than the specified format above. No preamble, no JSON, no markdown."""

    user_content = f"""\
Generate a Type {question_type} question for topic "{topic}".

Mastery level: {mastery_level}
Score category: {score_category} — {category_desc}

Source content:
\"\"\"
{chunk_text}
\"\"\""""

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# DG — LLAMA CHAT PROMPT (for LoRA fine-tuned inference)
# ═══════════════════════════════════════════════════════════════════════════════

def build_dg_chat_prompt(
    question: str,
    correct_answer: str,
    question_type: str,
    topic: str,
    mastery_level: str,
    score_category: str,
    chunk_text: str = "",
) -> list[dict[str, str]]:
    """Build the DG prompt as a Llama chat message list.

    Each call produces a prompt that generates exactly ONE distractor.
    Call multiple times for multiple distractors.

    Returns
    -------
    list[dict[str, str]]
        Chat-formatted messages ready for ``tokenizer.apply_chat_template``.
    """
    modifier = SCORE_CATEGORY_DISTRACTOR_MODIFIER.get(score_category, "standard")
    category_desc = score_category_description(score_category)

    modifier_instructions = {
        "keep_moderate": "clearly distinguishable — student needs confidence",
        "slightly_below_standard": "plausible but not subtle — tests basic confusion",
        "standard": "matches expected difficulty for this mastery level",
        "push_to_ceiling": "as challenging as possible — subtle, partially correct",
    }
    modifier_text = modifier_instructions.get(modifier, modifier_instructions["standard"])

    system_content = """\
You are an expert at creating wrong-but-plausible answer options for educational MCQs.

OUTPUT FORMAT — you must output exactly one line and nothing else:
DISTRACTOR: <the distractor text>

Do not output anything other than the specified format above. No preamble, no JSON, no markdown."""

    context_block = ""
    if chunk_text:
        context_block = f'\n\nSource content:\n"""\n{chunk_text[:400]}\n"""'

    user_content = f"""\
Question: {question}
Correct answer: {correct_answer}
Question type: Type {question_type}
Topic: {topic}
Mastery: {mastery_level}
Score category: {score_category} — {category_desc}
Difficulty: {modifier_text}{context_block}

Generate one wrong-but-plausible distractor. It must be the same format/length \
as the correct answer, wrong but not absurd, and different from the correct answer."""

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# CHAT TEMPLATE FORMATTING (for training and inference)
# ═══════════════════════════════════════════════════════════════════════════════

def format_chat_for_training(messages: list[dict[str, str]], tokenizer) -> str:
    """Apply the Llama tokenizer's chat template to a messages list.

    Parameters
    ----------
    messages :
        List of message dicts with ``role`` and ``content`` keys.
    tokenizer :
        The Llama tokenizer (must support ``apply_chat_template``).

    Returns
    -------
    str
        Formatted string ready for training or inference input.
    """
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# OUTPUT PARSERS (for LoRA model structured output)
# ═══════════════════════════════════════════════════════════════════════════════

def extract_qg_output(raw_output: str) -> dict | None:
    """Parse the model's raw text output for QG.

    Extracts QUESTION, ANSWER, and EXPLANATION fields from the structured
    output format.  Handles extra whitespace, missing fields, partial output.

    Parameters
    ----------
    raw_output :
        Raw decoded text from the model (assistant turn only).

    Returns
    -------
    dict or None
        Dict with keys ``question``, ``correct_answer``, ``explanation``,
        or None if parsing fails.
    """
    if not raw_output or not raw_output.strip():
        return None

    text = raw_output.strip()

    # Try structured field extraction
    question_match = re.search(
        r"QUESTION:\s*(.+?)(?=\nANSWER:|\Z)", text, re.DOTALL,
    )
    answer_match = re.search(
        r"ANSWER:\s*(.+?)(?=\nEXPLANATION:|\Z)", text, re.DOTALL,
    )
    explanation_match = re.search(
        r"EXPLANATION:\s*(.+)", text, re.DOTALL,
    )

    if question_match and answer_match:
        question = question_match.group(1).strip()
        answer = answer_match.group(1).strip()
        explanation = ""
        if explanation_match:
            explanation = explanation_match.group(1).strip()

        if question and answer:
            return {
                "question": question,
                "correct_answer": answer,
                "explanation": explanation,
            }

    return None


def extract_dg_output(raw_output: str) -> str | None:
    """Parse the model's raw text output for DG.

    Extracts the DISTRACTOR field from the structured output format.

    Parameters
    ----------
    raw_output :
        Raw decoded text from the model (assistant turn only).

    Returns
    -------
    str or None
        The distractor string, or None if parsing fails.
    """
    if not raw_output or not raw_output.strip():
        return None

    text = raw_output.strip()

    # Try structured field extraction
    match = re.search(r"DISTRACTOR:\s*(.+)", text, re.DOTALL)
    if match:
        distractor = match.group(1).strip()
        # Take only the first line if model produced extra text
        distractor = distractor.split("\n")[0].strip()
        if distractor:
            return distractor

    # Fallback: if the output is a single line without the prefix, use it directly
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) == 1 and not lines[0].startswith(("QUESTION:", "ANSWER:", "EXPLANATION:")):
        return lines[0]

    return None
