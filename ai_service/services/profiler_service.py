"""
Profiler Service — LLM-powered session analysis and emotion fusion.

Uses Groq (llama-3.1-8b-instant) for:
  • Cross-session profile rewriting (persistent student profile)
  • Real-time emotion fusion when FER and SER conflict
"""

import os
import re
import json
import logging
from typing import Optional
from pathlib import Path
from schemas.student_context import UnifiedStudentContext
from dotenv import load_dotenv
from groq import Groq

# Search for .env
_this_dir = Path(__file__).resolve().parent
for _candidate in [
    _this_dir / ".env",
    _this_dir.parent / ".env",
    _this_dir.parent.parent / ".env",
]:
    if _candidate.exists():
        load_dotenv(_candidate)
        break
else:
    load_dotenv()

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.1-8b-instant"


def _get_groq_client() -> Groq:
    """Create a Groq client (reuses the same API key as coding/evaluator)."""
    return Groq(api_key=GROQ_API_KEY)


def _clean_llm_json(text: str) -> str:
    """
    Strip markdown fences, leading/trailing whitespace, and any non-JSON
    text the LLM may have wrapped around the JSON object.
    """
    text = text.strip()

    # Remove ```json ... ``` or ``` ... ``` fences
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    # If there's text before the first '{', strip it
    first_brace = text.find("{")
    if first_brace > 0:
        text = text[first_brace:]

    # If there's text after the last '}', strip it
    last_brace = text.rfind("}")
    if last_brace >= 0 and last_brace < len(text) - 1:
        text = text[: last_brace + 1]

    return text


