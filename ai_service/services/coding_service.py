import os
import sys
import logging
from dotenv import load_dotenv
from pathlib import Path

# Load .env from the ai_service directory
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)
print(f"[coding_service] Loaded .env from: {env_path}")

# ── OllamaClient (shared LLM backend, lazy load) ──
_pathway_src = str(Path(__file__).resolve().parent.parent.parent / "course_pathway" / "src")
if _pathway_src not in sys.path:
    sys.path.insert(0, _pathway_src)

_ollama_client: object | None = None

def _get_ollama_client() -> object:
    global _ollama_client
    if _ollama_client is None:
        try:
            from pathway.llm.naming import OllamaClient  # type: ignore
            _ollama_client = OllamaClient(
                host=os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_HOST", "https://ollama.com"),
                model=os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
                api_key=os.getenv("OLLAMA_API_KEY", ""),
                max_retries=3,
                timeout=120,
            )
        except Exception as e:
            logger.error(f"Failed to initialize OllamaClient: {e}. Will use Groq fallback.")
            _ollama_client = None
    return _ollama_client

logger = logging.getLogger(__name__)

# Groq fallback for coding operations
try:
    from groq import Groq as GroqClient
    _groq_client = GroqClient(api_key=os.getenv("GROQ_API_KEY", ""))
    CODING_MODEL = os.getenv("GROQ_MODEL_CODING", "qwen/qwen3-32b")
    FALLBACK_MODEL = "llama-3.3-70b-versatile"
except ImportError:
    logger.warning("Groq not installed. Code generation will rely on Ollama only.")
    _groq_client = None
    CODING_MODEL = None
    FALLBACK_MODEL = None

# Backend routing: "hybrid" (T5 for basic topics + LLM enrichment), "llm" (LLM only), "t5" (force T5)
# CODING_USE_T5=true is a legacy alias for backend=hybrid.
_raw_backend = os.getenv("CODING_QG_BACKEND", "")
if not _raw_backend:
    _raw_backend = "hybrid" if os.getenv("CODING_USE_T5", "false").lower() == "true" else "llm"
CODING_QG_BACKEND = _raw_backend.lower()
print(f"[coding_service] CODING_QG_BACKEND: '{CODING_QG_BACKEND}'")

# In-process history: topic -> list of recently generated question summaries (max 10)
from collections import defaultdict
_question_history: dict[str, list[str]] = defaultdict(list)
_HISTORY_MAX = 10


def _chat_json(messages: list, temperature: float = 0.7) -> dict:
    import json

    # Try Ollama first
    try:
        client = _get_ollama_client()
        if client is not None:
            return client.chat_json(
                messages=messages,
                temperature=temperature,
                timeout_override=120,
            )
    except Exception as e:
        logger.warning(f"OllamaClient failed: {e}. Falling back to Groq.")

    # Fall back to Groq
    for model in [CODING_MODEL, FALLBACK_MODEL]:
        try:
            completion = _groq_client.chat.completions.create(
                messages=messages,
                model=model,
                response_format={"type": "json_object"},
                temperature=temperature,
            )
            return json.loads(completion.choices[0].message.content)
        except Exception as e:
            if model == FALLBACK_MODEL:
                raise
            logger.warning(f"Model {model} failed: {e}. Retrying with {FALLBACK_MODEL}")

# ── T5 lazy load (only when flag is enabled) ────────────────────────────────
_tokenizer = None
_t5_model = None

def _load_t5():
    global _tokenizer, _t5_model
    if _tokenizer is not None:
        return
    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

    # Use absolute path based on this file's location
    ai_service_dir = Path(__file__).resolve().parent.parent
    MODEL_PATH = ai_service_dir / "models" / "clean_question_model"

    print("\n--- T5 CODING MODEL STARTUP ---")
    try:
        if MODEL_PATH.exists():
            print(f"Loading custom T5 model from: {MODEL_PATH}")
            _tokenizer = AutoTokenizer.from_pretrained(str(MODEL_PATH))
            _t5_model = AutoModelForSeq2SeqLM.from_pretrained(str(MODEL_PATH))
            print("✓ Custom LeetCode Model Loaded Successfully!")
        else:
            print(f"Model not found at {MODEL_PATH}, using t5-small")
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

