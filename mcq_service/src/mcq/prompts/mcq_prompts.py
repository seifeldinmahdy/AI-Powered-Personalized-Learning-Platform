"""Prompt templates for question generation (QG) and distractor generation (DG).

All prompts inject QUESTION_TYPE_TAXONOMY and scoring category descriptions
to ensure the LLM (or fine-tuned T5 model reading the same prefix) produces
correctly typed questions.
"""

from __future__ import annotations

from mcq.question_types import (
    QUESTION_TYPE_TAXONOMY,
    SCORE_CATEGORY_DISTRACTOR_MODIFIER,
)
from mcq.scoring_categories import score_category_description


# ═══════════════════════════════════════════════════════════════════════════════
# QUESTION GENERATION PROMPT
# ═══════════════════════════════════════════════════════════════════════════════

def build_qg_prompt(
    chunk_text: str,
    topic: str,
    question_type: str,
    mastery_level: str,
    score_category: str,
) -> str:
    """Build the full question generation prompt.

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
        Complete prompt ready for LLM or T5 input.
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
# DISTRACTOR GENERATION PROMPT
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
    """Build the distractor generation prompt.

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
        Complete prompt ready for LLM or T5 input.
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
# T5 INPUT FORMATTING
# ═══════════════════════════════════════════════════════════════════════════════

def build_qg_t5_input(
    chunk_text: str,
    topic: str,
    question_type: str,
    mastery_level: str,
    score_category: str,
) -> str:
    """Build the T5 input string for fine-tuned question generation.

    Uses a structured prefix format that the T5 model was trained on.

    Returns
    -------
    str
        T5 input string.
    """
    return (
        f"generate question: type={question_type} topic={topic} "
        f"mastery={mastery_level} score_category={score_category} "
        f"context: {chunk_text}"
    )


def build_dg_t5_input(
    question: str,
    correct_answer: str,
    question_type: str,
    topic: str,
    mastery_level: str,
    score_category: str,
) -> str:
    """Build the T5 input string for fine-tuned distractor generation.

    Returns
    -------
    str
        T5 input string.
    """
    return (
        f"generate distractors: type={question_type} topic={topic} "
        f"mastery={mastery_level} score_category={score_category} "
        f"question: {question} answer: {correct_answer}"
    )
