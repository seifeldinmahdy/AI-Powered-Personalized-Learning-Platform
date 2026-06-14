import os
import sys
import json
import hashlib
import logging
from collections import OrderedDict
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# ── OllamaClient (shared LLM backend) ──
_pathway_src = str(Path(__file__).resolve().parent.parent.parent / "course_pathway" / "src")
if _pathway_src not in sys.path:
    sys.path.insert(0, _pathway_src)

try:
    from pathway.llm.naming import OllamaClient  # type: ignore
    _ollama_available = True
except Exception:
    _ollama_available = False

try:
    from groq import Groq as GroqClient
    _groq_client = GroqClient(api_key=os.getenv("GROQ_API_KEY", ""))
    _GROQ_MODEL = os.getenv("GROQ_MODEL_CODING", "qwen/qwen3-32b")
    _GROQ_FALLBACK = "llama-3.3-70b-versatile"
except Exception:
    _groq_client = None

logger = logging.getLogger(__name__)

_ollama_client = None

def _get_ollama_client():
    global _ollama_client
    if not _ollama_available:
        return None
    if _ollama_client is None:
        try:
            _ollama_client = OllamaClient(
                host=os.getenv("OLLAMA_HOST", "https://ollama.com"),
                model=os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
                api_key=os.getenv("OLLAMA_API_KEY", ""),
                max_retries=3,
                timeout=120,
            )
        except Exception as e:
            logger.warning(f"OllamaClient init failed: {e}")
            return None
    return _ollama_client


def _chat_json(messages: list, temperature: float = 0.3) -> dict:
    """Try Ollama first, fall back to Groq on any failure."""
    client = _get_ollama_client()
    if client is not None:
        try:
            return client.chat_json(messages=messages, temperature=temperature, timeout_override=120)
        except Exception as e:
            logger.warning(f"Ollama failed in rubric_service: {e}. Falling back to Groq.")

    if _groq_client is None:
        raise RuntimeError("No LLM backend available (Ollama and Groq both unavailable)")

    for model in [_GROQ_MODEL, _GROQ_FALLBACK]:
        try:
            completion = _groq_client.chat.completions.create(
                messages=messages,
                model=model,
                response_format={"type": "json_object"},
                temperature=temperature,
            )
            return json.loads(completion.choices[0].message.content)
        except Exception as e:
            if model == _GROQ_FALLBACK:
                raise
            logger.warning(f"Groq model {model} failed: {e}. Trying fallback.")


# In-process LRU cache keyed by question hash (max 200 entries)
_rubric_cache: OrderedDict = OrderedDict()
_CACHE_MAX = 200


def _cache_key(question: str) -> str:
    return hashlib.sha256(question.encode()).hexdigest()


def _normalize_weights(criteria: list[dict]) -> list[dict]:
    """Ensure criteria weights sum to exactly 100."""
    total = sum(c.get("weight", 0) for c in criteria)
    if total == 0:
        equal = round(100 / len(criteria))
        for c in criteria:
            c["weight"] = equal
        criteria[-1]["weight"] = 100 - equal * (len(criteria) - 1)
    elif total != 100:
        for c in criteria:
            c["weight"] = round(c["weight"] / total * 100)
        # Fix rounding drift on last element
        drift = 100 - sum(c["weight"] for c in criteria)
        criteria[-1]["weight"] += drift
    return criteria


def generate_rubric(question: str) -> dict:
    """Generate a 4–5 criterion rubric for evaluating a coding solution.

    Returns:
        {"criteria": [{"name", "weight", "description"}, ...], "total_points": 100}
    """
    key = _cache_key(question)
    if key in _rubric_cache:
        _rubric_cache.move_to_end(key)
        return _rubric_cache[key]

    prompt = f"""You are a Computer Science instructor creating a grading rubric for this coding problem:

"{question}"

Create a rubric with exactly 4-5 criteria that sum to 100 points total.

Return ONLY a JSON object (no markdown fences):
{{
  "criteria": [
    {{"name": "Correctness", "weight": 40, "description": "Solution produces correct output for valid inputs"}},
    {{"name": "Edge Cases", "weight": 20, "description": "Handles empty inputs, boundary values, and error cases"}},
    {{"name": "Code Quality", "weight": 20, "description": "Clean, readable code with meaningful variable names"}},
    {{"name": "Efficiency", "weight": 10, "description": "Reasonable time and space complexity for the problem"}},
    {{"name": "Readability", "weight": 10, "description": "Code is well-structured and easy to follow"}}
  ],
  "total_points": 100
}}

Tailor the criteria and weights to this specific problem. Correctness should always be the highest-weighted criterion (at least 35 points)."""

    try:
        data = _chat_json([{"role": "user", "content": prompt}], temperature=0.3)
        criteria = data.get("criteria", [])
        if not criteria:
            raise ValueError("No criteria returned")
        criteria = _normalize_weights(criteria)
        result = {"criteria": criteria, "total_points": 100}
    except Exception as e:
        print(f"Rubric generation error: {e}")
        result = {
            "criteria": [
                {"name": "Correctness", "weight": 50, "description": "Solution produces correct output"},
                {"name": "Edge Cases", "weight": 20, "description": "Handles edge cases properly"},
                {"name": "Code Quality", "weight": 20, "description": "Clean and readable code"},
                {"name": "Efficiency", "weight": 10, "description": "Reasonable complexity"},
            ],
            "total_points": 100,
        }

    # Store in cache; evict oldest if over limit
    _rubric_cache[key] = result
    _rubric_cache.move_to_end(key)
    if len(_rubric_cache) > _CACHE_MAX:
        _rubric_cache.popitem(last=False)

    return result
