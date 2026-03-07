import os
from groq import Groq
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from dotenv import load_dotenv

# Import your existing evaluator function (assuming it's in the same folder now)
from services.evaluator import evaluate_submission 

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# UPDATED PATH: Pointing to the models folder
MODEL_PATH = "models/clean_question_model" 

print("\n--- CODING EVALUATOR STARTUP ---")
try:
    if os.path.exists(MODEL_PATH):
        print(f"Found custom model folder at: {MODEL_PATH}")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
        model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_PATH)
        print("Custom LeetCode Model Loaded Successfully!")
    else:
        print(f"ERROR: Could not find folder '{MODEL_PATH}'")
        tokenizer = AutoTokenizer.from_pretrained("t5-small")
        model = AutoModelForSeq2SeqLM.from_pretrained("t5-small")
except Exception as e:
    print(f"CRITICAL ERROR LOADING MODEL: {e}")
    tokenizer = AutoTokenizer.from_pretrained("t5-small")
    model = AutoModelForSeq2SeqLM.from_pretrained("t5-small")

TOPIC_MAPPING = {
    "arr": "array", "arrar": "array", "arry": "array", "list": "array", "lists": "array",
    "dp": "dynamic programming", "dynmic": "dynamic programming",
    "dfs": "depth-first search", "bfs": "breadth-first search",
    "hash": "hash table", "map": "hash table", "dict": "hash table",
    "sort": "sorting", "bst": "binary search tree", "strings": "string"
}

def normalize_topic(user_input):
    clean_input = user_input.lower().replace("generate", "").strip()
    return TOPIC_MAPPING.get(clean_input, clean_input)

async def generate_problem(topic: str):
    smart_topic = normalize_topic(topic)
    input_text = f"generate {smart_topic}"
    print(f"Generating problem for: '{input_text}'")

    input_ids = tokenizer.encode(input_text, return_tensors="pt")
    outputs = model.generate(
        input_ids, 
        max_length=128, 
        do_sample=True, 
        temperature=0.9, 
        top_k=50, 
        top_p=0.95
    )
    question = tokenizer.decode(outputs[0], skip_special_tokens=True)

    print(f"Llama is creating starter code for: {question[:30]}...")
    
    prompt = f"""
    Based on this coding task: "{question}"
    Provide ONLY the Python function signature and a docstring. 
    Do NOT write the solution. Do NOT use markdown code blocks (```).
    Example format:
    def function_name(parameters):
        \"\"\"Docstring describing the task.\"\"\"
        pass
    """

    try:
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",
            temperature=0.1
        )
        starter_code = completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"Groq Error: {e}")
        starter_code = "def solution():\n    # TODO: Write your code here\n    pass"
        
    return {"question": question, "starter_code": starter_code}

async def evaluate_code(question: str, code: str):
    return evaluate_submission(question, code)