"""
Code Extractor Agent — Deterministic extraction + LLM validation / generation.

Two-stage, compound-AI design (mirrors the visual classifier ↔ judge split):

  Stage 1 — DETERMINISTIC (this is the prior, no hallucination risk):
    Regex/pattern checks find literal code in the chunk (`extract_code`).

  Stage 2 — LLM (only when enabled; always fails OPEN to Stage 1):
    A) If Stage 1 found code  → an LLM *validates & augments* it: fixes obvious
       syntax, makes it self-contained, trims to the slide line budget, and
       produces a short demonstrative output.
    B) If Stage 1 found nothing but the chunk has STRONG code signals → an
       HDEval gate (independent yes/no questions, G-Eval form-filling) decides,
       with the decision enforced in Python (not by the model's free opinion),
       whether a small self-contained snippet would aid demonstration. Only if
       every gate question is "yes" does the LLM generate the snippet + output.

The "output" is DEMONSTRATIVE — the LLM writes the expected stdout; nothing is
executed (no sandbox). The frontend shows a "Run" button that reveals it. Code
is capped at MAX_CODE_LINES and output at MAX_OUTPUT_LINES/CHARS so the block
always fits a slide without disturbing the rest of the layout.

Public surface:
  - chunk_has_code / detect_language / extract_code_lines / extract_code  (deterministic)
  - build_code_block(...)  → the full compound result used by the pipeline
"""

import os
import threading

from slide_gen.data_engine.utils import extract_json_from_response
from slide_gen.data_engine.key_pool import load_nvidia_keys, get_nvidia_config
from slide_gen.data_engine.nvidia_client import (
    NvidiaClient,
    NvidiaAuthError,
    NvidiaRateLimitError,
)


# Strict code patterns — only match definite programming constructs
CODE_PATTERNS = [
    "def ",           # Python function definition
    "class ",         # Class definition
    "import ",        # Python import
    "from ",          # Python from import
    ">>> ",           # Python REPL prompt
    "return ",        # Return statement
    "print(",         # Print function call
    "= function",     # JavaScript function assignment
    "const ",         # JavaScript const
    "let ",           # JavaScript let
    "var ",           # JavaScript var
    "function(",      # JavaScript function
    "async def",      # Async function
    "@property",      # Python decorator
    "@staticmethod",  # Python decorator
]

# Language detection heuristics
LANGUAGE_INDICATORS = {
    "python": ["def ", "import ", "from ", "print(", ">>> ", "elif ", "self."],
    "javascript": ["const ", "let ", "var ", "function(", "=> ", "console.log"],
    "java": ["public class", "System.out", "void ", "String[]"],
    "c": ["#include", "printf(", "int main"],
    "cpp": ["#include", "cout", "std::", "int main"],
}


def chunk_has_code(chunk: str) -> bool:
    """
    Detect if a chunk contains programming code.

    Requires multiple indicators to avoid false positives from English.

    Args:
        chunk: Raw text

    Returns:
        True if code is detected
    """
    pattern_matches = sum(1 for p in CODE_PATTERNS if p in chunk)

    # Need at least 2 code patterns for high confidence
    if pattern_matches >= 2:
        return True

    # Single pattern match + indentation indicates code
    if pattern_matches >= 1:
        lines = chunk.split("\n")
        has_indented = any(
            line.startswith("    ") or line.startswith("\t")
            for line in lines
        )
        if has_indented:
            return True

    return False


def detect_language(code: str) -> str:
    """
    Detect programming language from code content.

    Args:
        code: Extracted code string

    Returns:
        Language name (defaults to 'python')
    """
    scores = {}
    for lang, indicators in LANGUAGE_INDICATORS.items():
        score = sum(1 for ind in indicators if ind in code)
        if score > 0:
            scores[lang] = score

    if scores:
        return max(scores, key=scores.get)
    return "python"  # Default


