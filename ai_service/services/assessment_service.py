import os
import json
import logging
from groq import Groq

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _client


async def generate_assessment_questions(course_title: str, num_questions: int = 6) -> dict:
    prompt = f"""Generate exactly {num_questions} multiple choice questions to assess a student's prior knowledge of "{course_title}".

Return ONLY a valid JSON object with no markdown fences, no extra text, in this exact format:
{{
  "questions": [
    {{
      "question": "Question text here?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_answer": "Option A"
    }}
  ]
}}

Requirements:
- Each question must have exactly 4 options
- The correct_answer must match one of the options exactly
- Questions should vary in difficulty (beginner to intermediate)
- Questions should test conceptual understanding, not trivia"""

    client = _get_client()
    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=2000,
    )

    raw = response.choices[0].message.content.strip()

    try:
        data = json.loads(raw)
        if "questions" not in data or not isinstance(data["questions"], list):
            raise ValueError("Missing or invalid 'questions' key")
        return data
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Failed to parse assessment JSON: %s\nRaw: %s", e, raw[:500])
        raise ValueError(f"LLM returned invalid JSON: {e}")
