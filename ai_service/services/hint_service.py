import os
import sys
import json
import logging
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# ── OllamaClient (shared LLM backend) ──
_pathway_src = str(Path(__file__).resolve().parent.parent.parent / "course_pathway" / "src")
if _pathway_src not in sys.path:
    sys.path.insert(0, _pathway_src)

from pathway.llm.naming import OllamaClient  # type: ignore

logger = logging.getLogger(__name__)

_ollama_client: OllamaClient | None = None

def _get_ollama_client() -> OllamaClient:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient(
            host=os.getenv("OLLAMA_HOST", "https://ollama.com"),
            model=os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
            api_key=os.getenv("OLLAMA_API_KEY", ""),
            max_retries=3,
            timeout=120,
        )
    return _ollama_client


def _chat_json(messages: list, temperature: float = 0.5) -> dict:
    client = _get_ollama_client()
    return client.chat_json(
        messages=messages,
        temperature=temperature,
        timeout_override=120,
    )


_LEVEL_INSTRUCTIONS = {
    1: (
        "Give a CONCEPTUAL nudge only — point the student toward the right way of thinking "
        "without mentioning specific code or data structures. Example: 'Think about how you "
        "would track something as you iterate through the list.'"
    ),
    2: (
        "Give an APPROACH hint — mention the key data structure or algorithm pattern to use, "
        "but do NOT show any code. Example: 'Consider using a dictionary to map each element "
        "to its count, then look for the maximum.'"
    ),
    3: (
        "Give a PSEUDOCODE-level hint — describe the step-by-step algorithm in plain English "
        "or pseudocode, still without writing actual Python code. Example: '1. Create an empty "
        "dict. 2. For each number, increment its count. 3. Return the key with the highest value.'"
    ),
}


def get_hint(question: str, code: str, hint_level: int) -> dict:
    """Return a progressive hint for the given coding problem and student's current code.

    Args:
        question: The problem statement.
        code: The student's current code (may be empty or partial).
        hint_level: 1 (conceptual), 2 (approach), or 3 (pseudocode).

    Returns:
        {"hint": str, "level": int}
    """
    level = max(1, min(3, hint_level))
    instruction = _LEVEL_INSTRUCTIONS[level]

    code_context = f"\nStudent's current code:\n{code}" if code and code.strip() else ""

    prompt = f"""You are a helpful CS tutor giving a hint for this problem:

PROBLEM:
{question}{code_context}

HINT LEVEL {level} INSTRUCTION:
{instruction}

Provide exactly ONE hint sentence or short paragraph. Do NOT reveal the full solution.
Return ONLY a JSON object:
{{"hint": "Your hint here."}}"""

    try:
        data = _chat_json([{"role": "user", "content": prompt}], temperature=0.5)
        hint_text = data.get("hint", "Think carefully about the problem structure.")
    except Exception as e:
        print(f"Hint generation error: {e}")
        hint_text = "Try breaking the problem into smaller steps."

    return {"hint": hint_text, "level": level}
