import os
import sys
import logging
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

# ── OllamaClient (shared LLM backend) ──
_pathway_src = str(Path(__file__).resolve().parent.parent.parent / "course_pathway" / "src")
if _pathway_src not in sys.path:
    sys.path.insert(0, _pathway_src)

from pathway.llm.naming import OllamaClient  # type: ignore

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

logger = logging.getLogger(__name__)

# Feature flag: set CODING_USE_T5=true to fall back to T5 + llama starter code
USE_T5_FALLBACK = os.getenv("CODING_USE_T5", "false").lower() == "true"

# In-process history: topic -> list of recently generated question summaries (max 10)
from collections import defaultdict
_question_history: dict[str, list[str]] = defaultdict(list)
_HISTORY_MAX = 10


def _chat_json(messages: list, temperature: float = 0.7) -> dict:
    client = _get_ollama_client()
    return client.chat_json(
        messages=messages,
        temperature=temperature,
        timeout_override=120,
    )

# ── T5 lazy load (only when flag is enabled) ────────────────────────────────
_tokenizer = None
_t5_model = None

def _load_t5():
    global _tokenizer, _t5_model
    if _tokenizer is not None:
        return
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
    MODEL_PATH = "models/clean_question_model"
    print("\n--- T5 CODING MODEL STARTUP ---")
    try:
        if os.path.exists(MODEL_PATH):
            _tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
            _t5_model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_PATH)
            print("Custom LeetCode Model Loaded Successfully!")
        else:
            _tokenizer = AutoTokenizer.from_pretrained("t5-small")
            _t5_model = AutoModelForSeq2SeqLM.from_pretrained("t5-small")
    except Exception as e:
        print(f"CRITICAL ERROR LOADING MODEL: {e}")
        _tokenizer = AutoTokenizer.from_pretrained("t5-small")
        _t5_model = AutoModelForSeq2SeqLM.from_pretrained("t5-small")


TOPIC_MAPPING = {
    "arr": "array", "arrar": "array", "arry": "array", "list": "array", "lists": "array",
    "dp": "dynamic programming", "dynmic": "dynamic programming",
    "dfs": "depth-first search", "bfs": "breadth-first search",
    "hash": "hash table", "map": "hash table", "dict": "hash table",
    "sort": "sorting", "bst": "binary search tree", "strings": "string"
}


def normalize_topic(user_input: str) -> str:
    clean_input = user_input.lower().replace("generate", "").strip()
    return TOPIC_MAPPING.get(clean_input, clean_input)


# Per-topic guidance so the LLM generates problems that genuinely match the topic
_TOPIC_GUIDANCE = {
    "linear regression": "Write a problem about calculating a predicted value using slope and intercept (y = mx + b), or computing mean squared error between predicted and actual values.",
    "classification": "Write a problem about labeling items into categories based on a simple rule or threshold (e.g., spam/not-spam, pass/fail based on score).",
    "clustering": "Write a problem about grouping items by similarity, such as finding which cluster center a point is closest to given a list of centroids.",
    "model evaluation": "Write a problem about computing accuracy, precision, or recall given lists of predicted and actual labels.",
    "feature engineering": "Write a problem about transforming raw data, such as normalizing a list of numbers to 0–1 range, or one-hot encoding a categorical list.",
    "data preprocessing": "Write a problem about cleaning data — removing None/NaN values, filling missing values with mean, or normalizing a dataset.",
    "numpy arrays": "Write a problem about array operations: element-wise addition, finding the max/min, computing the mean, or reshaping a flat list into a 2D grid.",
    "pandas dataframes": "Write a problem that simulates a DataFrame operation using plain Python dicts/lists — e.g., filtering rows by a condition, computing a column average, or finding duplicates.",
    "binary search": "Write a problem about finding a target value in a sorted list using binary search logic.",
    "two pointers": "Write a problem that uses two index variables moving toward each other, such as checking if a list has a pair that sums to a target.",
    "sliding window": "Write a problem about finding the maximum or minimum sum of a fixed-size sublist.",
    "tree traversal": "Write a problem about traversing a simple nested dict or list structure level by level or recursively.",
    "graph bfs/dfs": "Write a problem about exploring nodes in a simple adjacency list graph using BFS or DFS.",
    "linked list": "Write a problem about traversing or manipulating a simple chain of nodes represented as dicts with a 'next' key.",
    "stack": "Write a problem about using a list as a stack (append/pop) to solve a task like matching brackets or reversing a string.",
    "queue": "Write a problem about using a list as a queue (append/pop(0)) to process items in order.",
    "dynamic programming (dp)": "Write a problem about building up a solution from smaller subproblems, such as computing Fibonacci numbers with memoization or finding the minimum number of coins for a sum.",
    "recursion": "Write a problem that requires a function to call itself, such as computing factorial, summing a nested list, or flattening a list.",
    "sorting & searching": "Write a problem about sorting a list by a custom key or searching for an element meeting a condition.",
}


