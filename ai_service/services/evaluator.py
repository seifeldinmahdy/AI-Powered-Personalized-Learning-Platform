import os
import json
from groq import Groq
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
api_key = os.getenv("GROQ_API_KEY")

def evaluate_submission(question, user_code):
    if not api_key or api_key == "your_groq_api_key_here":
        return {"status": "Error", "feedback": "API Key missing. Please update your .env file."}

    if not user_code or not user_code.strip():
        return {"status": "Needs Work", "feedback": "No code submitted. Write your solution in the editor and try again."}

    client = Groq(api_key=api_key)
    
    prompt = f"""
        You are a strict Computer Science Tutor grading student code.

        TASK: "{question}"
        STUDENT CODE:
        {user_code}

        STRICT GRADING RULES — follow ALL of them:
        1. **Placeholder code:** If the body contains ONLY `pass`, `...`, a single undefined variable, or any code that does NOT solve the task, status MUST be "Needs Work". No exceptions.
        2. **Single variable or expression:** A line like `x`, `True`, or `matrix` with no logic is NOT a solution. Status MUST be "Needs Work".
        3. **Correctness:** Return "Pass" ONLY if the code actually implements the correct logic to solve the task completely.
        4. **Partial attempts:** If the student started but the logic is incomplete or wrong, status is "Needs Work".
        5. **Hint:** If "Needs Work", give a short helpful hint pointing to what is missing. Do NOT reveal the full solution.

        You MUST be strict. When in doubt, return "Needs Work".

        Output JSON ONLY:
        {{
        "status": "Pass" or "Needs Work",
        "feedback": "Your hint or congratulatory message here."
        }}
        """

    try:
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant", 
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        return {"status": "Error", "feedback": str(e)}