def extract_code_lines(chunk: str) -> list[str]:
    """
    Extract lines that are likely code from a text chunk.

    Strategies:
    1. Lines inside ``` fenced blocks
    2. Lines starting with >>> (REPL)
    3. Consecutive indented lines following a code pattern

    Args:
        chunk: Raw text

    Returns:
        List of code lines
    """
    lines = chunk.split("\n")
    code_lines = []

    # Strategy 1: Fenced code blocks
    in_fence = False
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            code_lines.append(line)

    if code_lines:
        return code_lines

    # Strategy 2: REPL prompts
    repl_lines = [l for l in lines if l.strip().startswith(">>>")]
    if repl_lines:
        return [l.replace(">>> ", "").replace(">>>", "") for l in repl_lines]

    # Strategy 3: Indented blocks after code patterns
    capturing = False
    for line in lines:
        stripped = line.strip()

        # Start capturing if we hit a code pattern
        if any(p in line for p in CODE_PATTERNS):
            capturing = True
            code_lines.append(line)
            continue

        # Continue capturing indented lines
        if capturing:
            if line.startswith("    ") or line.startswith("\t") or stripped == "":
                code_lines.append(line)
            else:
                # Stop at non-indented non-empty line
                if stripped:
                    capturing = False

    return code_lines


def extract_code(chunk: str) -> dict | None:
    """
    Extract code from a text chunk if present.

    Args:
        chunk: Raw text chunk

    Returns:
        Dict with 'language' and 'code' keys, or None if no code found
    """
    if not chunk_has_code(chunk):
        return None

    code_lines = extract_code_lines(chunk)
    if not code_lines:
        return None

    code = "\n".join(code_lines).strip()
    if not code or len(code) < 10:
        return None

    language = detect_language(code)

    return {
        "language": language,
        "code": code,
    }


# =============================================================================
# STAGE 2 — LLM validation / generation (compound layer, fails OPEN)
# =============================================================================

# Slide-fit budgets. Keep the block small so it never overflows the slide or
# pushes other elements around in the frontend.
MAX_CODE_LINES = 14
MAX_OUTPUT_LINES = 8
MAX_OUTPUT_CHARS = 400

# How many distinct, strong code signals a code-less chunk needs before we even
# consider asking the LLM to GENERATE an example. Cheap pre-filter for the gate.
_STRONG_SIGNAL_MIN = 2

# Words that strongly suggest the chunk is teaching something programmable
# (a library/function/API/algorithm), not pure prose/theory.
_CODE_SIGNAL_TERMS = [
    "function", "method", "argument", "parameter", "return value", "returns",
    "syntax", "library", "module", "package", "api", "algorithm", "loop",
    "iterate", "variable", "array", "list", "dictionary", "string method",
    "data structure", "compile", "runtime", "call the", "invoke", "snippet",
    "implementation", "pseudocode", "import", "object", "instance", "class",
    "recursion", "iterator", "command", "expression", "operator",
]


def _llm_enabled() -> bool:
    return os.getenv("CODE_LLM_ENABLED", "1").strip().lower() not in ("0", "false", "no")


def _llm_model() -> str:
    # Fast NVIDIA NIM reasoning model — same backend the data generation uses.
    return os.getenv("CODE_LLM_MODEL", "nvidia/nemotron-3-nano-30b-a3b")


# One process-wide client (its rate limiter is shared account-wide anyway).
_NVIDIA_CLIENT: NvidiaClient | None = None
_NVIDIA_INIT_DONE = False
_CLIENT_LOCK = threading.Lock()


def _get_client() -> NvidiaClient | None:
    """Lazily build the shared NVIDIA NIM client. Returns None if no keys."""
    global _NVIDIA_CLIENT, _NVIDIA_INIT_DONE
    with _CLIENT_LOCK:
        if _NVIDIA_INIT_DONE:
            return _NVIDIA_CLIENT
        _NVIDIA_INIT_DONE = True
        keys = load_nvidia_keys()
        if not keys:
            return None
        cfg = get_nvidia_config()
        _NVIDIA_CLIENT = NvidiaClient(
            base_url=cfg["base_url"],
            model=_llm_model(),
            api_key=keys[0],          # all keys pool to one account; limiter governs RPM
            rpm=cfg["rpm"],
        )
        return _NVIDIA_CLIENT


def _call_llm(system_prompt: str, user_prompt: str, timeout: int = 60) -> dict | None:
    """Call the NVIDIA NIM model and parse JSON from the reply. Fails OPEN (None)."""
    client = _get_client()
    if client is None:
        return None
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    try:
        text = client.chat(messages, temperature=0.1, timeout_override=timeout)
    except (NvidiaRateLimitError, NvidiaAuthError, RuntimeError):
        return None
    except Exception:
        return None
    return extract_json_from_response(text)


