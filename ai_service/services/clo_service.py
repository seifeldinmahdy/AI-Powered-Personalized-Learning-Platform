"""
CLO (Course Learning Outcome) AI-assisted authoring service.

Given a course outline and available concepts, generates 4-8 draft CLOs
using Bloom's taxonomy action verbs. Returns strict JSON; never persists.
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
from schemas.clos import CLODraft, CLOSuggestRequest, CLOSuggestResponse

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
            timeout=120,
        )
    return _ollama_client


CLO_SYSTEM = """\
You are a curriculum design expert. Given a course outline, generate 4 to 8 Course Learning Outcomes (CLOs).

BLOOM'S TAXONOMY ACTION VERBS:
- Remember: define, list, recall, recognize, state
- Understand: describe, explain, summarize, interpret, classify
- Apply: apply, demonstrate, implement, solve, use
- Analyze: analyze, compare, differentiate, examine, break down
- Evaluate: evaluate, critique, justify, assess, argue
- Create: design, construct, develop, compose, formulate

OUTPUT RULES:
- Each CLO must start with a strong action verb from the appropriate Bloom level.
- CLOs should be measurable, specific, and achievable by course end.
- Map each CLO to the most relevant concept IDs from AVAILABLE CONCEPTS (use the "id" strings exactly).
- Generate 4–8 CLOs, covering a range of Bloom levels (at least Remember, Understand, Apply).
- Return ONLY a valid JSON object with key "drafts" containing an array. No markdown, no preamble.

JSON Schema for each draft:
{
  "code": "CLO1",          // sequential, e.g. CLO1, CLO2, ...
  "text": "...",           // full outcome statement starting with action verb
  "bloom_level": "...",    // one of: remember, understand, apply, analyze, evaluate, create
  "concept_ids": ["..."],  // list of concept ID strings from AVAILABLE CONCEPTS
  "order": 1               // sequential ordering integer
}
"""


async def suggest_clos(request: CLOSuggestRequest) -> CLOSuggestResponse:
    """Generate draft CLOs for a course using the strong LLM model."""
    outline_text = json.dumps(request.outline, indent=2)
    concepts_text = json.dumps(request.existing_concepts, indent=2)

    user_prompt = f"""COURSE TITLE: {request.course_title}

COURSE OUTLINE:
{outline_text}

AVAILABLE CONCEPTS (use these IDs in concept_ids):
{concepts_text}

Generate 4–8 CLOs for this course. Return JSON with key "drafts" containing the array."""

    client = _get_client()
    try:
        raw = client.chat_json(
            messages=[
                {"role": "system", "content": CLO_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            timeout_override=90,
        )
    except Exception as e:
        logger.error("CLO generation failed: %s", e)
        raise RuntimeError(f"CLO generation failed: {e}")

    # Parse response
    if isinstance(raw, dict) and "drafts" in raw:
        drafts_raw = raw["drafts"]
    elif isinstance(raw, list):
        drafts_raw = raw
    else:
        raise RuntimeError(f"Unexpected CLO response format: {type(raw)}")

    drafts = []
    for i, d in enumerate(drafts_raw):
        if not isinstance(d, dict):
            continue
        try:
            # Ensure code is set
            if not d.get("code"):
                d["code"] = f"CLO{i + 1}"
            # Ensure order
            if "order" not in d:
                d["order"] = i + 1
            # Coerce concept_ids to list of strings
            d["concept_ids"] = [str(c) for c in (d.get("concept_ids") or [])]
            drafts.append(CLODraft(**d))
        except Exception as parse_err:
            logger.warning("Skipping malformed CLO draft: %s — %s", d, parse_err)

    if not drafts:
        raise RuntimeError("CLO generation produced 0 valid drafts")

    logger.info("Generated %d CLO drafts for course: %s", len(drafts), request.course_title)
    return CLOSuggestResponse(drafts=drafts)
