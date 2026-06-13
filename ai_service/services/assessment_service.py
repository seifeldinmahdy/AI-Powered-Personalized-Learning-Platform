"""
Assessment Service — LLM-powered placement test question generation.

Uses the existing OllamaClient (from pathway.llm.naming) with gpt-oss:120b
for generating topic-tagged MCQ questions, grouped by category.
"""

import os
import sys
import json
import logging
from pathlib import Path

# Ensure course_pathway/src is on sys.path for OllamaClient import
_pathway_src = str(Path(__file__).resolve().parent.parent.parent / "course_pathway" / "src")
if _pathway_src not in sys.path:
    sys.path.insert(0, _pathway_src)

from pathway.llm.naming import OllamaClient  # type: ignore

logger = logging.getLogger(__name__)

_client: OllamaClient | None = None


def _get_ollama_client() -> OllamaClient:
    """Lazy-initialise the OllamaClient singleton."""
    global _client
    if _client is None:
        _client = OllamaClient(
            host=os.getenv("OLLAMA_HOST", "https://ollama.com"),
            model=os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
            api_key=os.getenv("OLLAMA_API_KEY", ""),
            max_retries=3,
            timeout=120,
        )
    return _client


async def generate_assessment_questions(course_title: str, num_questions: int = 6) -> dict:
    """Generate placement-test MCQs with topic tagging (flat, ungrouped).

    Each question includes a ``topic`` field identifying the knowledge area
    it tests, enabling per-topic scoring in the placement flow.

    Returns
    -------
    dict
        ``{"questions": [{"question": str, "options": [...], "correct_answer": str, "topic": str}]}``
    """
    prompt = f"""Generate exactly {num_questions} multiple choice questions to assess a student's prior knowledge of "{course_title}".

Return ONLY a valid JSON object with no markdown fences, no extra text, in this exact format:
{{
  "questions": [
    {{
      "question": "Question text here?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_answer": "Option A",
      "topic": "Topic Name"
    }}
  ]
}}

Requirements:
- Each question must have exactly 4 options
- The correct_answer must match one of the options exactly
- Each question must have a "topic" field identifying the specific knowledge area it tests (e.g. "Variables", "Loops", "Data Structures")
- Questions should vary in difficulty (beginner to intermediate)
- Questions should test conceptual understanding, not trivia
- Topics should cover different areas of {course_title}"""

    client = _get_ollama_client()

    try:
        data = client.chat_json(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            timeout_override=120,
        )

        if "questions" not in data or not isinstance(data["questions"], list):
            raise ValueError("Missing or invalid 'questions' key")
        return data
    except json.JSONDecodeError as e:
        logger.error("Failed to parse assessment JSON: %s", e)
        raise ValueError(f"LLM returned invalid JSON: {e}")
    except Exception as e:
        logger.error("Assessment generation failed: %s", e)
        raise ValueError(f"Assessment generation failed: {e}")


async def generate_categorized_questions(
    course_title: str,
    categories: list[dict],
    questions_per_category: int = 2,
) -> list[dict]:
    """Generate MCQs grouped by pre-defined categories.

    All category question-generation calls are made **concurrently** via
    ``asyncio.gather`` to minimise total wall-clock time.

    Parameters
    ----------
    course_title : str
        The course name for context.
    categories : list[dict]
        Each dict has ``name``, ``description``, ``topics``.
    questions_per_category : int
        Number of questions to generate per category.

    Returns
    -------
    list[dict]
        Each dict: ``{"name": str, "description": str, "questions": [...]}``
    """
    import asyncio

    client = _get_ollama_client()

    async def _generate_for_category(cat: dict) -> dict:
        topic_list = ", ".join(cat.get("topics", [cat["name"]]))
        n = questions_per_category

        prompt = f"""Generate exactly {n} multiple choice questions to assess a student's knowledge in the category "{cat['name']}" for the course "{course_title}".

The questions should cover these specific topics: {topic_list}

Return ONLY a valid JSON object with no markdown fences:
{{
  "questions": [
    {{
      "question": "Question text?",
      "options": ["A", "B", "C", "D"],
      "correct_answer": "A",
      "topic": "Specific Topic"
    }}
  ]
}}

Requirements:
- Each question must have exactly 4 options
- The correct_answer must match one of the options exactly
- Each question must have a "topic" field from the topics listed above
- Questions should vary in difficulty
- Questions should test conceptual understanding"""

        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None,
                lambda: client.chat_json(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    timeout_override=180,
                ),
            )
            qs = data.get("questions", [])
        except Exception as e:
            logger.error("Failed to generate questions for category '%s': %s", cat["name"], e)
            qs = []

        return {
            "name": cat["name"],
            "description": cat.get("description", ""),
            "questions": qs,
        }

    # Fire all category question-generation calls concurrently
    results = await asyncio.gather(
        *[_generate_for_category(cat) for cat in categories]
    )
    return list(results)