def _yes(value) -> bool:
    """Normalize an LLM yes/no answer to a strict bool (defaults to False)."""
    return str(value).strip().lower() in ("yes", "y", "true", "1")


def _clip_output(output: str | None) -> str | None:
    """Enforce the demonstrative-output budget (lines + chars)."""
    if not output:
        return None
    text = str(output).rstrip("\n")
    lines = text.split("\n")
    truncated = False
    if len(lines) > MAX_OUTPUT_LINES:
        lines = lines[:MAX_OUTPUT_LINES]
        truncated = True
    text = "\n".join(lines)
    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS].rstrip()
        truncated = True
    if truncated:
        text += "\n..."
    return text or None


def _code_line_count(code: str) -> int:
    return len([ln for ln in code.split("\n")])


def _clip_code(code: str) -> str:
    """Trim extracted code to the slide line budget (best-effort, keeps the head)."""
    lines = code.split("\n")
    if len(lines) <= MAX_CODE_LINES:
        return code.rstrip("\n")
    kept = lines[:MAX_CODE_LINES]
    return "\n".join(kept).rstrip("\n") + "\n# ..."


def _signal_count(chunk: str) -> int:
    """Count distinct strong programming signals in a code-less chunk."""
    low = chunk.lower()
    return sum(1 for term in _CODE_SIGNAL_TERMS if term in low)


# --- Path A: validate & augment code the regex already found -----------------

_VALIDATE_SYSTEM = (
    "You verify and lightly repair short code snippets pulled from lecture text "
    "so they can be shown on a slide. You fix only obvious breakage (indentation, "
    "an unmatched bracket, an undefined name needed to run), make the snippet "
    "self-contained, and predict its console output. You never invent unrelated "
    "functionality. Output ONLY JSON."
)


def _validate_and_augment(language: str, code: str, title: str | None,
                          timeout: int) -> dict | None:
    """LLM-validate extracted code and produce a demonstrative output."""
    user = (
        f"## DETECTED LANGUAGE: {language}\n\n"
        f"## SLIDE TITLE: {title or '(none)'}\n\n"
        f"## EXTRACTED CODE:\n```\n{code[:1500]}\n```\n\n"
        f"Tasks:\n"
        f"1. Repair only what is needed so this runs standalone (keep it faithful "
        f"to the original; do not add unrelated logic).\n"
        f"2. Keep it at most {MAX_CODE_LINES} lines.\n"
        f"3. Give the exact console output it would print, at most "
        f"{MAX_OUTPUT_LINES} lines / {MAX_OUTPUT_CHARS} chars. If it prints "
        f"nothing, use an empty string.\n\n"
        'Output ONLY: {"language": "...", "is_valid": "yes/no", '
        '"code": "the final snippet", "output": "expected stdout", '
        '"output_is_short": "yes/no"}'
    )
    result = _call_llm(_VALIDATE_SYSTEM, user, timeout=timeout)
    if not result or not result.get("code"):
        return None
    final_code = _clip_code(str(result["code"]))
    out = _clip_output(result.get("output"))
    lang = str(result.get("language") or language).strip().lower() or language
    return {
        "language": lang,
        "code": final_code,
        "output": out,
        "runnable": out is not None,
        "generated": False,
    }


# --- Path B: HDEval gate + generate an example for a code-less chunk ----------

_GENERATE_SYSTEM = (
    "You decide whether a tiny runnable code example would help teach the slide "
    "content, then — only if it would — you write one. You answer the gate "
    "questions independently and literally (yes/no), without trying to justify "
    "adding code. A good example is short, self-contained, and directly "
    "demonstrates the specific library / function / concept being explained. "
    "Output ONLY JSON."
)


