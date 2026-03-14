"""
Code Extractor Agent — Deterministic code extraction.

Detects and extracts code blocks from raw text using pattern matching.
No ML involved — 100% deterministic, no hallucination risk.
"""

import re


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
