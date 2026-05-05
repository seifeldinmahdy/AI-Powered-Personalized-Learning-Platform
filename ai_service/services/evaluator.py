import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
CODING_MODEL = os.getenv("GROQ_MODEL_CODING", "qwen/qwen3-32b")
FALLBACK_MODEL = "llama-3.3-70b-versatile"


def _chat_json(messages: list, temperature: float = 0.2) -> dict:
    """Call Groq with JSON mode, falling back to FALLBACK_MODEL on failure."""
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


def _letter_grade(score: int) -> str:
    if score >= 90: return "A"
    if score >= 87: return "A-"
    if score >= 83: return "B+"
    if score >= 80: return "B"
    if score >= 77: return "B-"
    if score >= 73: return "C+"
    if score >= 70: return "C"
    if score >= 67: return "C-"
    if score >= 60: return "D"
    return "F"


def evaluate_submission_graded(question: str, user_code: str, rubric: dict | None = None) -> dict:
    """Evaluate student code and return a 0–100 graded result with per-criterion breakdown.

    Args:
        question: The coding problem statement.
        user_code: The student's submitted code.
        rubric: Optional rubric dict from rubric_service. Generated server-side if absent.

    Returns:
        {
            "score": int,
            "letter_grade": str,
            "status": "Pass" | "Needs Work",
            "breakdown": [{"criterion", "earned", "max", "comment"}, ...],
            "feedback": str,
            "hint": str,
        }
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "your_groq_api_key_here":
        return _error_result("API Key missing. Please update your .env file.")

    if not user_code or not user_code.strip():
        return {
            "score": 0,
            "letter_grade": "F",
            "status": "Needs Work",
            "breakdown": [],
            "feedback": "No code submitted. Write your solution in the editor and try again.",
            "hint": "Start by reading the problem carefully and writing a function signature.",
        }

    if rubric is None:
        from services.rubric_service import generate_rubric
        rubric = generate_rubric(question)

    criteria = rubric.get("criteria", [])
    criteria_text = "\n".join(
        f"- {c['name']} ({c['weight']} pts): {c['description']}"
        for c in criteria
    )

    prompt = f"""You are a strict Computer Science grader. Evaluate the student's code against the rubric below.

PROBLEM:
{question}

STUDENT CODE:
{user_code}

GRADING RUBRIC:
{criteria_text}

Instructions:
1. Score each criterion from 0 to its maximum weight (partial credit is fine)
2. Provide a short 1-sentence comment per criterion explaining the score
3. Identify the lowest-scoring criterion and write one constructive hint (no full solution)
4. Write a 2-3 sentence overall feedback summary

Return ONLY a JSON object (no markdown fences):
{{
  "breakdown": [
    {{"criterion": "Correctness", "earned": 32, "max": 40, "comment": "Handles most cases but fails on empty input"}},
    ...
  ],
  "feedback": "Overall summary here.",
  "hint": "Specific constructive hint for the weakest area."
}}"""

    try:
        data = _chat_json([{"role": "user", "content": prompt}], temperature=0.2)
        breakdown = data.get("breakdown", [])

        # Clamp earned values to [0, max]
        for item in breakdown:
            item["earned"] = max(0, min(item.get("earned", 0), item.get("max", 0)))

        score = sum(item.get("earned", 0) for item in breakdown)
        score = max(0, min(100, score))
        letter = _letter_grade(score)

        return {
            "score": score,
            "letter_grade": letter,
            "status": "Pass" if score >= 60 else "Needs Work",
            "breakdown": breakdown,
            "feedback": data.get("feedback", ""),
            "hint": data.get("hint", ""),
        }

    except Exception as e:
        return _error_result(str(e))


def _error_result(message: str) -> dict:
    return {
        "score": 0,
        "letter_grade": "F",
        "status": "Error",
        "breakdown": [],
        "feedback": message,
        "hint": "",
    }


def evaluate_submission(question: str, user_code: str) -> dict:
    """Compatibility wrapper — returns legacy Pass/Needs Work format."""
    result = evaluate_submission_graded(question, user_code)
    return {"status": result["status"], "feedback": result["feedback"]}
