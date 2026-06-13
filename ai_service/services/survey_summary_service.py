"""
Post-course survey AI summarization service.

Aggregates text responses and Likert distributions to produce
a structured summary. NEVER quotes individual students.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_pathway_src = str(Path(__file__).resolve().parent.parent.parent / "course_pathway" / "src")
if _pathway_src not in sys.path:
    sys.path.insert(0, _pathway_src)

from pathway.llm.naming import OllamaClient  # type: ignore
from schemas.surveys import SurveySummarizeRequest, SurveySummaryResult

logger = logging.getLogger(__name__)

_ollama_client: OllamaClient | None = None


def _get_client() -> OllamaClient:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient(
            host=os.getenv("OLLAMA_HOST", "https://ollama.com"),
            model=os.getenv("OLLAMA_STRONG_MODEL", "gpt-oss:120b"),
            api_key=os.getenv("OLLAMA_API_KEY", ""),
            max_retries=3,
            timeout=180,
        )
    return _ollama_client


SURVEY_SYSTEM = """\
You are an educational research analyst summarizing student course feedback.

CRITICAL RULES:
- NEVER quote or paraphrase a specific student's response verbatim.
- Only describe AGGREGATE patterns — themes that appear in multiple responses.
- Do not invent or inflate data. If there is not enough text to identify a theme, say so.
- Output ONLY a valid JSON object matching the schema below. No markdown, no preamble.

JSON Schema:
{
  "recurring_themes": [          // top themes mentioned by multiple students
    {"theme": "string", "count": integer}
  ],
  "sentiment": "positive|mixed|negative",
  "top_praise": ["string", ...],        // 2-4 most common positive observations
  "top_complaints": ["string", ...],    // 2-4 most common concerns/complaints
  "per_clo_perception": {               // for each CLO label, one sentence on student perception
    "CLO text here": "perception sentence"
  }
}
"""


async def summarize_survey(request: SurveySummarizeRequest) -> SurveySummaryResult:
    """Summarize aggregate survey data using the strong LLM model."""
    if not request.text_answers and not request.likert_distributions:
        return SurveySummaryResult(
            recurring_themes=[],
            sentiment="mixed",
            top_praise=["Insufficient responses to generate summary."],
            top_complaints=[],
            per_clo_perception={},
        )

    # Build Likert summary text
    likert_text = ""
    for q_prompt, dist in request.likert_distributions.items():
        total = sum(dist.values())
        if total == 0:
            continue
        avg = sum(int(k) * v for k, v in dist.items()) / total
        likert_text += f"\n- {q_prompt}: average {avg:.1f}/5 (n={total})"

    # Truncate text answers to avoid token overflow (cap at 200 responses, 300 chars each)
    capped_texts = [t[:300] for t in request.text_answers[:200]]

    user_prompt = f"""COURSE ID: {request.course_id}

COURSE LEARNING OUTCOMES (CLOs):
{json.dumps(request.clo_labels, indent=2) if request.clo_labels else "None provided"}

LIKERT SCALE RESULTS (aggregate distributions):
{likert_text or "No Likert data"}

FREE-TEXT RESPONSES ({len(capped_texts)} responses — do NOT quote any single response):
{chr(10).join(f"- {t}" for t in capped_texts) if capped_texts else "No text responses"}

Analyze all of the above and produce the JSON summary."""

    client = _get_client()
    try:
        raw = client.chat_json(
            messages=[
                {"role": "system", "content": SURVEY_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            timeout_override=120,
        )
    except Exception as e:
        logger.error("Survey summarization failed: %s", e)
        return SurveySummaryResult(
            recurring_themes=[],
            sentiment="mixed",
            top_praise=[],
            top_complaints=[f"Summarization failed: {str(e)[:100]}"],
            per_clo_perception={},
        )

    try:
        return SurveySummaryResult(
            recurring_themes=raw.get("recurring_themes", []),
            sentiment=raw.get("sentiment", "mixed"),
            top_praise=raw.get("top_praise", []),
            top_complaints=raw.get("top_complaints", []),
            per_clo_perception=raw.get("per_clo_perception", {}),
        )
    except Exception as parse_err:
        logger.warning("Could not parse survey summary response: %s", parse_err)
        return SurveySummaryResult(
            recurring_themes=[],
            sentiment="mixed",
            top_praise=[],
            top_complaints=["Summary parsing failed."],
            per_clo_perception={},
        )