def _parse_llm_json(text: str, context: str = "LLM") -> dict:
    """
    Parse LLM output as JSON with robust cleanup and logging on failure.
    """
    cleaned = _clean_llm_json(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(
            f"[{context}] JSON parse failed: {e}\n"
            f"--- RAW LLM OUTPUT START ---\n{text}\n--- RAW LLM OUTPUT END ---\n"
            f"--- CLEANED TEXT START ---\n{cleaned}\n--- CLEANED TEXT END ---"
        )
        raise


# ── Cross-session profile rewriter (System B) ───────────────────

PROFILE_REWRITER_SYSTEM = """\
You are an educational psychologist AI that maintains a concise, evolving profile of a student's learning style and emotional patterns.

You will receive:
1. The student's existing profile (may be empty if this is their first session)
2. A timestamped log of the student's emotional states and spoken intentions during a new lesson, correlated with slides and subtopics

Your job is to synthesize the existing profile with the new session's data and produce an UPDATED profile.
The updated profile must be a REWRITE — not an append. It should be compact and useful.
Prioritize patterns that appear across multiple sessions. Let single-session signals inform but not dominate.

Return a raw JSON object only. No markdown. No backticks. No explanation. No text before or after the JSON.

The JSON must have exactly these fields:
{
  "profile_summary": "A single concise paragraph (max 5 sentences) written as a note from one teacher to another describing how to teach this student effectively.",
  "profile_data": {
    "learning_style_signals": ["list of observed learning preferences"],
    "engagement_patterns": { "high": ["contexts where student is most engaged"], "low": ["contexts where student disengages"] },
    "emotional_tendencies": { "description": "...", "notable_patterns": [] },
    "notable_intentions": ["list of requested adjustments like pace preferences, off-topic frequency, etc."],
    "recommended_approaches": ["specific teaching strategies that work for this student"],
    "topics_of_difficulty": ["concepts or styles the student struggles with"],
    "topics_of_strength": ["concepts or styles the student grasps easily"]
  }
}
"""


async def update_profile(
    student_id: int,
    lesson_title: str,
    session_log: list[dict],
    existing_profile_summary: str = "",
    existing_profile_data: dict | None = None,
    student_context: Optional[UnifiedStudentContext] = None,
) -> dict:
    """
    Rewrite the student's persistent learning profile by synthesizing
    the existing profile with new session data.

    Returns { profile_summary: str, profile_data: dict }.
    """
    if not GROQ_API_KEY:
        logger.warning("GROQ_API_KEY not set — returning empty profile update")
        return {
            "profile_summary": existing_profile_summary or "No profile yet.",
            "profile_data": existing_profile_data or _empty_profile_data(),
        }

    existing_data_str = json.dumps(existing_profile_data or {}, indent=2)
    
    context_str = ""
    if student_context:
        context_str = (
            f"STUDENT CONTEXT (Global):\n"
            f"Mastery Level: {student_context.profile.mastery_level}\n"
            f"Language Proficiency: {student_context.profile.language_proficiency}\n"
            f"Strengths: {', '.join(student_context.profile.strengths) if student_context.profile.strengths else 'None recorded'}\n"
            f"Weaknesses: {', '.join(student_context.profile.weaknesses) if student_context.profile.weaknesses else 'None recorded'}\n"
            f"Incorrectly Answered: {', '.join(student_context.profile.incorrectly_answered) if student_context.profile.incorrectly_answered else 'None recorded'}\n\n"
        )

    user_prompt = (
        f"Student ID: {student_id}\n"
        f"{context_str}"
        f"Lesson just completed: {lesson_title}\n\n"
        f"EXISTING PROFILE SUMMARY:\n"
        f"{existing_profile_summary or '(first session — no existing profile)'}\n\n"
        f"EXISTING PROFILE DATA:\n"
        f"{existing_data_str}\n\n"
        f"NEW SESSION EMOTION LOG ({len(session_log)} events):\n"
        f"{json.dumps(session_log, indent=2)}"
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": PROFILE_REWRITER_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_tokens=1024,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content.strip()
        result = _parse_llm_json(text, context="ProfileRewriter")

        # Validate expected keys
        if "profile_summary" not in result:
            result["profile_summary"] = existing_profile_summary or ""
        if "profile_data" not in result:
            result["profile_data"] = existing_profile_data or _empty_profile_data()

        return result
    except json.JSONDecodeError:
        return {
            "profile_summary": existing_profile_summary or "Profile update failed — LLM returned invalid JSON.",
            "profile_data": existing_profile_data or _empty_profile_data(),
        }
    except Exception as e:
        logger.error(f"Profile rewriter failed: {e}")
        raise


def _empty_profile_data() -> dict:
    """Return the default empty profile_data structure."""
    return {
        "learning_style_signals": [],
        "engagement_patterns": {"high": [], "low": []},
        "emotional_tendencies": {"description": "", "notable_patterns": []},
        "recommended_approaches": [],
        "topics_of_difficulty": [],
        "topics_of_strength": [],
    }


# ── Emotion fusion ───────────────────────────────────────────────

FUSION_SYSTEM = """\
You are an emotion analysis expert. Given facial expression recognition (FER) and speech emotion recognition (SER) results for the same moment, determine the student's true emotional state.

Return a raw JSON object only. No markdown. No backticks. No explanation. No text before or after the JSON.

The JSON must have exactly these fields: { "fused_emotion": "<emotion>", "reasoning": "<one sentence>" }
"""


async def fuse_emotions(
    fer_emotion: str,
    fer_confidence: float,
    ser_emotion: str,
    ser_confidence: float,
    slide_index: int = 0,
    slide_title: str = "",
    subtopic: str = "",
) -> dict:
    """
    Use Groq LLM to resolve conflicting FER and SER emotions.
    Returns { fused_emotion, reasoning }.
    """
    if not GROQ_API_KEY:
        # Fallback: higher confidence wins
        if fer_confidence >= ser_confidence:
            return {"fused_emotion": fer_emotion, "reasoning": "No API key — used FER (higher confidence)"}
        return {"fused_emotion": ser_emotion, "reasoning": "No API key — used SER (higher confidence)"}

    user_prompt = (
        f"FER detected: {fer_emotion} (confidence: {fer_confidence:.2f})\n"
        f"SER detected: {ser_emotion} (confidence: {ser_confidence:.2f})\n"
        f"Context: student is watching slide {slide_index}"
    )
    if slide_title:
        user_prompt += f' titled "{slide_title}"'
    if subtopic:
        user_prompt += f' during a lesson on "{subtopic}"'
    user_prompt += ".\nWhich emotion better represents the student's true state?"

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": FUSION_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=128,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content.strip()
        return _parse_llm_json(text, context="EmotionFusion")
    except json.JSONDecodeError:
        logger.warning("Emotion fusion: JSON parse failed, falling back to confidence")
        if fer_confidence >= ser_confidence:
            return {"fused_emotion": fer_emotion, "reasoning": "LLM returned invalid JSON — used FER (higher confidence)"}
        return {"fused_emotion": ser_emotion, "reasoning": "LLM returned invalid JSON — used SER (higher confidence)"}
    except Exception as e:
        logger.warning(f"Emotion fusion LLM failed, falling back to confidence: {e}")
        if fer_confidence >= ser_confidence:
            return {"fused_emotion": fer_emotion, "reasoning": "LLM failed — used FER (higher confidence)"}
        return {"fused_emotion": ser_emotion, "reasoning": "LLM failed — used SER (higher confidence)"}