async def generate_problem_llm(topic: str) -> dict:
    """Generate a coding problem, avoiding recently seen questions for this topic."""
    history = _question_history[topic.lower()]
    avoid_section = ""
    if history:
        avoid_list = "\n".join(f"- {q}" for q in history)
        avoid_section = f"\nDo NOT generate any of these already-used problems:\n{avoid_list}\n"

    topic_guidance = _TOPIC_GUIDANCE.get(topic.lower(), "")
    topic_context = f"\nTopic context: {topic_guidance}" if topic_guidance else ""

    prompt = f"""Generate a simple, beginner-friendly coding problem about "{topic}" for a student who is just learning Python.{topic_context}
{avoid_section}
Return ONLY a JSON object (no markdown fences) in this exact format:
{{
  "question": "Problem statement here. Include 1 clear example with input and output.",
  "starter_code": "def function_name(params):\\n    \\\"\\\"\\\"Docstring describing the task.\\\"\\\"\\\"\\n    pass"
}}

Requirements:
- The problem MUST genuinely relate to the topic "{topic}" — do not generate a generic math or list problem and label it as that topic
- Keep it SIMPLE — solvable with basic loops, conditionals, or built-in operations (no algorithms, no complex data structures)
- The problem should be solvable in 3-8 lines of code
- Use plain everyday language, no jargon
- Include one concrete example (e.g., Input: [1,2,3] → Output: 6)
- The starter code must be a Python function signature + docstring only — NO solution code
- Function name should match the task (e.g., find_max, reverse_string)
- The starter code must end with `pass`
- Good examples: sum a list, count vowels, find the largest number, check if a string is a palindrome"""

    try:
        data = _chat_json([{"role": "user", "content": prompt}], temperature=0.9)
        if "question" not in data or "starter_code" not in data:
            raise ValueError("Missing required fields in LLM response")

        # Record a short summary of this question to avoid future repeats
        summary = data["question"][:80].split(".")[0]
        history.append(summary)
        if len(history) > _HISTORY_MAX:
            history.pop(0)

        return data
    except Exception as e:
        print(f"Generation error: {e}")
        raise


async def generate_problem_t5(topic: str) -> dict:
    """Generate a coding problem using the legacy T5 model."""
    _load_t5()
    smart_topic = normalize_topic(topic)
    input_text = f"generate {smart_topic}"
    print(f"T5 generating problem for: '{input_text}'")

    input_ids = _tokenizer.encode(input_text, return_tensors="pt")
    outputs = _t5_model.generate(
        input_ids,
        max_length=128,
        do_sample=True,
        temperature=0.9,
        top_k=50,
        top_p=0.95
    )
    question = _tokenizer.decode(outputs[0], skip_special_tokens=True)

    starter_code_prompt = f"""Based on this coding task: "{question}"
Provide ONLY the Python function signature and a docstring.
Do NOT write the solution. Do NOT use markdown code blocks (```).
Example format:
def function_name(parameters):
    \"\"\"Docstring describing the task.\"\"\"
    pass"""

    try:
        client = _get_ollama_client()
        result = client.chat_json(
            messages=[{"role": "user", "content": starter_code_prompt}],
            temperature=0.1,
            timeout_override=60,
        )
        starter_code = result.get("starter_code", "def solution():\n    # TODO: Write your code here\n    pass")
    except Exception as e:
        print(f"OllamaClient Error: {e}")
        starter_code = "def solution():\n    # TODO: Write your code here\n    pass"

    return {"question": question, "starter_code": starter_code}


async def generate_problem(topic: str) -> dict:
    """Generate a coding problem. Routes to T5 or Qwen based on CODING_USE_T5 flag."""
    if USE_T5_FALLBACK:
        return await generate_problem_t5(topic)
    return await generate_problem_llm(topic)


async def evaluate_code(question: str, code: str) -> dict:
    from services.evaluator import evaluate_submission
    return evaluate_submission(question, code)
