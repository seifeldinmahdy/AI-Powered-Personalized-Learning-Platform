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
        You are a supportive and expert Computer Science Tutor.
        
        TASK: "{question}"
        STUDENT CODE:
        {user_code}
        
        GRADING & GUIDANCE RULES:
        1. **Empty Implementation:** If the code only contains a function signature, `pass`, placeholder comments, or no real logic, the status MUST be "Needs Work". This is unimplemented starter code.
        2. **Technique Check:** If the task requires a specific method (e.g., a "loop") and the student used a shortcut (e.g., "len()"), the status is "Needs Work".
        3. **Status:** Return "Pass" only if the code contains a real, working implementation that solves the task correctly.
        4. **The Hint:** If the status is "Needs Work", the "feedback" must include a small, helpful hint. Do NOT give the full answer. Instead, ask a guiding question or point out the missing logic (e.g., "Try using a 'for' loop to visit each item one by one.").

        Output JSON ONLY:
        {{
        "status": "Pass" or "Needs Work",
        "feedback": "Your supportive hint or congratulatory message here."
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