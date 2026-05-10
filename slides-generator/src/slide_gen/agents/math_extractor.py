"""
Math Extractor Agent — Detects and extracts mathematical equations from text.

A three-layer pipeline:
1. Detection  (regex, no LLM)  — fast pre-filter for math signals
2. Extraction (Ollama LLM)     — converts detected math into clean LaTeX
3. Validation (pylatexenc)      — verifies LaTeX is parseable

This agent is completely independent of the visual classifier and code
extractor.  It is an additive, parallel pipeline that enriches slides
with renderable math when math content is present in the source chunk.
"""

import json
import logging
import os
import re
from typing import Any

import requests

from slide_gen.core.slide_schema import EquationItem
from slide_gen.data_engine.utils import extract_json_from_response

logger = logging.getLogger(__name__)


# =============================================================================
# LAYER 1 — DETECTION (Regex, no LLM)
# =============================================================================

# Greek letters as Unicode code points
_GREEK_UNICODE = set(
    "α β γ δ ε ζ η θ ι κ λ μ ν ξ ο π ρ σ τ υ φ χ ψ ω"
    " Α Β Γ Δ Ε Ζ Η Θ Ι Κ Λ Μ Ν Ξ Ο Π Ρ Σ Τ Υ Φ Χ Ψ Ω"
    " ϵ ϕ ϑ ϱ ϖ".split()
)

# Math operators as Unicode code points
_MATH_OPERATORS = set(
    "∑ ∫ √ ∏ ≤ ≥ ≠ ∈ ∉ ⊂ ⊃ ∩ ∪ → ← ↔ ∀ ∃ − × ÷ ± ∞ ∂ ∇ ≈ ≡ ≫ ≪ ⊕ ⊗".split()
)

# Keywords that indicate math context
_MATH_KEYWORDS = [
    "where", "let", "given", "formula", "equation",
    "loss function", "cost function", "gradient", "derivative",
    "integral", "summation", "probability", "expected value",
    "variance", "distribution", "convergence", "divergence",
    "hypothesis", "likelihood", "posterior", "prior",
    "objective function", "optimization", "minimize", "maximize",
    "regression", "covariance", "eigenvalue", "eigenvector",
]

# Greek letter names when adjacent to math context
_GREEK_SPELLED = re.compile(
    r"\b(theta|sigma|lambda|alpha|beta|epsilon|delta|gamma|phi|omega|mu|pi|rho|tau|eta|nu|xi|zeta)\b",
    re.IGNORECASE,
)

# Mathematical notation patterns
_MATH_NOTATION = re.compile(
    r"(?:"
    r"[a-zA-Z]\([a-zA-Z][,|]"           # f(x, p(x|y
    r"|[a-zA-Z]\([a-zA-Z]\)"             # f(x)
    r"|O\([a-zA-Z0-9 ]+\)"              # O(n), O(log n)
    r"|\^[{0-9]"                          # superscript: x^2, x^{n}
    r"|_[{0-9a-zA-Z]"                    # subscript: x_i, x_{ij}
    r"|\\frac|\\sum|\\int|\\prod"        # LaTeX commands already in text
    r"|\\partial|\\nabla|\\infty"
    r"|\d+\s*[/]\s*\d+"                  # fractions: 1/2
    r"|=\s*\d"                            # assignment/equation with number
    r")",
    re.IGNORECASE,
)


def _detect_math(chunk_text: str) -> tuple[bool, list[str]]:
    """
    Layer 1: Fast regex scan for math signals.

    Returns:
        (has_math, list_of_signals) — signals is human-readable for logging.
    """
    signals: list[str] = []

    # Check for Greek Unicode characters
    found_greek = [ch for ch in chunk_text if ch in _GREEK_UNICODE]
    if found_greek:
        unique = set(found_greek)
        signals.append(f"Greek Unicode: {', '.join(sorted(unique)[:5])}")

    # Check for math operator Unicode characters
    found_ops = [ch for ch in chunk_text if ch in _MATH_OPERATORS]
    if found_ops:
        unique = set(found_ops)
        signals.append(f"Math operators: {', '.join(sorted(unique)[:5])}")

    # Check for spelled-out Greek letters near math context
    lower_text = chunk_text.lower()
    greek_matches = _GREEK_SPELLED.findall(chunk_text)
    if greek_matches:
        # Only count if there's also a math keyword nearby
        has_math_kw = any(kw in lower_text for kw in _MATH_KEYWORDS)
        if has_math_kw:
            signals.append(f"Spelled Greek + math context: {', '.join(set(greek_matches)[:3])}")

    # Check for math keywords
    found_kw = [kw for kw in _MATH_KEYWORDS if kw in lower_text]
    if len(found_kw) >= 2:
        signals.append(f"Math keywords: {', '.join(found_kw[:4])}")

    # Check for notation patterns
    notation_matches = _MATH_NOTATION.findall(chunk_text)
    if notation_matches:
        signals.append(f"Math notation patterns: {len(notation_matches)} found")

    # Threshold: need at least 2 signals to fire, or 1 strong signal
    # (Greek Unicode or Math operators are strong by themselves)
    strong_signal = bool(found_greek) or bool(found_ops)
    has_math = strong_signal or len(signals) >= 2

    return has_math, signals


# =============================================================================
# LAYER 2 — EXTRACTION (Ollama LLM)
# =============================================================================

