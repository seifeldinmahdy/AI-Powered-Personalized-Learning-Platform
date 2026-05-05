import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
CODING_MODEL = os.getenv("GROQ_MODEL_CODING", "qwen/qwen3-32b")
FALLBACK_MODEL = "llama-3.3-70b-versatile"


def _chat_json(messages: list, temperature: float = 0.5) -> dict:
    for model in [CODING_MODEL, FALLBACK_MODEL]:
        try:
            completion = _client.chat.completions.create(
                messages=messages,
                model=model,
                response_format={"type": "json_object"},
                temperature=temperature,
            )
            return json.loads(completion.choices[0].message.content)
        except Exception as e:
            if model == FALLBACK_MODEL:
                raise
            print(f"Model {model} failed ({e}), retrying with {FALLBACK_MODEL}")


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