# Topics the T5 model was trained on and handles reliably.
# Maps frontend topic name (lowercased) -> T5 training keyword.
_T5_TOPIC_MAP: dict[str, str] = {
    "loops": "loop",
    "control flow": "conditional",
    "arrays/lists": "array",
    "strings": "string",
    "dictionaries/maps": "dictionary",
    "sets": "set",
    "tuples": "tuple",
    "math": "math",
    "basic syntax": "math",
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


async def generate_problem_t5_enriched(topic: str) -> dict:
    """T5 generates the question core; LLM adds an I/O example + starter code.

    Stage 1: T5 (fine-tuned) produces a bare question sentence for the topic.
    Stage 2: LLM enriches it with a worked Input→Output example and a starter-code
             stub WITHOUT changing the task itself.
    Fallback: if the T5 output is incoherent or enrichment fails, raises so the
              caller can fall back to generate_problem_llm().
    """
    _load_t5()
    t5_keyword = _T5_TOPIC_MAP.get(topic.lower(), topic.lower())
    input_text = f"generate {t5_keyword}"
    print(f"[T5] generating core for: '{input_text}'")

    input_ids = _tokenizer.encode(input_text, return_tensors="pt")
    outputs = _t5_model.generate(
        input_ids,
        max_length=128,
        do_sample=True,
        temperature=0.9,
        top_k=50,
        top_p=0.95,
    )
    t5_question = _tokenizer.decode(outputs[0], skip_special_tokens=True).strip()

    if len(t5_question) < 15:
        raise ValueError(f"T5 produced incoherent output: '{t5_question}'")

    print(f"[T5] core question: {t5_question[:100]}")

    enrich_prompt = f"""You are a coding-question formatter. A fine-tuned model has generated this coding task:

"{t5_question}"

Your job is to enrich it WITHOUT changing the task itself. Return ONLY a JSON object (no markdown fences):
{{
  "question": "<exact original task, then one concrete worked example on a new line: Input: ... → Output: ...>",
  "starter_code": "def function_name(params):\\n    \\"\\"\\"Docstring describing the task.\\"\\"\\"\\n    pass"
}}

Rules:
- Keep the task wording as close to the original as possible (minor grammar fixes only).
- The worked example must use realistic values (e.g. Input: [3, 1, 4] → Output: 4).
- The starter code must be a function signature + docstring + `pass` ONLY — no solution code.
- Choose a descriptive function name that matches the task."""

    data = _chat_json([{"role": "user", "content": enrich_prompt}], temperature=0.3)

    if "question" not in data or "starter_code" not in data:
        raise ValueError("LLM enrichment response missing required fields")

    # Record for dedup (same history used by LLM path)
    history = _question_history[topic.lower()]
    summary = data["question"][:80].split(".")[0]
    history.append(summary)
    if len(history) > _HISTORY_MAX:
        history.pop(0)

    return data


async def generate_problem(topic: str) -> dict:
    """Route to T5-enriched (hybrid) or pure-LLM based on CODING_QG_BACKEND."""
    print(f"\n=== GENERATE_PROBLEM: backend={CODING_QG_BACKEND}, topic={topic} ===")

    if CODING_QG_BACKEND == "t5":
        print("→ T5-enriched (forced)")
        return await generate_problem_t5_enriched(topic)

    if CODING_QG_BACKEND == "hybrid" and topic.lower() in _T5_TOPIC_MAP:
        print("→ T5-enriched (hybrid path)")
        try:
            return await generate_problem_t5_enriched(topic)
        except Exception as e:
            print(f"  T5-enriched failed ({e}), falling back to LLM")
            return await generate_problem_llm(topic)

    print("→ LLM only")
    return await generate_problem_llm(topic)


async def evaluate_code(question: str, code: str) -> dict:
    from services.evaluator import evaluate_submission
    return evaluate_submission(question, code)
