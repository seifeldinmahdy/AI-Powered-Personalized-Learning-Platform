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
            host=os.getenv("OLLAMA_HOST"),
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
- Generate 4–8 CLOs, covering a range of Bloom levels (at least Remember, Understand, Apply).
- Generate 4-8 core concepts from the course outline.
- Map each CLO to the most relevant concepts (use the generated concept strings directly).
- Return ONLY a valid JSON object. No markdown, no preamble.

JSON Schema:
{
  "suggested_concepts": ["concept 1", "concept 2", ...], // list of newly generated core concepts
  "drafts": [
    {
      "code": "CLO1",          // sequential, e.g. CLO1, CLO2, ...
      "text": "...",           // full outcome statement starting with action verb
      "bloom_level": "...",    // one of: remember, understand, apply, analyze, evaluate, create
      "concept_ids": ["..."],  // list of concept ID strings or concept labels
      "order": 1               // sequential ordering integer
    }
  ]
}
"""


async def suggest_clos(request: CLOSuggestRequest) -> CLOSuggestResponse:
    """Generate draft CLOs for a course using the strong LLM model."""
    outline_text = json.dumps(request.outline, indent=2)
    concepts_text = json.dumps(request.existing_concepts, indent=2)

    if request.existing_concepts:
        user_prompt = f"""COURSE TITLE: {request.course_title}

COURSE OUTLINE:
{outline_text}

AVAILABLE CONCEPTS (use these exact IDs in concept_ids):
{concepts_text}

Generate 4–8 CLOs for this course. Map the CLOs ONLY to the provided AVAILABLE CONCEPTS.
Return JSON with keys "suggested_concepts" (empty array) and "drafts" containing the array."""
    else:
        user_prompt = f"""COURSE TITLE: {request.course_title}

COURSE OUTLINE:
{outline_text}

There are no existing concepts. Please generate 4-8 core concepts from the course outline.
Return JSON with keys "suggested_concepts" containing the generated concepts, and "drafts" containing the CLO drafts mapped to those new concepts."""

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
        suggested_concepts = raw.get("suggested_concepts", [])
    elif isinstance(raw, list):
        drafts_raw = raw
        suggested_concepts = []
    else:
        raise RuntimeError(f"Unexpected CLO response format: {type(raw)}")

    # Build valid concept ID set for validation
    valid_concept_ids = {str(c["id"]) for c in request.existing_concepts}

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
            raw_ids = [str(c) for c in (d.get("concept_ids") or [])]
            if request.existing_concepts:
                # If using existing concepts, filter to valid IDs only
                d["concept_ids"] = [cid for cid in raw_ids if cid in valid_concept_ids]
            else:
                # If generating new concepts, keep the raw labels as "concept_ids"
                d["concept_ids"] = raw_ids
            drafts.append(CLODraft(**d))
        except Exception as parse_err:
            logger.warning("Skipping malformed CLO draft: %s — %s", d, parse_err)

    if not drafts:
        raise RuntimeError("CLO generation produced 0 valid drafts")

    # Auto-assign concepts to drafts that have no concept_ids.
    # Uses fuzzy text matching between CLO text and concept labels.
    if request.existing_concepts:
        _auto_assign_concepts(drafts, request.existing_concepts)

    logger.info("Generated %d CLO drafts for course: %s", len(drafts), request.course_title)
    return CLOSuggestResponse(drafts=drafts, suggested_concepts=suggested_concepts)


def _auto_assign_concepts(
    drafts: list[CLODraft],
    existing_concepts: list[dict],
) -> None:
    """Assign concepts to any draft with empty concept_ids using text similarity.

    Each CLO should map to 1-3 of the most relevant concepts. Concepts already
    assigned by the LLM are kept; this only fills in empty ones.
    """
    from difflib import SequenceMatcher
    import re

    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9 ]", " ", s.lower()).strip()

    concept_labels = [(str(c["id"]), _norm(c["label"])) for c in existing_concepts]

    for draft in drafts:
        if draft.concept_ids:
            continue  # LLM already assigned concepts

        clo_text = _norm(draft.text)
        scores: list[tuple[str, float]] = []
        for cid, label in concept_labels:
            ratio = SequenceMatcher(None, clo_text, label).ratio()
            # Bonus for keyword overlap
            clo_words = set(clo_text.split())
            label_words = set(label.split())
            overlap = len(clo_words & label_words) / max(len(label_words), 1)
            score = 0.5 * ratio + 0.5 * overlap
            scores.append((cid, score))

        # Assign top 1-3 concepts with score > 0.15
        scores.sort(key=lambda x: -x[1])
        assigned = [cid for cid, s in scores[:3] if s > 0.15]
        if not assigned and scores:
            # At minimum assign the single best match
            assigned = [scores[0][0]]
        draft.concept_ids = assigned