async def generate_clo_questions(
    course_title: str,
    plan: list[dict],
    total_questions: int = 12,
) -> list[dict]:
    """Backward-designed placement generation: probe the CLO concept set.

    For each CLO group, generate questions covering its concepts such that
    EVERY concept is probed by at least one question, and every question is
    tagged with the exact ``concept_id`` it measures (so the submission path is
    concept-keyed). This replaces topic-discovery generation.

    Parameters
    ----------
    plan :
        Output of ``category_service.build_clo_assessment_plan`` —
        ``[{name, description, clo_code, concepts: [{id, label}]}]``.
    total_questions :
        Target total; distributed across concepts but never below one-per-concept
        (coverage guarantee).

    Returns
    -------
    list[dict]
        ``[{name, description, questions: [{question, options, correct_answer,
        topic, concept_id}]}]`` grouped by CLO.
    """
    import asyncio

    client = _get_ollama_client()

    total_concepts = sum(len(g["concepts"]) for g in plan) or 1
    per_concept = max(1, total_questions // total_concepts)

    async def _generate_for_group(group: dict) -> dict:
        concepts = group["concepts"]
        concept_lines = "\n".join(f'- id="{c["id"]}" label="{c["label"]}"' for c in concepts)
        n_each = per_concept

        prompt = f"""Generate placement-test multiple choice questions for the course "{course_title}".

These questions assess the learning outcome "{group['name']}": {group.get('description', '')}

Cover EACH of the following concepts with at least {n_each} question(s). Every question MUST be tagged with the exact concept_id it measures.

CONCEPTS:
{concept_lines}

Return ONLY valid JSON with no markdown fences:
{{
  "questions": [
    {{
      "question": "Question text?",
      "options": ["A", "B", "C", "D"],
      "correct_answer": "A",
      "concept_id": "<one of the ids above>",
      "topic": "<the matching concept label>"
    }}
  ]
}}

Requirements:
- Every concept id above appears on at least one question (no concept skipped).
- Each question has exactly 4 options; correct_answer matches one option exactly.
- concept_id MUST be one of the ids listed above.
- Test conceptual understanding, not trivia."""

        valid_ids = {c["id"] for c in concepts}
        label_by_id = {c["id"]: c["label"] for c in concepts}
        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(
                None,
                lambda: client.chat_json(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    timeout_override=180,
                ),
            )
            qs = data.get("questions", [])
        except Exception as e:
            logger.error("CLO question generation failed for '%s': %s", group["name"], e)
            qs = []

        # Keep only questions tagged with a real concept id from this group.
        cleaned = []
        covered: set[str] = set()
        for q in qs:
            cid = str(q.get("concept_id", ""))
            if cid in valid_ids:
                q["concept_id"] = cid
                q.setdefault("topic", label_by_id.get(cid, ""))
                cleaned.append(q)
                covered.add(cid)

        # Coverage guarantee: synthesize a minimal probe for any uncovered concept
        # so every CLO concept is measured even if the LLM skipped it.
        for c in concepts:
            if c["id"] not in covered:
                logger.warning(
                    "CLO gen: concept %s (%s) uncovered by LLM — adding fallback probe",
                    c["id"], c["label"],
                )
                cleaned.append({
                    "question": f"Which best describes the concept \"{c['label']}\"?",
                    "options": [
                        f"A correct understanding of {c['label']}",
                        "An unrelated definition",
                        "A partially correct but flawed statement",
                        "None of the above",
                    ],
                    "correct_answer": f"A correct understanding of {c['label']}",
                    "concept_id": c["id"],
                    "topic": c["label"],
                })

        return {
            "name": group["name"],
            "description": group.get("description", ""),
            "questions": cleaned,
        }

    results = await asyncio.gather(*[_generate_for_group(g) for g in plan])
    return list(results)