def _gate_and_generate(chunk: str, title: str | None, bullets: list[str] | None,
                       timeout: int) -> dict | None:
    """Run the yes/no HDEval gate and, if it passes in Python, take the snippet."""
    bullets_text = "\n".join(f"- {b}" for b in (bullets or [])) or "(none)"
    user = (
        f"## SLIDE TITLE: {title or '(none)'}\n\n"
        f"## BULLETS:\n{bullets_text}\n\n"
        f"## SOURCE TEXT:\n{chunk[:1200]}\n\n"
        f"Answer each question independently with exactly \"yes\" or \"no\":\n"
        f"- is_programming_topic: Is this content about a concrete programmable "
        f"thing (a library, function, method, API, syntax, or algorithm) that is "
        f"normally expressed in code?\n"
        f"- code_demonstrates: Would a short runnable snippet demonstrate this "
        f"MORE clearly than prose alone?\n"
        f"- self_containable: Can a correct example be written in at most "
        f"{MAX_CODE_LINES} lines with NO external files, network, or data setup?\n"
        f"- not_pure_theory: Is this NOT purely abstract theory / history / a "
        f"plain definition with no executable angle?\n\n"
        f"If and only if ALL four are \"yes\", also provide a snippet (<= "
        f"{MAX_CODE_LINES} lines) demonstrating exactly the content above, plus "
        f"its expected console output (<= {MAX_OUTPUT_LINES} lines / "
        f"{MAX_OUTPUT_CHARS} chars). Otherwise set code and output to \"\".\n\n"
        'Output ONLY: {"is_programming_topic": "yes/no", "code_demonstrates": '
        '"yes/no", "self_containable": "yes/no", "not_pure_theory": "yes/no", '
        '"language": "python", "code": "...", "output": "...", '
        '"output_is_short": "yes/no"}'
    )
    result = _call_llm(_GENERATE_SYSTEM, user, timeout=timeout)
    if not result:
        return None

    # HDEval gate enforced in Python — every question must be yes.
    gate = (
        _yes(result.get("is_programming_topic"))
        and _yes(result.get("code_demonstrates"))
        and _yes(result.get("self_containable"))
        and _yes(result.get("not_pure_theory"))
    )
    if not gate:
        return None

    code = str(result.get("code") or "").strip()
    if not code:
        return None
    # Generated code that blows the line budget is rejected rather than truncated
    # (a clipped generated snippet would be broken — worse than no code).
    if _code_line_count(code) > MAX_CODE_LINES:
        return None

    out = _clip_output(result.get("output"))
    lang = str(result.get("language") or detect_language(code)).strip().lower() or "python"
    return {
        "language": lang,
        "code": code,
        "output": out,
        "runnable": out is not None,
        "generated": True,
    }


def build_code_block(
    chunk: str,
    title: str | None = None,
    bullets: list[str] | None = None,
    enable_llm: bool | None = None,
    timeout: int = 45,
) -> dict | None:
    """
    Full compound code result for a chunk.

    Returns a dict with keys ``language, code, output, runnable, generated`` or
    ``None`` when no code should be shown.

    Flow:
      1. Deterministic ``extract_code`` (the prior).
      2. If code was found → LLM validate/augment + demonstrative output (Path A).
      3. If no code but strong code signals → HDEval yes/no gate, and only on a
         full pass, LLM generate a snippet + output (Path B).

    Every LLM step fails OPEN: on any error or when the LLM is disabled, this
    degrades to the deterministic result (extracted code with no output) or
    ``None`` — never worse than the regex-only behavior.
    """
    use_llm = _llm_enabled() if enable_llm is None else enable_llm

    deterministic = extract_code(chunk)

    # --- Path A: regex found code ---
    if deterministic:
        if not use_llm:
            return {
                "language": deterministic["language"],
                "code": _clip_code(deterministic["code"]),
                "output": None,
                "runnable": False,
                "generated": False,
            }
        augmented = _validate_and_augment(
            deterministic["language"], deterministic["code"], title, timeout
        )
        if augmented:
            return augmented
        # Fail open to the raw extracted code (still useful, just no output).
        return {
            "language": deterministic["language"],
            "code": _clip_code(deterministic["code"]),
            "output": None,
            "runnable": False,
            "generated": False,
        }

    # --- Path B: no literal code — consider generating one ---
    if not use_llm:
        return None
    if _signal_count(chunk) < _STRONG_SIGNAL_MIN:
        return None
    return _gate_and_generate(chunk, title, bullets, timeout)