_EXTRACTION_PROMPT = """You are a LaTeX math extractor for educational content.

Given this educational text chunk, extract the key mathematical equations and expressions.

RULES:
1. Write each equation as valid LaTeX math mode syntax
2. Do NOT include $ signs, \\[ \\], or \\begin{equation} wrappers — return the inner expression only
3. Do NOT invent equations that are not present or clearly implied in the text
4. Return MAXIMUM 3 equations — only the most important ones
5. If the math is purely symbolic (like O(n) complexity notation) include it only if it adds educational value
6. For inline expressions that are part of a sentence, set display to false
7. For standalone important equations that deserve their own line, set display to true

Text chunk:
{chunk_text}

Return ONLY valid JSON, no other text:
{{
  "equations": [
    {{"latex": "inner LaTeX expression only", "label": "short human-readable name", "display": true or false}},
    ...
  ]
}}

If there are no meaningful equations to extract, return: {{"equations": []}}"""


def _call_ollama(
    chunk_text: str,
    ollama_host: str | None = None,
    ollama_model: str | None = None,
    api_key: str | None = None,
) -> list[dict[str, Any]] | None:
    """
    Layer 2: Call Ollama to extract LaTeX equations from text.

    Returns list of raw equation dicts, or None on failure.
    """
    import os
    host = (ollama_host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
    model = ollama_model or os.getenv("OLLAMA_MODEL", "llama3")
    key = api_key or os.getenv("OLLAMA_API_KEY")

    # Truncate very long chunks to keep prompt size sane
    truncated = chunk_text[:2000]

    user_prompt = _EXTRACTION_PROMPT.format(chunk_text=truncated)

    url = f"{host}/api/chat"
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.1,
            "top_p": 0.9,
        },
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        text = result.get("message", {}).get("content", "")
        parsed = extract_json_from_response(text)

        if parsed and "equations" in parsed and isinstance(parsed["equations"], list):
            logger.info(
                "math_extractor_llm_success: equations_returned=%d",
                len(parsed["equations"]),
            )
            return parsed["equations"]

        logger.warning("math_extractor_llm_no_equations: response=%s", text[:200])
        return None

    except requests.RequestException as e:
        logger.warning("math_extractor_llm_request_failed: %s", str(e))
        return None
    except Exception as e:
        logger.warning("math_extractor_llm_unexpected_error: %s", str(e))
        return None


# =============================================================================
# LAYER 3 — VALIDATION (pylatexenc)
# =============================================================================

def _validate_latex(latex_str: str) -> bool:
    """
    Layer 3: Validate a LaTeX string using pylatexenc.

    Returns True if the expression is parseable, False otherwise.
    Falls through silently if pylatexenc is not installed.
    """
    try:
        from pylatexenc.latex2text import LatexNodes2Text
        LatexNodes2Text().latex_to_text(latex_str)
        return True
    except ImportError:
        # pylatexenc not available — accept the string unvalidated
        return True
    except Exception:
        # Parsing failed — this LaTeX is invalid
        return False


# =============================================================================
# PUBLIC INTERFACE
# =============================================================================

def extract_math(
    chunk_text: str,
    ollama_host: str | None = None,
    ollama_model: str | None = None,
    api_key: str | None = None,
) -> list[EquationItem] | None:
    """
    Extract mathematical equations from a text chunk.

    Three-layer pipeline:
    1. Detection  — regex scan for math signals (skip if none found)
    2. Extraction — LLM call to produce LaTeX
    3. Validation — pylatexenc parse check

    Args:
        chunk_text: Raw text chunk from PDF
        ollama_host: Ollama API host (falls back to env OLLAMA_HOST)
        ollama_model: Model name (falls back to env OLLAMA_MODEL)
        api_key: API key for cloud Ollama (falls back to env OLLAMA_API_KEY)

    Returns:
        List of EquationItem if math detected and extracted.
        None if no math detected or extraction failed.
        Never raises exceptions.
    """
    try:
        # Layer 1: Detection
        has_math, signals = _detect_math(chunk_text)

        if not has_math:
            logger.debug("math_extractor_no_math_detected")
            return None

        logger.info(
            "math_extractor_detection_fired: signals=%s",
            "; ".join(signals),
        )

        # Layer 2: LLM Extraction
        raw_equations = _call_ollama(
            chunk_text,
            ollama_host=ollama_host,
            ollama_model=ollama_model,
            api_key=api_key,
        )

        if not raw_equations:
            logger.info("math_extractor_no_equations_extracted")
            return None

        # Layer 3: Validation
        validated: list[EquationItem] = []
        for eq in raw_equations[:3]:  # Enforce max 3
            latex = eq.get("latex", "")
            label = eq.get("label", "equation")
            display = eq.get("display", True)

            if not latex or not isinstance(latex, str):
                continue

            # Strip any $ wrappers the LLM might have added
            latex = latex.strip().strip("$").strip()

            if _validate_latex(latex):
                validated.append(EquationItem(
                    latex=latex,
                    label=label,
                    display=bool(display),
                ))
            else:
                logger.info(
                    "math_extractor_validation_failed: latex=%s",
                    latex[:80],
                )

        logger.info(
            "math_extractor_complete: detected=%d validated=%d",
            len(raw_equations),
            len(validated),
        )

        return validated if validated else None

    except Exception as e:
        logger.warning("math_extractor_unexpected_error: %s", str(e))
        return None
