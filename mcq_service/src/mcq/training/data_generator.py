"""Training data generator — multi-threaded Ollama pipeline for QG/DG pairs.

Generates raw MCQ training data by calling Ollama to produce complete MCQ
objects (question + correct answer + 3 distractors) for each chunk sampled
with weighted mastery/score_category distributions.  Workers write results
thread-safely to a single JSONL output file.

Synthetic chunks (replacing the removed Scipy PDF) are generated on demand
from clean, book-agnostic CS educational paragraphs via ``generate_synthetic_chunks``.
All chunks — PDF-sourced and synthetic alike — pass through ``sanitize_chunk``
before being sent to the teacher LLM.

Usage::

    python -m mcq.training.data_generator \\
        --books data/raw_books \\
        --output data/mcq_training/mcq_raw.jsonl \\
        --workers 4
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import random
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from dotenv import load_dotenv
from tqdm import tqdm

# Load .env from mcq_service root (two levels above this file's src/mcq/training/)
_ENV_PATH = Path(__file__).resolve().parents[4] / ".env"
if not _ENV_PATH.exists():
    _ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)

logger = structlog.get_logger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# NINE-KEY PIPELINE ARCHITECTURE
# ═══════════════════════════════════════════════════════════════════════════════
#
# KEY ASSIGNMENT (hard-coded — do not swap roles):
#   GENERATION_KEYS  = [key_1, key_2, key_3, key_4]   — primary generation workers
#   FALLBACK_KEYS    = [key_8, key_9]                  — cycling fallback on hard failure
#   JUDGE_B_KEY      = key_5                           — personalization judge (20B)
#   JUDGE_C_KEY      = key_6                           — distractor quality judge (20B)
#   JUDGE_D_KEY      = key_7                           — factual correctness judge (20B)
#
# GENERATION_MODEL = small model (speed); JUDGE_MODEL = 20B model (accuracy).
# NEVER swap: do not use 20B for generation or small for judging.
# ═══════════════════════════════════════════════════════════════════════════════

# ── Key resolution — each role has a named env var ──────────────────────────
GENERATION_KEYS: list[str] = [
    k for k in [
        os.getenv("OLLAMA_API_KEY_1"),
        os.getenv("OLLAMA_API_KEY_2"),
        os.getenv("OLLAMA_API_KEY_3"),
        os.getenv("OLLAMA_API_KEY_4"),
    ] if k
]
FALLBACK_KEYS: list[str] = [
    k for k in [
        os.getenv("OLLAMA_API_KEY_8"),
        os.getenv("OLLAMA_API_KEY_9"),
    ] if k
]
JUDGE_B_KEY: str | None = os.getenv("OLLAMA_API_KEY_5")
JUDGE_C_KEY: str | None = os.getenv("OLLAMA_API_KEY_6")
JUDGE_D_KEY: str | None = os.getenv("OLLAMA_API_KEY_7")

# Model names — set via env vars with safe defaults
GENERATION_MODEL: str = os.getenv("GENERATION_MODEL", os.getenv("OLLAMA_MODEL", "qwen3:7b"))
JUDGE_MODEL:      str = os.getenv("JUDGE_MODEL", "qwen3:20b")

# ── Unified CONFIG dict — preserved for internal use ────────────────────────
CONFIG = {
    # Aggregate key lists for KeyPool (used by generation workers)
    "api_keys_primary": GENERATION_KEYS,
    "api_keys_backup":  FALLBACK_KEYS,
    "ollama_host": os.getenv("OLLAMA_HOST", "https://ollama.com"),
    "model": GENERATION_MODEL,
    "output": "data/mcq_training/mcq_raw.jsonl",
    "raw_books_dir": "data/raw_books",
    "chunk_size": 800,
    "chunk_overlap": 80,
    "max_retries": 3,
    "retry_delay": 2,
    "num_workers": 4,
    # How many consecutive API errors on a key before marking it failed
    "key_fail_threshold": 3,
    # Seconds to wait before re-trying a failed key
    "key_cooldown": 60,
    # Books to exclude from PDF loading (noisy, code-heavy, or book-reference-polluted)
    "excluded_books": {
        "ScipyLectures-simple.pdf",
    },
    # How many synthetic chunks to generate when the generator is invoked
    "n_synthetic_chunks": 180,
    # Evaluation queue capacity — 0 = unbounded so generation workers never
    # block waiting for judges to drain the queue.
    "eval_queue_maxsize": 0,
}

# ── Data targets (Action 5) ──────────────────────────────────────────────────
# Because judges reject ~50%, we generate 2× the clean target.
DATA_TARGETS = {
    # QG
    "qg_raw_target":   12_000,   # raw generations before judging
    "qg_clean_target":  6_000,   # post-judge accepted samples
    # DG — 3 examples per QG sample
    "dg_raw_target":   36_000,
    "dg_clean_target": 18_000,
    # Stratified cap within any type: no (mastery × score_cat) combo > 40%
    "max_combo_pct_within_type": 0.40,
    # Mandatory minimums in the FINAL accepted dataset
    "min_very_weak_novice_4a":        150,
    "min_very_weak_intermediate_4a":  150,
    "min_very_weak_expert_4a":        150,
    "min_novice_intermediate_pairs":  200,
    "min_code_type_each":             150,   # types 1, 2, 3
    "min_conceptual_type_each":       200,   # types 4a, 4b, 4c, 4d, 4e
}

MASTERY_WEIGHTS = {
    "Novice": 0.45,
    "Intermediate": 0.35,
    "Expert": 0.20,
}

SCORE_CATEGORY_WEIGHTS = {
    "very_weak": 0.35,
    "weak": 0.25,
    "moderate": 0.25,
    "strong": 0.15,
}

# Type escalation map for misconception-context examples
_ESCALATION_MAP = {
    "4a": "4b",
    "4b": "4c",
    "4c": "4d",
    "4d": "4e",
    "4e": "4e",
    "1": "2",
    "2": "3",
    "3": "3",
}

# ═══════════════════════════════════════════════════════════════════════════════
# TASK CONSTRUCTION
# ═══════════════════════════════════════════════════════════════════════════════


def _chunk_hash(text: str) -> str:
    """Compute a short hash for a chunk for deduplication."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:8]


def _weighted_sample(weights: dict[str, float]) -> str:
    """Sample one key from a weighted distribution."""
    keys = list(weights.keys())
    vals = list(weights.values())
    return random.choices(keys, weights=vals, k=1)[0]


# Compiled once at import time for performance.
_CODE_PRINT      = re.compile(r'\bprint\s*\(')
_CODE_REPL       = re.compile(r'^>>>\s*\S', re.MULTILINE)
_CODE_FUNC_DEF   = re.compile(r'\bdef\s+\w+\s*\(')
_CODE_IMPORT     = re.compile(r'^(?:import|from)\s+\w+', re.MULTILINE)
_CODE_FOR        = re.compile(r'\bfor\s+\w+\s+in\s+(?:range\s*\(|enumerate\s*\(|zip\s*\(|\w+)')
_CODE_ASSIGNMENT = re.compile(r'^\w[\w.]*\s*=\s*(?:\[|\{|["\']|\d)', re.MULTILINE)
_CODE_FENCE      = re.compile(r'```')
_CODE_METHOD     = re.compile(
    r'\.\b(?:append|extend|insert|remove|pop|sort|reverse|clear|copy|update|get|'
    r'keys|values|items|split|join|strip|replace|find|format|encode|decode|'
    r'read|write|close|predict|fit|transform|reshape|astype|head|tail)\s*\('
)
_CODE_SYNTAX_DESC = re.compile(
    r'(?:to do|the syntax (?:for|is)|use the following|'
    r'in python[,\s]+(?:use|you can|call|write)|'
    r'(?:complete|fill in|implement)\s+the\s+(?:function|code|following))',
    re.IGNORECASE,
)
_SIG_DISTINCTION  = re.compile(
    r'\b(?:unlike|whereas|compared to|the difference between|'
    r'in contrast|on the other hand|distinguishes?|versus|vs\.?)\b'
)
_SIG_APPLICATION  = re.compile(
    r'\b(?:which would you use|best approach|most appropriate|'
    r'in this scenario|given that you need|use case|when to use|'
    r'suitable for|ideal for|best model|real[- ]world)\b'
)
_SIG_REASONING    = re.compile(
    r'\b(?:trade.off|time complexity|space complexity|amortized|'
    r'consequence|guarantees?|implication|therefore|derive|justify)\b|o\([^)]+\)'
)
_SIG_MISCONCEPTION = re.compile(
    r'\b(?:common mistake|misconception|students?\s+(?:often|usually|commonly)|'
    r'contrary to|a student claims|is it true|incorrectly|wrongly)\b'
)


def _detect_content_eligible_types(text: str) -> list[str]:
    """Return the question types appropriate for this chunk's actual content.

    Pass 1 — code signals determine whether Types 1, 2, 3 are viable:
      * Type 2 needs a runnable snippet with traceable output (print / REPL).
      * Type 1 needs method calls, function signatures, or import-level APIs.
      * Type 3 needs code present OR a description of how to write code.

    Pass 2 — conceptual signal words bias toward specific 4x subtypes.
    Type 4a is always included as a safe fallback for any chunk.

    The caller intersects the result with MASTERY_TYPE_ELIGIBILITY.
    """
    eligible: set[str] = {"4a"}  # universal fallback

    # ── Pass 1: code signals ──────────────────────────────────────────────
    has_print      = bool(_CODE_PRINT.search(text))
    has_repl       = bool(_CODE_REPL.search(text))
    has_func_def   = bool(_CODE_FUNC_DEF.search(text))
    has_import     = bool(_CODE_IMPORT.search(text))
    has_for        = bool(_CODE_FOR.search(text))
    has_assignment = bool(_CODE_ASSIGNMENT.search(text))
    has_fence      = bool(_CODE_FENCE.search(text))
    has_method     = bool(_CODE_METHOD.search(text))
    has_syntax_desc = bool(_CODE_SYNTAX_DESC.search(text))

    is_code_chunk = any([
        has_print, has_repl, has_func_def, has_import,
        has_for, has_method, has_fence, has_assignment,
    ])

    # Type 2 — Code Output: needs runnable code with a traceable output
    if has_print or has_repl:
        eligible.add("2")

    # Type 1 — Method/API: needs method calls, function defs, or imports
    if has_method or has_func_def or has_import:
        eligible.add("1")

    # Type 3 — Code Completion: code present OR explicit "how to write" description
    if is_code_chunk or has_syntax_desc:
        eligible.add("3")

    # ── Pass 2: conceptual signal words ──────────────────────────────────
    t = text.lower()

    if _SIG_DISTINCTION.search(t):
        eligible.add("4b")

    if _SIG_APPLICATION.search(t):
        eligible.add("4c")

    if _SIG_REASONING.search(t):
        eligible.add("4d")

    if _SIG_MISCONCEPTION.search(t):
        eligible.add("4e")

    return list(eligible)


# Patterns that indicate a line is a PDF header/footer artifact, not content.
# These are stripped from the beginning and end of every chunk before sending
# to the model so it doesn't waste tokens on page noise.
_HEADER_PATTERNS = [
    # "Scipy lecture notes, Edition 2022.1"  / "Release 3.0"  etc.
    r"^.{0,80}(lecture notes|edition|release)\s+[\d.]+",
    # "(continued from previous page)"
    r"^\(continued from previous page\)",
    # Bare page number lines: "116"
    r"^\d+$",
    # Section/chapter header ending in a page number:
    #   "4.5. Some exercises 116"  or  "4.4 Generative Models for Classification 149"
    r"^[\d]+[\d.]*\s+.{1,80}\s+\d{1,4}$",
    # All-caps section header + page number: "11.9. EXERCISES 143"
    r"^\d+\.\d+\.\s+[A-Z ]+\s+\d+$",
    # Chapter / section header artifacts: "CHAPTER 14. ..."
    r"^(CHAPTER|SECTION|APPENDIX)\s+[\d.]+",
]
import re as _re
_HEADER_RE = _re.compile("|".join(_HEADER_PATTERNS), _re.IGNORECASE | _re.MULTILINE)


def _clean_chunk_text(text: str, book_stem: str) -> str:
    """Strip PDF header/footer artifacts from chunk text.

    Removes:
    - Lines that match any ``_HEADER_PATTERNS`` (edition lines, page numbers, etc.)
    - Lines that *are* (or start with) the book title (case-insensitive substring match)
    - Leading/trailing blank lines after cleaning
    """
    book_words = book_stem.lower().split()
    lines = text.splitlines()
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Skip header-pattern lines
        if _HEADER_RE.match(stripped):
            continue
        # Skip lines that are just the book title / contain most of its words
        if len(book_words) >= 3:
            line_lower = stripped.lower()
            matches = sum(1 for w in book_words if w in line_lower)
            if matches >= max(3, len(book_words) - 1):
                continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


# ═══════════════════════════════════════════════════════════════════════════════
# CHUNK SANITIZER
# ═══════════════════════════════════════════════════════════════════════════════

# Compiled patterns for sanitize_chunk — applied to every chunk, PDF and synthetic.
_SANITIZE_FIGURE_RE = re.compile(
    r'(?i)'
    r'(?:figure|fig\.?)\s*[\d.]+'
    r'|\bsee figure\b'
    r'|\bas shown above\b'
    r'|\bthe diagram above\b'
    r'|\bthe table below\b',
)
_SANITIZE_SOURCE_RE = re.compile(
    r'(?i)'
    r'from the \w[^.,]{0,40} lecture notes'
    r'|\bin this book\b'
    r'|\bthe author\b'
    r'|\bthe text states\b'
    r'|\bthe passage\b'
    r'|\bthis chapter\b'
    r'|\bthis section\b',
)
_SANITIZE_FORWARD_RE = re.compile(
    r'(?i)'
    r'as discussed in chapter \w+'
    r'|\bwe saw earlier\b'
    r'|\bin the next section\b'
    r'|\bpreviously\b'
    r'|\blater in this\b',
)
# Unicode box-drawing characters U+2500–U+257F
_SANITIZE_BOX_CHARS_RE = re.compile(r'[\u2500-\u257f]+')
# A line consisting entirely of box-drawing chars and whitespace
_SANITIZE_BOX_LINE_RE = re.compile(r'^[\u2500-\u257f\s]+$')
# PDF page-number prefix at start of line: "55 " with no other digits following
_SANITIZE_PAGE_PREFIX_RE = re.compile(r'^\d{1,4} +(?=[A-Z])', re.MULTILINE)


def sanitize_chunk(text: str) -> str | None:
    """Strip book-specific artifacts from any chunk before sending to the teacher LLM.

    Applies to both real PDF chunks and synthetic chunks as a safety net.

    Strips:
    - Figure/diagram references
    - Book/source/passage references
    - Forward/backward cross-references
    - Code blocks longer than 10 lines (truncated with note)
    - PDF extraction artifacts: page-number prefixes, header repetitions
    - Unicode box-drawing characters (decorative PDF separators)
    - Normalises whitespace

    Returns
    -------
    str or None
        Cleaned text, or None if the cleaned text is fewer than 40 words
        (too little content for a meaningful question).
    """
    if not text or not text.strip():
        return None

    lines = text.splitlines()
    result_lines: list[str] = []
    in_code_block = False
    code_block_lines: list[str] = []

    for line in lines:
        stripped = line.strip()

        # ── Box-drawing lines: drop entirely ──────────────────────────
        if _SANITIZE_BOX_LINE_RE.match(stripped):
            continue

        # ── Track fenced code blocks ───────────────────────────────────
        if stripped.startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_block_lines = [line]
            else:
                # Closing fence
                in_code_block = False
                code_block_lines.append(line)
                # Truncate if too long
                content_lines = code_block_lines[1:-1]  # strip fence markers
                if len(content_lines) > 10:
                    trimmed = code_block_lines[:11]  # opening fence + 10 content lines
                    trimmed.append("# ... [code truncated — focus on the concept]")
                    trimmed.append("```")
                    result_lines.extend(trimmed)
                else:
                    result_lines.extend(code_block_lines)
                code_block_lines = []
            continue

        if in_code_block:
            code_block_lines.append(line)
            continue

        # ── Strip page-number prefixes ("55 Some Heading") ─────────────
        line = _SANITIZE_PAGE_PREFIX_RE.sub("", line)
        stripped = line.strip()
        if not stripped:
            result_lines.append("")
            continue

        # ── Remove inline box-drawing chars ────────────────────────────
        stripped = _SANITIZE_BOX_CHARS_RE.sub("", stripped).strip()
        if not stripped:
            continue

        # ── Remove figure references ────────────────────────────────────
        stripped = _SANITIZE_FIGURE_RE.sub("", stripped).strip()

        # ── Remove source/book references ───────────────────────────────
        stripped = _SANITIZE_SOURCE_RE.sub("", stripped).strip()

        # ── Remove forward/backward references ─────────────────────────
        stripped = _SANITIZE_FORWARD_RE.sub("", stripped).strip()

        if stripped:
            result_lines.append(stripped)

    # Flush any unterminated code block
    if in_code_block and code_block_lines:
        content_lines = code_block_lines[1:]
        if len(content_lines) > 10:
            trimmed = code_block_lines[:11]
            trimmed.append("# ... [code truncated — focus on the concept]")
            result_lines.extend(trimmed)
        else:
            result_lines.extend(code_block_lines)

    # Normalise: collapse runs of blank lines to one
    cleaned_lines: list[str] = []
    prev_blank = False
    for ln in result_lines:
        is_blank = not ln.strip()
        if is_blank and prev_blank:
            continue
        cleaned_lines.append(ln)
        prev_blank = is_blank

    cleaned = "\n".join(cleaned_lines).strip()

    # Discard if too short after cleaning
    if len(cleaned.split()) < 40:
        return None

    return cleaned


# ═══════════════════════════════════════════════════════════════════════════════
# SYNTHETIC CHUNK GENERATOR
# ═══════════════════════════════════════════════════════════════════════════════

# Topic distribution for synthetic chunk generation.
# Tuple format: (topic_tag, subtopics_list)
# Subtopics are cycled through evenly to fill the per-topic chunk quota.
_SYNTHETIC_TOPIC_DISTRIBUTION: list[tuple[str, list[str]]] = [
    ("data_structures", [
        "arrays",
        "linked lists",
        "binary trees",
        "general trees",
        "graphs",
        "hash tables",
        "heaps",
        "tries",
        "stacks",
        "queues",
    ]),
    ("algorithms", [
        "sorting algorithms",
        "binary search",
        "recursion",
        "dynamic programming",
        "greedy algorithms",
        "breadth-first search (BFS)",
        "depth-first search (DFS)",
        "divide and conquer",
    ]),
    ("complexity", [
        "Big-O notation",
        "time vs space tradeoffs",
        "amortized analysis",
        "best average and worst case complexity",
    ]),
    ("python_fundamentals", [
        "Python functions and scope",
        "mutability and pass-by-object-reference in Python",
        "Python generators",
        "list comprehensions and dict comprehensions",
        "Python decorators",
    ]),
    ("oop_concepts", [
        "inheritance in object-oriented programming",
        "polymorphism",
        "encapsulation",
        "composition vs inheritance",
        "abstraction and method resolution order",
    ]),
    ("functional_concepts", [
        "map filter and reduce",
        "closures in Python",
        "higher-order functions",
        "lambda expressions",
        "immutability in functional programming",
    ]),
    ("error_handling", [
        "exceptions and try/except in Python",
        "custom exception classes",
        "the finally block and cleanup",
        "context managers and the with statement",
    ]),
    ("file_and_io", [
        "file handling in Python",
        "serialization with JSON and pickle",
        "buffering and file modes",
    ]),
    ("basic_ml_concepts", [
        "overfitting and underfitting",
        "bias-variance tradeoff",
        "cross-validation",
        "loss functions",
        "gradient descent",
        "regularization in machine learning",
    ]),
    ("statistics_basics", [
        "mean variance and standard deviation",
        "probability distributions",
        "hypothesis testing",
        "correlation vs causation",
        "sampling and sampling bias",
    ]),
]


def generate_synthetic_chunks(
    n_chunks: int,
    api_keys: list[str],
    cache_path: str | None = None,
) -> list[dict]:
    """Generate clean, reference-free CS educational paragraphs via the teacher LLM.

    All API keys run in parallel — one persistent worker thread per key.  Tasks
    are drawn from a shared queue so every key stays busy until all targets are
    processed.  Each successful chunk is written to ``cache_path`` immediately
    (with a threading lock) so a Ctrl-C loses at most one in-flight request per
    key.

    On restart the cache is loaded; already-generated chunks are skipped by
    count (same deterministic shuffle seed) so the function resumes from where
    it left off.

    Parameters
    ----------
    n_chunks :
        Target number of synthetic chunks to generate.
    api_keys :
        API keys to run in parallel.  One thread is spawned per key; all threads
        work simultaneously on different tasks pulled from a shared queue.
    cache_path :
        Optional path to a JSONL file.  Chunks are appended as they complete.
        If the file exists on startup its contents are loaded and those targets
        are skipped.  Pass ``None`` to disable caching.

    Returns
    -------
    list[dict]
        Each dict has ``text``, ``topic``, ``book`` keys compatible with the
        standard chunk format expected by ``_build_tasks``.
    """
    if not api_keys:
        logger.error("generate_synthetic_chunks_no_keys")
        return []

    # ── Load cache (resume support) ──────────────────────────────────────
    result_lock: threading.Lock = threading.Lock()
    synthetic_chunks: list[dict] = []
    seen_hashes: set[str] = set()

    cache_file: Path | None = Path(cache_path) if cache_path else None
    if cache_file and cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as _cf:
            for _line in _cf:
                _line = _line.strip()
                if not _line:
                    continue
                try:
                    _entry = json.loads(_line)
                    _h = _chunk_hash(_entry.get("text", ""))
                    if _h not in seen_hashes:
                        seen_hashes.add(_h)
                        synthetic_chunks.append(_entry)
                except (json.JSONDecodeError, KeyError):
                    pass
        if synthetic_chunks:
            print(
                f"  Synthetic chunk cache: {len(synthetic_chunks)} chunks loaded "
                f"from {cache_file} (resuming)"
            )
            if len(synthetic_chunks) >= n_chunks:
                print("  Cache already at target. Skipping generation.")
                return synthetic_chunks

    already_have = len(synthetic_chunks)
    still_needed = n_chunks - already_have

    # ── Build target list ────────────────────────────────────────────────
    n_topics = len(_SYNTHETIC_TOPIC_DISTRIBUTION)
    base_per_topic = n_chunks // n_topics
    remainder = n_chunks % n_topics

    targets: list[tuple[str, str]] = []
    for i, (tag, subtopics) in enumerate(_SYNTHETIC_TOPIC_DISTRIBUTION):
        count = base_per_topic + (1 if i < remainder else 0)
        for j in range(count):
            targets.append((tag, subtopics[j % len(subtopics)]))

    rng = random.Random(99)
    rng.shuffle(targets)

    # Skip already-cached targets (same deterministic seed = same order)
    targets_remaining = targets[already_have:]

    n_keys = len(api_keys)
    logger.info(
        "synthetic_chunk_generation_start",
        target=n_chunks,
        cached=already_have,
        still_needed=still_needed,
        actual_targets=len(targets_remaining),
        parallel_keys=n_keys,
    )
    print(
        f"\n  Generating {len(targets_remaining)} synthetic chunks in parallel "
        f"({n_keys} keys, need {still_needed} more, have {already_have} cached)..."
    )

    # ── One Ollama client per key ─────────────────────────────────────────
    clients = [_make_ollama_client(k) for k in api_keys]

    # ── Shared task queue — all threads drain this ────────────────────────
    task_queue: queue.Queue = queue.Queue()
    for item in targets_remaining:
        task_queue.put(item)

    # ── Open cache file for appending (shared across threads via lock) ────
    cache_fh = open(cache_file, "a", encoding="utf-8") if cache_file else None

    # ── Progress bar driven from worker threads ───────────────────────────
    pbar = tqdm(
        total=len(targets_remaining),
        desc="Synthetic chunks",
        unit="chunk",
        dynamic_ncols=True,
        colour="cyan",
    )

    def _syn_worker(key_idx: int, client: Any) -> None:
        """Worker pinned to one API key — keeps pulling tasks until queue empty."""
        while True:
            try:
                tag, subtopic = task_queue.get_nowait()
            except queue.Empty:
                return  # nothing left — this thread is done

            prompt = (
                f"Write a self-contained educational paragraph (100-150 words) about "
                f"the computer science concept: {subtopic}\n\n"
                "Rules:\n"
                "- No figure references, no 'as shown above', no 'in this example'\n"
                "- No reference to any specific book, lecture, author, or publication\n"
                "- No 'we', no 'the student', no 'you will learn'\n"
                "- State the concept directly and precisely\n"
                "- Include one concrete illustrative sentence\n"
                "- End with a consequence or implication of the concept\n\n"
                "Output only the paragraph, nothing else."
            )

            try:
                response = client.chat(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.8,
                    timeout_override=60,
                )

                raw_text: str = ""
                if isinstance(response, str):
                    raw_text = response
                elif isinstance(response, dict):
                    raw_text = (
                        response.get("content")
                        or response.get("text")
                        or response.get("message", {}).get("content", "")
                        or ""
                    )

                raw_text = raw_text.strip()
                if not raw_text:
                    logger.warning(
                        "synthetic_chunk_empty_response",
                        subtopic=subtopic, key_idx=key_idx,
                    )
                    task_queue.task_done()
                    pbar.update(1)
                    continue

                cleaned = sanitize_chunk(raw_text)
                if cleaned is None:
                    logger.warning(
                        "synthetic_chunk_too_short_after_sanitize",
                        subtopic=subtopic, key_idx=key_idx,
                    )
                    task_queue.task_done()
                    pbar.update(1)
                    continue

                chunk_h = _chunk_hash(cleaned)
                entry = {"text": cleaned, "topic": tag, "book": f"synthetic:{tag}"}

                with result_lock:
                    if chunk_h not in seen_hashes:
                        seen_hashes.add(chunk_h)
                        synthetic_chunks.append(entry)
                        if cache_fh:
                            cache_fh.write(json.dumps(entry) + "\n")
                            cache_fh.flush()
                    else:
                        logger.debug("synthetic_chunk_duplicate", subtopic=subtopic)

            except Exception as exc:
                logger.warning(
                    "synthetic_chunk_failed",
                    subtopic=subtopic,
                    key_idx=key_idx,
                    error=str(exc)[:120],
                )
            finally:
                task_queue.task_done()
                pbar.update(1)

    # ── Launch all key-threads simultaneously ─────────────────────────────
    try:
        with ThreadPoolExecutor(max_workers=n_keys, thread_name_prefix="syn") as pool:
            futures = [
                pool.submit(_syn_worker, idx, clients[idx])
                for idx in range(n_keys)
            ]
            for fut in as_completed(futures):
                exc = fut.exception()
                if exc:
                    logger.error(
                        "synthetic_worker_thread_crashed",
                        error=str(exc)[:200],
                    )
    finally:
        pbar.close()
        if cache_fh:
            cache_fh.close()

    logger.info(
        "synthetic_chunk_generation_done",
        requested=n_chunks,
        generated=len(synthetic_chunks),
    )
    print(
        f"  Synthetic chunks done: {len(synthetic_chunks)} / {n_chunks} target "
        f"({already_have} from cache + {len(synthetic_chunks) - already_have} new)"
    )
    return synthetic_chunks

def _load_chunks_from_pdfs(books_dir: str, chunk_size: int, chunk_overlap: int) -> list[dict]:
    """Load and chunk all PDFs from the books directory.

    Books are processed in **alphabetical order** so the task queue always
    starts from the first book, first chunk.  Chunk artifacts (headers,
    page numbers, edition lines) are stripped, then every chunk passes
    through ``sanitize_chunk`` to remove book-specific references.

    Books listed in ``CONFIG["excluded_books"]`` are skipped entirely.
    """
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    books_path = Path(books_dir)
    if not books_path.exists():
        logger.error("books_dir_not_found", path=books_dir)
        return []

    excluded = CONFIG.get("excluded_books", set())
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    all_chunks: list[dict] = []
    # Sort alphabetically for deterministic, book-ordered processing
    pdf_files = sorted(books_path.glob("*.pdf"), key=lambda p: p.name.lower())
    logger.info("found_pdf_files", count=len(pdf_files), dir=books_dir)

    for i, p in enumerate(pdf_files):
        if p.name in excluded:
            logger.info("book_excluded", index=i + 1, name=p.name)
            print(f"  Skipping excluded book: {p.name}")
            continue
        logger.info("book_order", index=i + 1, name=p.name)

    for pdf_path in pdf_files:
        if pdf_path.name in excluded:
            continue
        try:
            loader = PyPDFLoader(str(pdf_path))
            pages = loader.load()
            splits = splitter.split_documents(pages)
            book_stem = pdf_path.stem
            skipped = 0
            for doc in splits:
                raw_text = doc.page_content.strip()
                text = _clean_chunk_text(raw_text, book_stem)
                # Run through the full sanitizer — removes figure refs, source
                # refs, cross-refs, over-long code blocks, and box-drawing chars
                sanitized = sanitize_chunk(text)
                if sanitized is None:
                    skipped += 1
                    continue
                # Use the PDF filename stem as topic — ignore langchain's
                # metadata.topic which leaks page-level noise.
                all_chunks.append({
                    "text": sanitized,
                    "topic": book_stem,
                    "book": pdf_path.name,
                })
            if skipped:
                logger.info(
                    "pdf_chunks_sanitized_out",
                    book=pdf_path.name,
                    skipped=skipped,
                )
        except Exception:
            logger.exception("pdf_load_failed", path=str(pdf_path))

    logger.info("total_chunks_loaded", count=len(all_chunks))
    return all_chunks


def _build_tasks(
    chunks: list[dict],
    existing_hashes: set[str],
    balanced_types: bool = False,
) -> list[dict]:
    """Build generation tasks from chunks with content-aware type selection.

    For every chunk, ``_detect_content_eligible_types`` is called first to
    determine which question types are actually supported by the chunk's text
    (e.g. Type 2 requires a runnable snippet; pure-prose chunks are restricted
    to conceptual types).  That set is then intersected with the mastery-level
    ceiling from ``MASTERY_TYPE_ELIGIBILITY`` to get the final eligible pool.

    Parameters
    ----------
    chunks :
        Text chunks loaded from PDFs.
    existing_hashes :
        Chunk hashes already present in the output file (for resumability).
    balanced_types :
        If True, enforces equal quota per question type — each type gets
        ``len(eligible_chunks) // n_types`` tasks, assigned round-robin while
        respecting content eligibility.  If False (default), types are sampled
        randomly weighted by mastery × content eligibility.
    """
    mcq_src = str(Path(__file__).resolve().parent.parent.parent)
    if mcq_src not in sys.path:
        sys.path.insert(0, mcq_src)

    from mcq.question_types import MASTERY_TYPE_ELIGIBILITY, ALL_QUESTION_TYPES

    all_types: list[str] = sorted(set(ALL_QUESTION_TYPES))

    eligible = [
        c for c in chunks if _chunk_hash(c["text"]) not in existing_hashes
    ]

    tasks: list[dict] = []

    if balanced_types:
        # ── Balanced mode ────────────────────────────────────────────────
        # Round-robin across types but only assign a type when the chunk's
        # content actually supports it AND the quota hasn't been reached.
        quota = max(1, len(eligible) // len(all_types))
        type_counts: dict[str, int] = {t: 0 for t in all_types}
        type_cycle = all_types * ((len(eligible) // len(all_types)) + 2)
        type_idx = 0

        for chunk in eligible:
            content_types = set(_detect_content_eligible_types(chunk["text"]))

            # Find the next type that is under quota AND content-eligible
            assigned: str | None = None
            for _ in range(len(all_types) * 3):
                candidate = type_cycle[type_idx % len(type_cycle)]
                type_idx += 1
                if type_counts[candidate] < quota and candidate in content_types:
                    assigned = candidate
                    break

            if assigned is None:
                # Quotas full or no round-robin match — fall back to content pool
                pool = [t for t in all_types if t in content_types]
                assigned = random.choice(pool) if pool else "4a"

            type_counts[assigned] += 1
            qtype = assigned
            score_category = _weighted_sample(SCORE_CATEGORY_WEIGHTS)

            compatible_masteries = [
                m for m, types in MASTERY_TYPE_ELIGIBILITY.items()
                if qtype in types
            ]
            if compatible_masteries:
                # Filter MASTERY_WEIGHTS to only compatible levels, re-normalize
                filtered = {m: MASTERY_WEIGHTS[m] for m in compatible_masteries
                            if m in MASTERY_WEIGHTS}
                mastery = _weighted_sample(filtered) if filtered \
                    else random.choice(compatible_masteries)
            else:
                mastery = _weighted_sample(MASTERY_WEIGHTS)

            misconception_context = None
            if random.random() < 0.20:
                original_type = qtype
                qtype = _ESCALATION_MAP.get(qtype, qtype)
                misconception_context = (
                    f"student chose a wrong answer for a Type {original_type} "
                    f"question on this topic"
                )

            tasks.append({
                "text": chunk["text"],
                "topic": chunk.get("topic", "General"),
                "book": chunk.get("book", "unknown"),
                "chunk_hash": _chunk_hash(chunk["text"]),
                "mastery": mastery,
                "score_category": score_category,
                "question_type": qtype,
                "misconception_context": misconception_context,
            })

        logger.info(
            "tasks_built_balanced",
            total=len(tasks),
            quota_per_type=quota,
            type_counts=type_counts,
        )

    else:
        # ── Default mode ─────────────────────────────────────────────────
        # Mastery is sampled first, then the type is restricted to the
        # intersection of mastery-eligible and content-eligible types.
        for chunk in eligible:
            mastery = _weighted_sample(MASTERY_WEIGHTS)
            score_category = _weighted_sample(SCORE_CATEGORY_WEIGHTS)

            mastery_types = set(MASTERY_TYPE_ELIGIBILITY.get(mastery, ["4a"]))
            content_types = set(_detect_content_eligible_types(chunk["text"]))
            pool = list(mastery_types & content_types)
            if not pool:
                # Safety net: no overlap — relax content constraint
                pool = list(mastery_types)
            question_type = random.choice(pool)

            misconception_context = None
            if random.random() < 0.20:
                original_type = question_type
                question_type = _ESCALATION_MAP.get(question_type, question_type)
                misconception_context = (
                    f"student chose a wrong answer for a Type {original_type} "
                    f"question on this topic"
                )

            tasks.append({
                "text": chunk["text"],
                "topic": chunk.get("topic", "General"),
                "book": chunk.get("book", "unknown"),
                "chunk_hash": _chunk_hash(chunk["text"]),
                "mastery": mastery,
                "score_category": score_category,
                "question_type": question_type,
                "misconception_context": misconception_context,
            })

        logger.info(
            "tasks_built",
            total=len(tasks),
            skipped_existing=len(chunks) - len(eligible),
        )

    # Do NOT shuffle — tasks are in alphabetical-book, sequential-chunk order.
    return tasks


# ═══════════════════════════════════════════════════════════════════════════════
# OLLAMA CLIENT FACTORY
# ═══════════════════════════════════════════════════════════════════════════════


def _make_ollama_client(api_key: str, model: str | None = None):
    """Create an OllamaClient with a specific API key and optional model override.

    Parameters
    ----------
    api_key :
        The API key for the request.
    model :
        Model name.  Defaults to ``GENERATION_MODEL`` (small, fast).
        Pass ``JUDGE_MODEL`` to create a 20B judge client.
    """
    pathway_src = str(
        Path(__file__).resolve().parent.parent.parent.parent.parent / "course_pathway" / "src"
    )
    if pathway_src not in sys.path:
        sys.path.insert(0, pathway_src)

    from pathway.llm.naming import OllamaClient  # type: ignore

    return OllamaClient(
        host=CONFIG["ollama_host"],
        model=model or GENERATION_MODEL,
        api_key=api_key,
        max_retries=3,
        timeout=180,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PROMPT BUILDING
# ═══════════════════════════════════════════════════════════════════════════════


_PROMPT_CONTEXT_SCOPE = """\
CRITICAL INSTRUCTION — QUESTION SCOPE:
The student answering this question will NOT have access to:
- The source textbook or lecture notes
- Any figures, diagrams, or images referenced in the text
- Any specific code snippets from the chunk below

You MUST generate a question that tests the underlying CS concept
or principle described in the chunk — NOT a question about the
specific example, figure, or code that appears in the text.

BAD (never generate):
  "In the following code snippet from the Scipy lecture notes..."
  "According to the passage, what does Figure 3.2 show?"
  "As shown in the example above..."

GOOD (generate these instead):
  "What does the boxplot() function visualize?"
  "Which data structure provides O(1) average-case lookup time?"
  "What happens when a recursive function has no base case?"

The question must be answerable by any student who understands
the concept — even without having read this specific textbook."""


_PROMPT_CODE_LENGTH = """\
If your question needs to reference code, limit it to a MAXIMUM
of 5 lines. Never reproduce a full code block from the chunk in
your question stem. Prefer to describe what the code does in words."""


_PROMPT_SIGNAL_SEPARATION = """\
TWO SIGNALS — TWO DIFFERENT JOBS:

MASTERY LEVEL controls HOW you frame the question — vocabulary,
cognitive register, and distractor sophistication:

  Novice:
    - Vocabulary: everyday language matching the chunk exactly
    - Frame: "What is X?" / "What does X do?"
    - Distractors: clearly wrong to anyone who read carefully
    - No cross-concept reasoning required
    - Example: "What is a stack?"
    - Example distractor: a wrong but obviously unrelated answer

  Intermediate:
    - Vocabulary: standard CS terminology assumed known
    - Frame: connect two ideas or apply to a simple scenario
    - Distractors: require careful reasoning to eliminate
    - NEVER a pure definition (unless score_category overrides)
    - Example: "What is the difference between a stack and a queue?"
    - Example distractor: plausible-sounding but subtly wrong

  Expert:
    - Vocabulary: precise technical language, assume mastery
    - Frame: WHY it works, edge cases, tradeoffs
    - Distractors: sophisticated, plausible to partial knowers
    - Synthesis across concepts is appropriate
    - Example: "Why does a hash table degrade to O(n) lookup in
      the worst case?"
    - Example distractor: technically accurate but misses the point

SCORE CATEGORY controls HOW HARD the question is — difficulty
and whether mastery type is overridden:

  very_weak:
    - OVERRIDES mastery on TYPE ONLY — always generate Type 4a
    - Mastery still controls vocabulary and distractor sophistication
    - Even for Expert students: simple definition question
    - Distractors: easy to eliminate, student needs confidence
    - Goal: rebuild the foundation before anything else

  weak:
    - One cognitive level easier than mastery alone would suggest
    - An Intermediate student gets a Novice-difficulty question
    - Distractors: plausible but distinguishable with careful reading

  moderate:
    - Standard difficulty for the mastery level, no adjustment

  strong:
    - Hardest difficulty mastery allows
    - Distractors: as subtle and challenging as mastery permits

IMPORTANT: mastery and score_category are independent dimensions.
A Novice + strong student gets a hard Novice-framed question.
An Expert + very_weak student gets a Type 4a — but written with
Expert vocabulary, not dumbed-down language. Same type, different
register."""


_PROMPT_DISTRACTOR_LABELS = """\
Generate exactly 3 distractors, each targeting a DIFFERENT
misconception. Label each:
  - wrong_concept: student confuses this with a different concept
  - wrong_application: student understands but applies incorrectly
  - partial_knowledge: student knows part but misses a key detail

Each distractor must be meaningfully different from the other two
and from the correct answer. Output one distractor per category."""


def _build_very_weak_override_block(question_type: str) -> str:
    """Return the very_weak hard override injection block.

    Only injected when score_category is 'very_weak'.
    """
    return (
        "score_category is very_weak. You MUST generate a Type 4a "
        "(Definition/Recall) question REGARDLESS of whether the chunk "
        "contains code. If the chunk contains code, identify the concept "
        "the code demonstrates and ask a definition question about that "
        "concept — not about the syntax or output of the code.\n\n"
        "Example: chunk shows a recursive function →\n"
        "BAD:  \"What does this recursive function return?\"\n"
        "GOOD: \"What is the purpose of a base case in a recursive function?\""
    )


def _build_generation_prompt(task: dict) -> str:
    """Build a combined QG+DG generation prompt for a single MCQ.

    Incorporates five blocks beyond the taxonomy:
    1. Context-scope restriction (no figure/textbook questions)
    2. very_weak hard type override (injected only when applicable)
    3. Code length restriction (max 5 lines in question stem)
    4. Explicit mastery vs score_category separation with examples
    5. Distractor category labeling (wrong_concept / wrong_application /
       partial_knowledge)
    """
    mcq_src = str(Path(__file__).resolve().parent.parent.parent)
    if mcq_src not in sys.path:
        sys.path.insert(0, mcq_src)

    from mcq.question_types import QUESTION_TYPE_TAXONOMY
    from mcq.scoring_categories import score_category_description

    category_desc = score_category_description(task["score_category"])

    misconception_block = ""
    if task["misconception_context"]:
        misconception_block = (
            f"\nMISCONCEPTION CONTEXT:\n"
            f"Previously, {task['misconception_context']}.\n"
            f"Generate a question that approaches this topic from a different angle to\n"
            f"address the underlying gap.  One distractor should target the same\n"
            f"misconception from a new perspective.\n"
        )

    # Inject the very_weak override block only when applicable
    very_weak_block = ""
    if task["score_category"] == "very_weak":
        very_weak_block = f"\n{_build_very_weak_override_block(task['question_type'])}\n"

    return f"""\
You are an expert educational question writer.

{QUESTION_TYPE_TAXONOMY}

{_PROMPT_CONTEXT_SCOPE}

{_PROMPT_SIGNAL_SEPARATION}
{very_weak_block}
TASK: Generate a complete multiple-choice question of Type {task['question_type']} \
for the topic "{task['topic']}".

STUDENT PROFILE:
- Mastery level: {task['mastery']}
- Topic score category: {task['score_category']}
- {category_desc}
{misconception_block}
{_PROMPT_CODE_LENGTH}

SOURCE CONTENT:
\"\"\"
{task['text']}
\"\"\"

{_PROMPT_DISTRACTOR_LABELS}

Generate exactly ONE question with the correct answer, explanation, and exactly \
3 wrong-but-plausible distractors.

REQUIREMENTS:
1. The question MUST be Type {task['question_type']} as defined in the taxonomy.
2. The question must be answerable from the source content alone without
   needing the textbook, any figures, or any code block.
3. Each distractor must be plausible but incorrect.
4. No distractor should match the correct answer.
5. No two distractors should be identical.

Return ONLY valid JSON:
{{
  "question": "...",
  "correct_answer": "...",
  "explanation": "...",
  "distractors": ["wrong 1", "wrong 2", "wrong 3"]
}}
"""


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════


def _validate_response(data: dict) -> str | None:
    """Validate a generated MCQ response and return a specific error message.

    Returns
    -------
    str or None
        A human-readable error message describing the first problem found,
        or None if the response is fully valid.
    """
    if not isinstance(data, dict):
        return "Response was not a JSON object."

    missing = [k for k in ("question", "correct_answer", "distractors") if k not in data]
    if missing:
        return (
            f"Response was missing required field(s): {', '.join(missing)}. "
            f"You must output all of: 'question', 'correct_answer', 'explanation', 'distractors'."
        )

    distractors = data.get("distractors", [])
    if not isinstance(distractors, list):
        return "'distractors' must be a JSON array, but it was not a list."

    if len(distractors) != 3:
        return (
            f"'distractors' must contain exactly 3 items, but you provided {len(distractors)}. "
            f"Generate exactly 3 wrong-but-plausible distractors."
        )

    correct_lower = str(data["correct_answer"]).strip().lower()
    distractor_strs = [str(d).strip() for d in distractors]

    for d in distractor_strs:
        if d.lower() == correct_lower:
            return (
                f"Distractor '{d}' is identical to the correct answer '{data['correct_answer']}'. "
                f"Every distractor must be wrong — it must not match the correct answer."
            )

    unique_lower = {d.lower() for d in distractor_strs}
    if len(unique_lower) < 3:
        return (
            "Two or more distractors are identical. "
            "All 3 distractors must be distinct from each other."
        )

    return None  # all checks passed


# ═══════════════════════════════════════════════════════════════════════════════
# KEY POOL  — thread-safe primary ↔ backup rotation (generation workers)
# ═══════════════════════════════════════════════════════════════════════════════


class KeyPool:
    """Thread-safe API key pool with primary→backup→primary rotation.

    Used by generation workers only.  Judge keys are dedicated singletons
    and never go through this pool.

    Each worker owns one key at a time. When it reports an API error the pool
    immediately gives it the next available key (cycling through primary first,
    then backup, then primary again).  A key is marked "cooling down" for
    ``cooldown`` seconds after ``fail_threshold`` consecutive errors so
    transiently-bad keys can recover.  If every key in both sets is cooling
    down simultaneously, ``all_failed`` is set and workers stop cleanly.
    """

    def __init__(
        self,
        primary: list[str],
        backup: list[str],
        fail_threshold: int = 3,
        cooldown: float = 60.0,
    ):
        self._primary  = list(primary)
        self._backup   = list(backup)
        self._all_keys = self._primary + self._backup
        if not self._all_keys:
            raise ValueError("KeyPool requires at least one API key.")

        self._fail_threshold = fail_threshold
        self._cooldown       = cooldown
        self._lock           = threading.Lock()

        # Per-key state
        self._consecutive_errors: dict[str, int]   = {k: 0 for k in self._all_keys}
        self._cooling_until:      dict[str, float]  = {k: 0.0 for k in self._all_keys}

        # Round-robin index across all keys
        self._rr_idx = 0

        # Set to True when every key is in cooldown simultaneously
        self.all_failed = False

    # ── public API ────────────────────────────────────────────────────────────

    def get_initial_key(self) -> str:
        """Return the first available key for a new worker."""
        with self._lock:
            return self._next_available_key_locked()

    def report_success(self, key: str) -> None:
        """Reset the error counter for ``key``."""
        with self._lock:
            self._consecutive_errors[key] = 0

    def report_api_error(self, key: str) -> str:
        """Record an API error for ``key`` and return the next key to use.

        If the error count reaches the threshold the key enters cooldown.
        Returns the same key if it is still usable.
        """
        with self._lock:
            self._consecutive_errors[key] = self._consecutive_errors.get(key, 0) + 1
            if self._consecutive_errors[key] >= self._fail_threshold:
                self._cooling_until[key] = time.time() + self._cooldown
                self._consecutive_errors[key] = 0
                logger.warning(
                    "key_cooling_down",
                    key=key[:8] + "...",
                    cooldown_s=self._cooldown,
                )
            return self._next_available_key_locked()

    # ── internals ─────────────────────────────────────────────────────────────

    def _next_available_key_locked(self) -> str:
        """Return next non-cooling key. Sets all_failed if none available."""
        now = time.time()
        # Try primary first, then backup — pure round-robin within each tier
        for tier in (self._primary, self._backup, self._primary):
            for _ in range(len(tier)):
                key = tier[self._rr_idx % len(tier)] if tier else None
                self._rr_idx += 1
                if key and now >= self._cooling_until.get(key, 0.0):
                    return key
        # All keys are cooling — pick the one that cools down soonest
        candidates = [
            (self._cooling_until.get(k, 0.0), k)
            for k in self._all_keys
        ]
        soonest_time, soonest_key = min(candidates)
        wait = max(0.0, soonest_time - now)
        if wait > 0:
            logger.error(
                "all_keys_cooling",
                wait_s=round(wait, 1),
                msg="All API keys are in cooldown — waiting for recovery.",
            )
            # Check if all keys have been cooling for too long (give up)
            max_cooling = max(t for t, _ in candidates)
            if max_cooling - now > self._cooldown * 3:
                self.all_failed = True
            time.sleep(min(wait, 10.0))  # wait in small increments
        return soonest_key


# ═══════════════════════════════════════════════════════════════════════════════
# WORKER POOL  — generation key management with hard-failure fallback cycling
# ═══════════════════════════════════════════════════════════════════════════════


class WorkerPool:
    """Manages 4 primary generation keys with fallback cycling on hard failure.

    A "hard failure" is: connection refused, auth error (401/403), or
    5 consecutive timeouts from the same key.  A single timeout or rate
    limit is NOT a hard failure — the caller should retry once before
    calling ``mark_failed``.

    When a key is hard-failed, it is permanently removed from the active
    set and replaced by the next fallback key.  If no fallbacks remain the
    active pool shrinks.  ``available()`` returns False only when the active
    pool is completely empty.
    """

    def __init__(self, primary_keys: list[str], fallback_keys: list[str]):
        self._lock = threading.Lock()
        self.active_keys: list[str]  = list(primary_keys)
        self.fallback_keys: list[str] = list(fallback_keys)
        self.failed_keys: set[str]   = set()

        # Per-key consecutive timeout counter (resets on success)
        self._timeout_count: dict[str, int] = {
            k: 0 for k in primary_keys + fallback_keys
        }
        self._TIMEOUT_HARD_LIMIT = 5

    def get_active_keys(self) -> list[str]:
        """Return a snapshot of the currently active key list."""
        with self._lock:
            return list(self.active_keys)

    def report_success(self, key: str) -> None:
        """Reset the timeout counter for a key after a successful call."""
        with self._lock:
            self._timeout_count[key] = 0

    def report_timeout(self, key: str) -> bool:
        """Record a timeout for ``key``.  Returns True if this becomes a hard failure."""
        with self._lock:
            self._timeout_count[key] = self._timeout_count.get(key, 0) + 1
            if self._timeout_count[key] >= self._TIMEOUT_HARD_LIMIT:
                return True  # caller should call mark_failed
            return False

    def mark_failed(self, key: str) -> None:
        """Permanently remove ``key`` from the active pool and replace with next fallback."""
        with self._lock:
            if key in self.active_keys:
                self.active_keys.remove(key)
                self.failed_keys.add(key)
                if self.fallback_keys:
                    replacement = self.fallback_keys.pop(0)
                    self.active_keys.append(replacement)
                    logger.info(
                        "worker_key_replaced",
                        failed=key[:8] + "...",
                        replacement=replacement[:8] + "...",
                        active_count=len(self.active_keys),
                    )
                else:
                    logger.warning(
                        "worker_key_failed_no_fallback",
                        failed=key[:8] + "...",
                        active_count=len(self.active_keys),
                    )

    def available(self) -> bool:
        """Return True if there is at least one active key."""
        with self._lock:
            return len(self.active_keys) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# JUDGE A — REGEX PRE-FILTER  (no LLM, no key, instant)
# ═══════════════════════════════════════════════════════════════════════════════

# Compiled once at import time.
_JUDGE_A_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in [
        r'the following code snippet',
        r'the code above',
        r'the code below',
        r'from the \w[^.,]{0,40} lecture',
        r'from the \w[^.,]{0,40} notes',
        r'\bfigure\s+[\d.]+',
        r'\bfig\.?\s+[\d.]+',
        r'\bthe diagram\b',
        r'the table above',
        r'according to the passage',
        r'according to the text',
        r'the author states',
        r'\bas shown\b',
        r'as described above',
    ]
]
# Code block longer than 5 lines: fence open + 5+ content lines + fence close
_JUDGE_A_CODE_BLOCK_RE = re.compile(r'```[^`]*\n(?:[^\n]*\n){6,}[^`]*```', re.DOTALL)


def _passes_regex_filter(mcq: dict) -> bool:
    """Judge A: fast regex pre-filter. No LLM call.

    Returns True (passes) if the generated question is free of
    textbook-reference patterns and does not include a code block
    longer than 5 lines in the question stem.
    """
    question = mcq.get("question", "")
    for pat in _JUDGE_A_PATTERNS:
        if pat.search(question):
            return False
    if _JUDGE_A_CODE_BLOCK_RE.search(question):
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# JUDGE B — FULL PERSONALIZATION ADHERENCE  (JUDGE_B_KEY, JUDGE_MODEL)
# G-Eval: reasoning written BEFORE each sub-check answer.
# HD-Eval: 9 atomic YES/NO sub-checks; score derived in Python, never by LLM.
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class JudgeBResult:
    verdict: str                    # "ACCEPT" or "REJECT"
    overall_score: float            # (mastery + score_cat + misconception) / 3
    primary_failure: str            # which sub-check failed first, or "NONE"
    mastery_score: int   = 0        # count of YES from 3 mastery sub-checks
    score_cat_score: int = 0        # count of YES from 3 score_cat sub-checks
    misconception_score: int = 0    # count of YES from 3 misconception sub-checks
    type_eligible: bool  = True
    depth_calibration: str = "CORRECT"
    # Raw sub-check answers stored for sub-check pass-rate reporting
    sub_checks: dict = field(default_factory=dict)
    raw_response: str = ""


# ── Misconception block (substituted in Python before sending) ─────────────
_JUDGE_B_MISCONCEPTION_NONE_BLOCK = """\
SIGNAL 3 — MISCONCEPTION CONTEXT
─────────────────────────────────────────────────────
MISCONCEPTION_REASONING: Not applicable — no misconception context.
MISCONCEPTION_CHECK_NEW_ANGLE: YES
MISCONCEPTION_CHECK_DISTRACTOR_TARGETS: YES
MISCONCEPTION_CHECK_ANSWER_ADDRESSES_GAP: YES"""


def _build_judge_b_misconception_block(mc: str | None) -> str:
    """Build Signal 3 block — auto-YES when no misconception context."""
    if not mc:
        return _JUDGE_B_MISCONCEPTION_NONE_BLOCK
    return f"""\
SIGNAL 3 — MISCONCEPTION CONTEXT
─────────────────────────────────────────────────────
Misconception: {mc}

MISCONCEPTION_REASONING: [1-2 sentences: does this question approach
  the same conceptual gap from a new angle? Does a distractor target
  the misconception?]

MISCONCEPTION_CHECK_NEW_ANGLE: [YES/NO — different scenario than
  the one the student previously failed?]
MISCONCEPTION_CHECK_DISTRACTOR_TARGETS: [YES/NO — does at least
  one distractor appeal to the same wrong mental model?]
MISCONCEPTION_CHECK_ANSWER_ADDRESSES_GAP: [YES/NO — does the
  correct answer implicitly address why the misconception is wrong?]"""


def _build_judge_b_prompt(mcq: dict) -> str:
    """Build the full Judge B prompt (G-Eval + HD-Eval restructured)."""
    mastery    = mcq.get("mastery_level", "Intermediate")
    score_cat  = mcq.get("score_category", "moderate")
    qtype      = mcq.get("question_type", "4a")
    mc         = mcq.get("misconception_context") or None
    chunk      = mcq.get("chunk", "")
    question   = mcq.get("question", "")
    answer     = mcq.get("correct_answer", "")
    explanation = mcq.get("explanation", "")

    misconception_block = _build_judge_b_misconception_block(mc)

    return f"""\
You are a strict personalization quality reviewer for an adaptive
learning platform.

PERSONALIZATION SIGNALS:
  mastery_level:    {mastery}
  score_category:   {score_cat}
  question_type:    {qtype}
  misconception:    {mc or "NONE"}

SOURCE CHUNK:
{chunk}

GENERATED QUESTION:
{question}

CORRECT ANSWER:
{answer}

EXPLANATION:
{explanation}

─────────────────────────────────────────────────────
SIGNAL RESPONSIBILITIES
─────────────────────────────────────────────────────
MASTERY controls HOW the question is framed: vocabulary, cognitive
register, distractor sophistication.

SCORE CATEGORY controls HOW HARD the question is: difficulty, and
whether mastery is overridden on type (very_weak forces Type 4a but
mastery still governs vocabulary and distractor sophistication).

Evaluate each signal below. For each, FIRST write one to two
sentences of reasoning addressing the sub-checks, THEN answer each
sub-check YES or NO. Do not answer the sub-checks before writing
your reasoning.

─────────────────────────────────────────────────────
SIGNAL 1 — MASTERY: {mastery}
─────────────────────────────────────────────────────
Reference framing rules:
  Novice: vocabulary matches chunk exactly, asks what something IS
    or DOES, no cross-concept reasoning, distractors clearly wrong
    to a careful reader
  Intermediate: standard CS terminology, connects two ideas or
    applies to a scenario, never a pure definition (unless
    score_category forces 4a), distractors require careful reasoning
  Expert: precise technical vocabulary, reasons about WHY/edge
    cases/tradeoffs, may synthesize concepts, distractors plausible
    to partial knowers

MASTERY_REASONING: [1-2 sentences: does the vocabulary and cognitive
  register in this question match {mastery}? Reference specific
  words or phrasing from the question.]

MASTERY_CHECK_VOCABULARY: [YES/NO — does vocabulary depth match
  {mastery}?]
MASTERY_CHECK_FRAMING: [YES/NO — does the cognitive demand
  (recall/connect/reason) match {mastery}?]
MASTERY_CHECK_DISTRACTOR_SOPHISTICATION: [YES/NO — does distractor
  sophistication match {mastery}?]

─────────────────────────────────────────────────────
SIGNAL 2 — SCORE CATEGORY: {score_cat}
─────────────────────────────────────────────────────
Reference difficulty rules:
  very_weak: TYPE must be 4a regardless of mastery; simplest
    possible question; distractors easy to eliminate; mastery
    vocabulary/sophistication still applies
  weak: one level easier than mastery standard; distractors
    plausible but distinguishable with effort
  moderate: standard difficulty for mastery, no adjustment
  strong: hardest difficulty mastery allows; distractors as subtle
    as mastery permits

SCORE_CATEGORY_REASONING: [1-2 sentences: does the question and
  distractor difficulty match {score_cat}? If very_weak, is the
  TYPE actually 4a?]

SCORE_CATEGORY_CHECK_TYPE_OVERRIDE: [YES/NO — if score_category is
  very_weak, is question_type actually 4a? If score_category is
  NOT very_weak, answer YES automatically (not applicable).]
SCORE_CATEGORY_CHECK_DIFFICULTY: [YES/NO — does question difficulty
  match {score_cat}?]
SCORE_CATEGORY_CHECK_DISTRACTOR_DIFFICULTY: [YES/NO — does
  distractor difficulty match {score_cat}?]

─────────────────────────────────────────────────────
{misconception_block}

─────────────────────────────────────────────────────
SIGNAL 4 — TYPE × MASTERY ELIGIBILITY
─────────────────────────────────────────────────────
Eligibility matrix:
  Novice:       Types 1, 4a only
  Intermediate: Types 1, 2, 3, 4b, 4c only
  Expert:       All types
Override: very_weak forces 4a regardless of mastery.

TYPE_ELIGIBLE: [YES/NO — is {qtype} eligible given
  mastery={mastery} and score_category={score_cat}?]
TYPE_REASON: [one sentence if NO]

─────────────────────────────────────────────────────
SIGNAL 5 — COGNITIVE DEPTH
─────────────────────────────────────────────────────
DEPTH_REASONING: [1-2 sentences: given all signals combined, is the
  cognitive depth of this question too easy, correct, or too hard?]
DEPTH_CALIBRATION: [TOO_EASY / CORRECT / TOO_HARD]

─────────────────────────────────────────────────────
END OF EVALUATION — do not compute a final score or verdict.
The numeric score and accept/reject decision are computed
separately from your sub-check answers above.
─────────────────────────────────────────────────────
"""


# ── HD-Eval Python scoring functions ─────────────────────────────────────
# The LLM provides atomic YES/NO sub-checks; Python counts them.
# The LLM never picks "2 vs 3" directly — the arithmetic is deterministic.

def _score_mastery_signal(parsed: dict) -> int:
    checks = [
        parsed.get("mastery_check_vocabulary", "NO"),
        parsed.get("mastery_check_framing", "NO"),
        parsed.get("mastery_check_distractor_sophistication", "NO"),
    ]
    return sum(1 for c in checks if c == "YES")


def _score_category_signal(parsed: dict) -> int:
    checks = [
        parsed.get("score_category_check_type_override", "NO"),
        parsed.get("score_category_check_difficulty", "NO"),
        parsed.get("score_category_check_distractor_difficulty", "NO"),
    ]
    return sum(1 for c in checks if c == "YES")


def _score_misconception_signal(parsed: dict) -> int:
    checks = [
        parsed.get("misconception_check_new_angle", "NO"),
        parsed.get("misconception_check_distractor_targets", "NO"),
        parsed.get("misconception_check_answer_addresses_gap", "NO"),
    ]
    return sum(1 for c in checks if c == "YES")


def _parse_judge_b_response(raw: str) -> JudgeBResult:
    """Parse Judge B's structured text response into a JudgeBResult.

    Extracts all atomic YES/NO sub-checks by regex; derives numeric
    scores in Python.  The LLM is never asked to produce a score directly.
    """
    def _yn(key: str, default: str = "NO") -> str:
        # Scan each line for the key (case-insensitive) then extract YES/NO.
        # This is decoration-agnostic: handles **KEY:** YES, - KEY: YES,
        # KEY: **YES**, KEY — YES, or any other formatting the LLM may use.
        key_upper = key.upper()
        for line in raw.splitlines():
            if key_upper in line.upper():
                m = re.search(r'\b(YES|NO)\b', line, re.IGNORECASE)
                if m:
                    return m.group(1).upper()
        return default

    def _str(key: str, default: str = "") -> str:
        m = re.search(rf'^{key}:\s*(.+)', raw, re.MULTILINE)
        return m.group(1).strip() if m else default

    # Collect all sub-check answers into a flat dict for score functions
    parsed: dict = {
        "mastery_check_vocabulary":              _yn("MASTERY_CHECK_VOCABULARY"),
        "mastery_check_framing":                 _yn("MASTERY_CHECK_FRAMING"),
        "mastery_check_distractor_sophistication": _yn("MASTERY_CHECK_DISTRACTOR_SOPHISTICATION"),
        "score_category_check_type_override":    _yn("SCORE_CATEGORY_CHECK_TYPE_OVERRIDE", default="YES"),
        "score_category_check_difficulty":       _yn("SCORE_CATEGORY_CHECK_DIFFICULTY"),
        "score_category_check_distractor_difficulty": _yn("SCORE_CATEGORY_CHECK_DISTRACTOR_DIFFICULTY"),
        "misconception_check_new_angle":         _yn("MISCONCEPTION_CHECK_NEW_ANGLE", default="YES"),
        "misconception_check_distractor_targets": _yn("MISCONCEPTION_CHECK_DISTRACTOR_TARGETS", default="YES"),
        "misconception_check_answer_addresses_gap": _yn("MISCONCEPTION_CHECK_ANSWER_ADDRESSES_GAP", default="YES"),
    }

    mastery_score       = _score_mastery_signal(parsed)
    score_cat_score     = _score_category_signal(parsed)
    misconception_score = _score_misconception_signal(parsed)
    overall_score       = round((mastery_score + score_cat_score + misconception_score) / 3.0, 2)

    type_eligible_raw = _str("TYPE_ELIGIBLE", "YES").upper()
    type_eligible     = "NO" not in type_eligible_raw

    depth_raw = _str("DEPTH_CALIBRATION", "CORRECT").upper()
    if "TOO_EASY" in depth_raw:
        depth = "TOO_EASY"
    elif "TOO_HARD" in depth_raw:
        depth = "TOO_HARD"
    else:
        depth = "CORRECT"

    # ── Derive verdict + primary_failure in Python — never from LLM output ──
    # very_weak type-override check is the first and hardest gate.
    if parsed["score_category_check_type_override"] == "NO":
        verdict        = "REJECT"
        primary_failure = "very_weak_type_override_violated"
    elif not type_eligible:
        verdict        = "REJECT"
        primary_failure = "type_ineligible"
    elif mastery_score < 2:
        verdict        = "REJECT"
        primary_failure = "mastery_mismatch"
    elif score_cat_score < 2:
        verdict        = "REJECT"
        primary_failure = "score_category_mismatch"
    elif misconception_score < 2:
        verdict        = "REJECT"
        primary_failure = "misconception_mismatch"
    elif depth == "TOO_HARD":
        verdict        = "REJECT"
        primary_failure = "too_hard"
    else:
        verdict        = "ACCEPT"
        primary_failure = "NONE"

    return JudgeBResult(
        verdict=verdict,
        overall_score=overall_score,
        primary_failure=primary_failure,
        mastery_score=mastery_score,
        score_cat_score=score_cat_score,
        misconception_score=misconception_score,
        type_eligible=type_eligible,
        depth_calibration=depth,
        sub_checks=parsed,
        raw_response=raw[:600],
    )


def _run_judge_b(
    mcq: dict,
    judge_b_client,
) -> JudgeBResult:
    """Call Judge B and return a parsed result. Never raises."""
    try:
        prompt = _build_judge_b_prompt(mcq)
        raw = judge_b_client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            timeout_override=120,
        )
        return _parse_judge_b_response(raw)
    except Exception as exc:
        logger.warning("judge_b_failed", error=str(exc)[:100])
        # On failure: ACCEPT with score 0 so the sample is not silently lost;
        # the low personalization_score flags it for post-hoc review.
        return JudgeBResult(
            verdict="ACCEPT",
            overall_score=0.0,
            primary_failure="judge_b_exception",
            sub_checks={},
            raw_response=str(exc)[:200],
        )


# ═══════════════════════════════════════════════════════════════════════════════
# JUDGE C — DISTRACTOR QUALITY  (JUDGE_C_KEY, JUDGE_MODEL)
# G-Eval: reasoning before each YES/NO.
# HD-Eval: 5 atomic hard checks + 1 advisory; verdict computed in Python.
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class JudgeCResult:
    verdict: str       # "ACCEPT" or "REJECT"
    reason:  str = ""  # comma-joined failed check names, or "NONE"
    # Raw sub-check answers for pass-rate reporting
    sub_checks: dict = field(default_factory=dict)


def _build_judge_c_prompt(mcq: dict) -> str:
    """Build the Judge C distractor quality prompt (G-Eval + HD-Eval restructured)."""
    question = mcq.get("question", "")
    answer   = mcq.get("correct_answer", "")
    dists    = mcq.get("distractors", ["", "", ""])
    d1 = dists[0] if len(dists) > 0 else ""
    d2 = dists[1] if len(dists) > 1 else ""
    d3 = dists[2] if len(dists) > 2 else ""
    return f"""\
You are a quality reviewer for educational MCQ training data.

Question: {question}
Correct answer: {answer}

Distractors:
D1: {d1}
D2: {d2}
D3: {d3}

For each check below, FIRST write one sentence of reasoning, THEN
answer YES or NO.

CHECK_D1_DIFFERENT_REASONING: [is D1 clearly different from the
  correct answer? why or why not?]
CHECK_D1_DIFFERENT: [YES/NO]

CHECK_D2_DIFFERENT_REASONING: [is D2 clearly different from the
  correct answer? why or why not?]
CHECK_D2_DIFFERENT: [YES/NO]

CHECK_D3_DIFFERENT_REASONING: [is D3 clearly different from the
  correct answer? why or why not?]
CHECK_D3_DIFFERENT: [YES/NO]

CHECK_MUTUAL_DIVERSITY_REASONING: [are D1, D2, D3 meaningfully
  different from each other, or do two or more say the same thing
  in different words?]
CHECK_MUTUAL_DIVERSITY: [YES/NO]

CHECK_PLAUSIBILITY_REASONING: [could a student with partial
  understanding of this specific topic plausibly choose each
  distractor? are any of them absurd or unrelated to the topic?]
CHECK_PLAUSIBILITY: [YES/NO]

CHECK_FORMAT_CONSISTENCY_REASONING: [are all distractors similar
  in length and structure to the correct answer?]
CHECK_FORMAT_CONSISTENCY: [YES/NO — advisory only]
"""


def _parse_judge_c_response(raw: str) -> JudgeCResult:
    """Parse Judge C's response into a JudgeCResult.

    All 5 hard check answers are extracted by regex; verdict computed in Python.
    """
    def _yn(key: str, default: str = "NO") -> str:
        # Scan each line for the key (case-insensitive) then extract YES/NO.
        # Decoration-agnostic: handles **KEY:** YES, - KEY: YES, KEY — YES, etc.
        key_upper = key.upper()
        for line in raw.splitlines():
            if key_upper in line.upper():
                m = re.search(r'\b(YES|NO)\b', line, re.IGNORECASE)
                if m:
                    return m.group(1).upper()
        return default

    sub_checks = {
        "check_d1_different":      _yn("CHECK_D1_DIFFERENT"),
        "check_d2_different":      _yn("CHECK_D2_DIFFERENT"),
        "check_d3_different":      _yn("CHECK_D3_DIFFERENT"),
        "check_mutual_diversity":  _yn("CHECK_MUTUAL_DIVERSITY"),
        "check_plausibility":      _yn("CHECK_PLAUSIBILITY"),
        # advisory — stored but not used for rejection
        "check_format_consistency": _yn("CHECK_FORMAT_CONSISTENCY", default="YES"),
    }

    hard_names = [
        ("check_d1_different",     "d1_equals_answer"),
        ("check_d2_different",     "d2_equals_answer"),
        ("check_d3_different",     "d3_equals_answer"),
        ("check_mutual_diversity", "low_diversity"),
        ("check_plausibility",     "implausible"),
    ]
    failed = [label for key, label in hard_names if sub_checks[key] == "NO"]

    if failed:
        return JudgeCResult(verdict="REJECT", reason=",".join(failed), sub_checks=sub_checks)
    return JudgeCResult(verdict="ACCEPT", reason="NONE", sub_checks=sub_checks)


def _run_judge_c(
    mcq: dict,
    judge_c_client,
) -> JudgeCResult:
    """Call Judge C and return a parsed result. Never raises."""
    try:
        prompt = _build_judge_c_prompt(mcq)
        raw = judge_c_client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            timeout_override=90,
        )
        return _parse_judge_c_response(raw)
    except Exception as exc:
        logger.warning("judge_c_failed", error=str(exc)[:100])
        return JudgeCResult(verdict="ACCEPT", reason="judge_c_exception", sub_checks={})


# ═══════════════════════════════════════════════════════════════════════════════
# JUDGE D — FACTUAL CORRECTNESS  (JUDGE_D_KEY, JUDGE_MODEL)
# G-Eval: reasoning before each check.
# HD-Eval: decomposes factual correctness into per-claim verification +
#          answerability + ambiguity + explanation; verdict computed in Python.
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class JudgeDResult:
    verdict: str       # "ACCEPT" or "REJECT"
    reason:  str = ""  # which check failed, or "NONE"
    # Raw sub-check answers for pass-rate reporting
    sub_checks: dict = field(default_factory=dict)


def _build_judge_d_prompt(mcq: dict) -> str:
    """Build the Judge D factual correctness prompt (G-Eval + HD-Eval restructured)."""
    chunk       = mcq.get("chunk", "")
    question    = mcq.get("question", "")
    answer      = mcq.get("correct_answer", "")
    explanation = mcq.get("explanation", "")
    return f"""\
You are a fact-checker for educational MCQ training data.

Chunk:
{chunk}

Question: {question}
Stated correct answer: {answer}
Explanation: {explanation}

STEP 1 — Decompose the correct answer into its core factual claims.
List each distinct claim made by the correct answer, numbered.

CLAIMS: [list each claim, e.g. "1. A hash table provides O(1)
  average-case lookup. 2. Collisions degrade this to O(n) worst case."]

STEP 2 — For EACH claim listed above, verify it against general CS
knowledge and the chunk. Write one sentence of reasoning per claim,
then YES (claim is true) or NO (claim is false or unsupported).

CLAIM_1_REASONING: [...]
CLAIM_1_VERIFIED: [YES/NO]
CLAIM_2_REASONING: [...]  (omit if only one claim)
CLAIM_2_VERIFIED: [YES/NO]
(continue for each claim)

STEP 3 — Answerability and ambiguity.

ANSWERABILITY_REASONING: [can this be answered using general CS
  knowledge of the concept, without needing this specific textbook
  or outside trivia?]
ANSWERABILITY_CHECK: [YES/NO]

AMBIGUITY_REASONING: [is there exactly one defensibly correct
  answer, or could a reasonable student argue for more than one?]
AMBIGUITY_CHECK: [YES — only one correct answer / NO — ambiguous]

STEP 4 — Explanation correctness.

EXPLANATION_REASONING: [does the explanation correctly justify
  the answer using the claims verified above?]
EXPLANATION_CHECK: [YES/NO]
"""


def _parse_judge_d_response(raw: str) -> JudgeDResult:
    """Parse Judge D's structured response into a JudgeDResult.

    Extracts all CLAIM_N_VERIFIED fields by regex (handles any number
    of claims); derives verdict in Python.
    """
    def _yn(key: str, default: str = "NO") -> str:
        # Scan each line for the key (case-insensitive) then extract YES/NO.
        # Decoration-agnostic: handles **KEY:** YES, - KEY: YES, KEY — YES, etc.
        key_upper = key.upper()
        for line in raw.splitlines():
            if key_upper in line.upper():
                m = re.search(r'\b(YES|NO)\b', line, re.IGNORECASE)
                if m:
                    return m.group(1).upper()
        return default

    # Extract all CLAIM_N_VERIFIED entries (1, 2, 3, ...)
    claim_results: dict[str, str] = {}
    for m in re.finditer(r'^(CLAIM_\d+_VERIFIED):\s*(YES|NO)', raw, re.MULTILINE | re.IGNORECASE):
        claim_results[m.group(1).lower()] = m.group(2).upper()

    # If no claims found at all, treat as unverified (parser fault → soft reject)
    if not claim_results:
        claim_results["claim_1_verified"] = "NO"

    sub_checks = {
        **claim_results,
        "answerability_check": _yn("ANSWERABILITY_CHECK"),
        "ambiguity_check":     _yn("AMBIGUITY_CHECK", default="YES"),
        "explanation_check":   _yn("EXPLANATION_CHECK"),
    }

    # Verdict: any NO anywhere is a reject
    if any(v == "NO" for v in claim_results.values()):
        return JudgeDResult(verdict="REJECT", reason="unverified_claim", sub_checks=sub_checks)
    if sub_checks["answerability_check"] == "NO":
        return JudgeDResult(verdict="REJECT", reason="requires_outside_knowledge", sub_checks=sub_checks)
    if sub_checks["ambiguity_check"] == "NO":
        return JudgeDResult(verdict="REJECT", reason="ambiguous_correct_answer", sub_checks=sub_checks)
    if sub_checks["explanation_check"] == "NO":
        return JudgeDResult(verdict="REJECT", reason="explanation_incorrect", sub_checks=sub_checks)
    return JudgeDResult(verdict="ACCEPT", reason="NONE", sub_checks=sub_checks)


def _run_judge_d(
    mcq: dict,
    judge_d_client,
) -> JudgeDResult:
    """Call Judge D and return a parsed result. Never raises."""
    try:
        prompt = _build_judge_d_prompt(mcq)
        raw = judge_d_client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            timeout_override=90,
        )
        return _parse_judge_d_response(raw)
    except Exception as exc:
        logger.warning("judge_d_failed", error=str(exc)[:100])
        return JudgeDResult(verdict="ACCEPT", reason="judge_d_exception", sub_checks={})


# ═══════════════════════════════════════════════════════════════════════════════
# DECISION LOGIC
# ═══════════════════════════════════════════════════════════════════════════════


def _decide(
    b: JudgeBResult,
    c: JudgeCResult,
    d: JudgeDResult,
    mcq: dict,
) -> tuple[bool, str]:
    """Apply decision logic across all three judge verdicts.

    Returns (accepted: bool, reason: str).
    On accept, attaches personalization_score to mcq in-place.
    """
    if not b.type_eligible:
        return False, f"judge_b:type_not_eligible"
    if b.mastery_score < 2:
        return False, f"judge_b:mastery_score_{b.mastery_score}"
    if b.score_cat_score < 2:
        return False, f"judge_b:score_category_{b.score_cat_score}"
    if mcq.get("misconception_context") and b.misconception_score < 2:
        return False, f"judge_b:misconception_{b.misconception_score}"
    if b.depth_calibration == "TOO_HARD":
        return False, "judge_b:too_hard"
    if b.verdict == "REJECT":
        return False, f"judge_b:{b.primary_failure}"
    if c.verdict == "REJECT":
        return False, f"judge_c:{c.reason}"
    if d.verdict == "REJECT":
        return False, f"judge_d:{d.reason}"
    # All passed — attach personalization score metadata
    mcq["personalization_score"] = b.overall_score
    return True, "accepted"


# ═══════════════════════════════════════════════════════════════════════════════
# WORKER
# ═══════════════════════════════════════════════════════════════════════════════


class WorkerStats:
    """Thread-safe per-worker counters."""

    def __init__(self):
        self.success = 0
        self.failure = 0
        self.lock = threading.Lock()

    def record_success(self):
        with self.lock:
            self.success += 1

    def record_failure(self):
        with self.lock:
            self.failure += 1


def _worker(
    worker_id: int,
    key_pool: KeyPool,
    task_queue: queue.Queue,
    eval_queue: queue.Queue,
    stats: WorkerStats,
    all_stats: list,
    pbar: tqdm,
    pbar_lock: threading.Lock,
    target_counter: dict | None = None,
):
    """Generation worker: pulls tasks, calls Ollama, pushes validated MCQs
    to the evaluation queue.

    Does NOT write directly to disk — that is the responsibility of the
    evaluation worker which runs the three LLM judges.

    Owns one active API key at a time. On any API/network error the key
    is reported to KeyPool which returns the next best key.
    Validation errors (bad JSON structure) keep the current key and
    append feedback to the conversation for self-correction.
    """
    current_key = key_pool.get_initial_key()
    client = _make_ollama_client(current_key, model=GENERATION_MODEL)

    while True:
        # Stop if KeyPool has determined that all keys are permanently dead
        if key_pool.all_failed:
            logger.error("worker_stopping_all_keys_failed", worker=worker_id)
            break

        # Stop if target reached (for --target mode)
        if target_counter is not None:
            with target_counter["lock"]:
                if target_counter["count"] >= target_counter["target"]:
                    break

        try:
            task = task_queue.get(timeout=5)
        except queue.Empty:
            break

        prompt = _build_generation_prompt(task)
        result = None

        # Conversation history — grows with validation feedback on each retry
        messages: list[dict] = [{"role": "user", "content": prompt}]

        for attempt in range(1, CONFIG["max_retries"] + 1):
            try:
                data = client.chat_json(
                    messages=messages,
                    temperature=0.7,
                    timeout_override=180,
                )
                # Successful API call — reset key error counter
                key_pool.report_success(current_key)

                # ── Validate the response ─────────────────────────────
                error_msg = _validate_response(data)

                if error_msg is None:
                    distractors = data["distractors"]
                    distractor_strs = [str(d).strip() for d in distractors]
                    result = {
                        "chunk": task["text"],
                        "topic": task["topic"],
                        "question": str(data["question"]).strip(),
                        "correct_answer": str(data["correct_answer"]).strip(),
                        "distractors": distractor_strs,
                        "explanation": str(data.get("explanation", "")).strip(),
                        "question_type": task["question_type"],
                        "mastery_level": task["mastery"],
                        "score_category": task["score_category"],
                        "misconception_context": task["misconception_context"],
                        "_chunk_hash": task["chunk_hash"],
                        "_worker_id": worker_id,
                        "_book": task["book"],
                        "_attempts": attempt,
                        "_api_key_prefix": current_key[:8],
                    }
                    break

                # ── Validation failed — feedback, keep same key ────────
                logger.warning(
                    "worker_validation_failed",
                    worker=worker_id,
                    attempt=attempt,
                    chunk_hash=task["chunk_hash"],
                    reason=error_msg,
                )
                if attempt < CONFIG["max_retries"]:
                    raw_assistant = json.dumps(data) if isinstance(data, dict) else str(data)
                    messages.append({"role": "assistant", "content": raw_assistant})
                    feedback = (
                        f"Your response was invalid. Error: {error_msg}\n\n"
                        f"Please fix this and return valid JSON with the corrected output only. "
                        f"Do not repeat the same mistake."
                    )
                    messages.append({"role": "user", "content": feedback})

            except Exception as exc:
                # ── API / network error — rotate to next key ──────────
                logger.warning(
                    "worker_api_error",
                    worker=worker_id,
                    attempt=attempt,
                    key_prefix=current_key[:8] + "...",
                    error=str(exc)[:120],
                )
                new_key = key_pool.report_api_error(current_key)
                if new_key != current_key:
                    logger.info(
                        "worker_key_rotated",
                        worker=worker_id,
                        old=current_key[:8] + "...",
                        new=new_key[:8] + "...",
                    )
                    current_key = new_key
                    client = _make_ollama_client(current_key, model=GENERATION_MODEL)

                if key_pool.all_failed:
                    break

                if attempt < CONFIG["max_retries"]:
                    # Reset conversation history — start fresh with new key
                    messages = [{"role": "user", "content": prompt}]
                    time.sleep(CONFIG["retry_delay"])

        if result is not None:
            # Push to eval queue — evaluation worker handles judging + writing
            eval_queue.put(result)
            stats.record_success()
            if target_counter is not None:
                with target_counter["lock"]:
                    target_counter["count"] += 1
        else:
            logger.error(
                "worker_all_retries_exhausted",
                worker=worker_id,
                chunk_hash=task["chunk_hash"],
                topic=task["topic"],
            )
            stats.record_failure()

        # Update tqdm bar
        with pbar_lock:
            total_success = sum(s.success for s in all_stats)
            total_fail    = sum(s.failure for s in all_stats)
            pbar.update(1)
            pbar.set_postfix(success=total_success, fail=total_fail, refresh=False)

        task_queue.task_done()


# ═══════════════════════════════════════════════════════════════════════════════
# EVALUATION WORKER  — drains the eval queue with 3 parallel judge calls
# ═══════════════════════════════════════════════════════════════════════════════


class EvalStats:
    """Thread-safe counters for the evaluation pipeline.

    In addition to the high-level reject/accept counts, accumulates
    per-sub-check YES/total tallies from Judges B, C, D so that
    _print_quality_report can compute pass rates for every atomic check.
    """

    def __init__(self):
        self.generated:               int   = 0
        self.regex_rejected:          int   = 0
        self.judge_b_rejected:        int   = 0
        self.judge_c_rejected:        int   = 0
        self.judge_d_rejected:        int   = 0
        self.accepted:                int   = 0
        self.personalization_score_sum: float = 0.0
        # Sub-check pass-rate accumulators: key → (total_seen, yes_count)
        self.sub_check_totals: dict[str, int] = {}
        self.sub_check_yes:    dict[str, int] = {}
        self._lock = threading.Lock()

    def add_generated(self):
        with self._lock: self.generated += 1

    def add_regex_reject(self):
        with self._lock: self.regex_rejected += 1

    def add_judge_b_reject(self):
        with self._lock: self.judge_b_rejected += 1

    def add_judge_c_reject(self):
        with self._lock: self.judge_c_rejected += 1

    def add_judge_d_reject(self):
        with self._lock: self.judge_d_rejected += 1

    def add_accepted(self, personalization_score: float):
        with self._lock:
            self.accepted += 1
            self.personalization_score_sum += personalization_score

    def record_sub_checks(self, sub_checks: dict) -> None:
        """Accumulate YES/NO answers from a judge result into pass-rate counters.

        Called once per sample that reaches any LLM judge (B, C, or D).
        ``sub_checks`` is the flat dict of {field_name: "YES"|"NO"} stored
        on each JudgeXResult dataclass.
        """
        with self._lock:
            for key, val in sub_checks.items():
                self.sub_check_totals[key] = self.sub_check_totals.get(key, 0) + 1
                if val == "YES":
                    self.sub_check_yes[key] = self.sub_check_yes.get(key, 0) + 1

    def avg_personalization_score(self) -> float:
        with self._lock:
            if self.accepted == 0:
                return 0.0
            return round(self.personalization_score_sum / self.accepted, 2)


def _evaluation_worker(
    eval_queue: queue.Queue,
    output_path: str,
    file_lock: threading.Lock,
    judge_b_client,
    judge_c_client,
    judge_d_client,
    eval_stats: EvalStats,
):
    """Evaluation worker: drains eval_queue, runs 3 parallel judges, writes accepted.

    Judge A (regex pre-filter) runs synchronously in Python — no LLM call.
    Judges B, C, D fire in parallel via ThreadPoolExecutor.
    After each judge fires, its sub_checks dict is recorded into EvalStats
    for per-sub-check pass-rate reporting at the end of the run.
    The worker blocks only on evaluation of the current item, not on
    generation workers — they continue filling the queue independently.
    """
    rejected_log: list[dict] = []

    while True:
        try:
            item = eval_queue.get(timeout=10)
        except queue.Empty:
            # Idle check — queue will be poisoned with None when gen is done
            continue

        # Poison pill signals end-of-stream
        if item is None:
            eval_queue.task_done()
            break

        mcq = item
        eval_stats.add_generated()

        # ── Judge A: regex pre-filter ───────────────────────────────────
        if not _passes_regex_filter(mcq):
            eval_stats.add_regex_reject()
            rejected_log.append({"reason": "judge_a_regex", "question": mcq.get("question", "")[:100]})
            logger.debug("eval_rejected_judge_a", question=mcq.get("question", "")[:80])
            eval_queue.task_done()
            continue

        # ── Judges B, C, D: fire in parallel ───────────────────────────
        with ThreadPoolExecutor(max_workers=3) as ex:
            fb = ex.submit(_run_judge_b, mcq, judge_b_client)
            fc = ex.submit(_run_judge_c, mcq, judge_c_client)
            fd = ex.submit(_run_judge_d, mcq, judge_d_client)
            b_result = fb.result()
            c_result = fc.result()
            d_result = fd.result()

        # Record every sub-check answer for pass-rate reporting
        eval_stats.record_sub_checks(b_result.sub_checks)
        eval_stats.record_sub_checks(c_result.sub_checks)
        eval_stats.record_sub_checks(d_result.sub_checks)

        accepted, reason = _decide(b_result, c_result, d_result, mcq)

        if accepted:
            eval_stats.add_accepted(mcq.get("personalization_score", 0.0))
            with file_lock:
                with open(output_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(mcq) + "\n")
            logger.debug(
                "eval_accepted",
                personalization_score=mcq.get("personalization_score"),
                question_type=mcq.get("question_type"),
            )
        else:
            # Track which judge caused the rejection
            if reason.startswith("judge_b"):
                eval_stats.add_judge_b_reject()
            elif reason.startswith("judge_c"):
                eval_stats.add_judge_c_reject()
            elif reason.startswith("judge_d"):
                eval_stats.add_judge_d_reject()
            rejected_log.append({"reason": reason, "question": mcq.get("question", "")[:100]})
            logger.debug("eval_rejected", reason=reason)

        eval_queue.task_done()

    # Write rejection log alongside the output file
    logger.info(
        "evaluation_worker_done",
        total_evaluated=eval_stats.generated,
        accepted=eval_stats.accepted,
        rejected=len(rejected_log),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# RESUMABILITY
# ═══════════════════════════════════════════════════════════════════════════════


def _load_existing_hashes(output_path: str) -> set[str]:
    """Load chunk hashes already present in the output file."""
    hashes: set[str] = set()
    path = Path(output_path)
    if not path.exists():
        return hashes

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                h = obj.get("_chunk_hash")
                if h:
                    hashes.add(h)
            except json.JSONDecodeError:
                pass

    logger.info("existing_hashes_loaded", count=len(hashes))
    return hashes


# ═══════════════════════════════════════════════════════════════════════════════
# REPORTS
# ═══════════════════════════════════════════════════════════════════════════════


def _print_quality_report(
    eval_stats: EvalStats,
    worker_pool: WorkerPool,
    all_stats: list,
    elapsed: float = 0.0,
):
    """Print the post-evaluation quality report, including per-sub-check pass rates."""
    W = 55
    gen   = eval_stats.generated
    rej_a = eval_stats.regex_rejected
    rej_b = eval_stats.judge_b_rejected
    rej_c = eval_stats.judge_c_rejected
    rej_d = eval_stats.judge_d_rejected
    acc   = eval_stats.accepted
    avg_p = eval_stats.avg_personalization_score()

    pct = lambda n: f"({100 * n / max(gen, 1):.1f}%)"
    sc_pct = lambda yes, total: f"{100 * yes / max(total, 1):.0f}%" if total > 0 else "N/A"

    print("\n" + "═" * W)
    print("  DATA GENERATION — QUALITY REPORT")
    print("═" * W)
    print(f"  Generated:                     {gen:>6}")
    print(f"  Pattern filter rejects:        {rej_a:>6}  {pct(rej_a):>8}")
    print(f"  Judge B rejects:               {rej_b:>6}  {pct(rej_b):>8}  [personalization, 20B]")
    print(f"  Judge C rejects:               {rej_c:>6}  {pct(rej_c):>8}  [distractor quality, 20B]")
    print(f"  Judge D rejects:               {rej_d:>6}  {pct(rej_d):>8}  [factual correctness, 20B]")
    print(f"  Final accepted:                {acc:>6}  {pct(acc):>8}")
    print(f"  Avg personalization score:     {avg_p:.2f} / 3.0")
    if elapsed > 0:
        print(f"  Elapsed:                       {elapsed/60:.1f} min")

    # ── Judge B sub-check pass rates ─────────────────────────────────
    sc = eval_stats.sub_check_totals
    sc_yes = eval_stats.sub_check_yes
    if sc.get("mastery_check_vocabulary", 0) > 0:
        print()
        print("  Judge B sub-check pass rates (of samples that reached Judge B):")
        b_checks = [
            ("mastery_check_vocabulary",              "mastery_vocabulary"),
            ("mastery_check_framing",                 "mastery_framing"),
            ("mastery_check_distractor_sophistication", "mastery_distractor_soph"),
            ("score_category_check_type_override",    "very_weak_type_override  ← watch"),
            ("score_category_check_difficulty",       "score_category_difficulty"),
            ("score_category_check_distractor_difficulty", "score_category_distr_diff"),
            ("misconception_check_new_angle",         "misconception_new_angle"),
            ("misconception_check_distractor_targets", "misconception_distr_target"),
            ("misconception_check_answer_addresses_gap", "misconception_answer_gap"),
        ]
        for raw_key, label in b_checks:
            total = sc.get(raw_key, 0)
            yes   = sc_yes.get(raw_key, 0)
            print(f"    {label:<40} {sc_pct(yes, total):>4}  ({yes}/{total})")

    # ── Judge C sub-check pass rates ─────────────────────────────────
    if sc.get("check_d1_different", 0) > 0:
        print()
        print("  Judge C sub-check pass rates:")
        c_checks = [
            ("check_d1_different",     "d1_different_from_answer"),
            ("check_d2_different",     "d2_different_from_answer"),
            ("check_d3_different",     "d3_different_from_answer"),
            ("check_mutual_diversity", "mutual_diversity"),
            ("check_plausibility",     "plausibility"),
            ("check_format_consistency", "format_consistency (advisory)"),
        ]
        for raw_key, label in c_checks:
            total = sc.get(raw_key, 0)
            yes   = sc_yes.get(raw_key, 0)
            print(f"    {label:<40} {sc_pct(yes, total):>4}  ({yes}/{total})")

    # ── Judge D sub-check pass rates ─────────────────────────────────
    if sc.get("answerability_check", 0) > 0:
        print()
        print("  Judge D sub-check pass rates:")
        d_fixed = [
            ("answerability_check", "answerability"),
            ("ambiguity_check",     "ambiguity (only one correct answer)"),
            ("explanation_check",   "explanation_correctness"),
        ]
        for raw_key, label in d_fixed:
            total = sc.get(raw_key, 0)
            yes   = sc_yes.get(raw_key, 0)
            print(f"    {label:<40} {sc_pct(yes, total):>4}  ({yes}/{total})")
        # Claim checks (variable count)
        claim_keys = sorted(k for k in sc if k.startswith("claim_") and k.endswith("_verified"))
        for raw_key in claim_keys:
            total = sc.get(raw_key, 0)
            yes   = sc_yes.get(raw_key, 0)
            label = raw_key.replace("_", " ")
            print(f"    {label:<40} {sc_pct(yes, total):>4}  ({yes}/{total})")

    print()
    print("  Worker key events:")
    print(f"    Primary keys active:           {len(worker_pool.active_keys)}")
    print(f"    Fallback keys consumed:        {len(FALLBACK_KEYS) - len(worker_pool.fallback_keys)}")
    print(f"    Hard failures:                 {len(worker_pool.failed_keys)}")
    print("═" * W + "\n")


def _print_report(
    all_stats: list,
    output_path: str,
    total_tasks: int,
    elapsed: float = 0.0,
    eval_stats: EvalStats | None = None,
    worker_pool: WorkerPool | None = None,
):
    """Print comprehensive final generation + quality report to terminal."""
    total_success = sum(s.success for s in all_stats)
    total_failure = sum(s.failure for s in all_stats)

    # ── Scan the output file for full statistics ────────────────────────
    type_dist:     Counter = Counter()
    mastery_dist:  Counter = Counter()
    category_dist: Counter = Counter()
    book_dist:     Counter = Counter()
    attempt_dist:  Counter = Counter()
    misconception_count = 0
    line_count = 0
    pscore_sum = 0.0

    path = Path(output_path)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    line_count += 1
                    type_dist[obj.get("question_type", "?")] += 1
                    mastery_dist[obj.get("mastery_level", "?")] += 1
                    category_dist[obj.get("score_category", "?")] += 1
                    book_dist[obj.get("_book", "?").split("/")[-1]] += 1
                    attempt_dist[obj.get("_attempts", 1)] += 1
                    if obj.get("misconception_context"):
                        misconception_count += 1
                    pscore_sum += obj.get("personalization_score", 0.0)
                except json.JSONDecodeError:
                    pass

    file_size_mb = path.stat().st_size / 1e6 if path.exists() else 0.0
    success_rate = 100 * total_success / max(total_tasks, 1)
    avg_attempts = (sum(k * v for k, v in attempt_dist.items()) / max(line_count, 1))
    miscon_pct   = 100 * misconception_count / max(line_count, 1)
    dg_estimate  = line_count * 3  # each MCQ yields 3 DG examples
    avg_pscore   = pscore_sum / max(line_count, 1)

    W = 66
    print("\n" + "═" * W)
    print("  MCQ DATA GENERATION — FINAL REPORT")
    print("═" * W)

    # ── Run summary ─────────────────────────────────────────────────────
    print("  RUN SUMMARY")
    print(f"  {'Chunks queued:':<30} {total_tasks}")
    print(f"  {'Successful generations:':<30} {total_success}")
    print(f"  {'Failures / retries exhausted:':<30} {total_failure}")
    print(f"  {'Success rate:':<30} {success_rate:.1f}%")
    if elapsed > 0:
        rate = total_success / max(elapsed, 1)
        print(f"  {'Elapsed time:':<30} {elapsed/60:.1f} min")
        print(f"  {'Throughput:':<30} {rate:.2f} samples/sec")
    print()

    # ── Per-worker ─────────────────────────────────────────────────────
    print("  PER-WORKER")
    for i, s in enumerate(all_stats):
        wr = 100 * s.success / max(s.success + s.failure, 1)
        print(f"    Worker {i}: {s.success:>5} success  {s.failure:>4} fail  ({wr:.0f}%)")
    print()

    # ── Question type distribution ───────────────────────────────────────
    print("  QUESTION TYPE DISTRIBUTION")
    for t in sorted(type_dist):
        c = type_dist[t]
        bar = "█" * int(40 * c / max(line_count, 1))
        print(f"    Type {t:<4}: {c:>5}  {bar}")
    print()

    # ── Mastery distribution ───────────────────────────────────────────
    print("  MASTERY DISTRIBUTION")
    for m in sorted(mastery_dist):
        c = mastery_dist[m]
        bar = "█" * int(40 * c / max(line_count, 1))
        print(f"    {m:<14}: {c:>5}  {bar}")
    print()

    # ── Score category distribution ────────────────────────────────────
    print("  SCORE CATEGORY DISTRIBUTION")
    for cat in sorted(category_dist):
        c = category_dist[cat]
        bar = "█" * int(40 * c / max(line_count, 1))
        print(f"    {cat:<12}: {c:>5}  {bar}")
    print()

    # ── Book breakdown ───────────────────────────────────────────────────
    print("  BOOK BREAKDOWN")
    for book in sorted(book_dist, key=lambda b: -book_dist[b]):
        c = book_dist[book]
        print(f"    {book:<40}: {c:>5} samples")
    print()

    # ── Attempt histogram ───────────────────────────────────────────────
    print("  RETRY HISTOGRAM  (attempts needed per successful sample)")
    for att in sorted(attempt_dist):
        c = attempt_dist[att]
        bar = "█" * int(40 * c / max(line_count, 1))
        print(f"    {att} attempt(s): {c:>5}  {bar}")
    print(f"    Average:       {avg_attempts:.2f} attempts/sample")
    print()

    # ── Dataset quality summary ────────────────────────────────────────
    print("  DATASET SUMMARY")
    print(f"  {'Total samples in file:':<36} {line_count}")
    print(f"  {'File size:':<36} {file_size_mb:.1f} MB")
    print(f"  {'Misconception-context samples:':<36} {misconception_count} ({miscon_pct:.1f}%)")
    print(f"  {'Est. DG training examples (x3):':<36} {dg_estimate}")
    print(f"  {'Avg personalization score:':<36} {avg_pscore:.2f} / 3.0")
    print(f"  {'Output file:':<36} {output_path}")

    # ── Mastery distribution validation ────────────────────────────────
    if line_count > 0:
        target_weights = {"Expert": 0.20, "Intermediate": 0.35, "Novice": 0.45}
        print()
        print("  MASTERY DISTRIBUTION VALIDATION")
        any_violation = False
        for m, target_pct in sorted(target_weights.items()):
            actual_count = mastery_dist.get(m, 0)
            actual_pct = actual_count / line_count
            diff = abs(actual_pct - target_pct)
            status = "OK" if diff <= 0.10 else "⚠ DRIFT"
            if diff > 0.10:
                any_violation = True
            print(f"    {m:<14}: actual={100*actual_pct:.1f}%  target={100*target_pct:.1f}%  [{status}]")
        if any_violation:
            print()
            print("  ⚠ WARNING: Mastery distribution has drifted >10pp from target.")
            print("    This may indicate a sampling bug or eligibility constraint.")

    print("═" * W + "\n")

    # ── Quality report (evaluation pipeline) ──────────────────────────
    if eval_stats is not None and worker_pool is not None:
        _print_quality_report(eval_stats, worker_pool, all_stats, elapsed)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="Generate MCQ training data from raw PDF books using Ollama.",
    )
    parser.add_argument(
        "--books", default=CONFIG["raw_books_dir"],
        help="Directory containing raw PDF books.",
    )
    parser.add_argument(
        "--output", default=CONFIG["output"],
        help="Output JSONL file path.",
    )
    parser.add_argument(
        "--workers", type=int, default=CONFIG["num_workers"],
        help="Number of parallel generation worker threads (max 4, one per generation key).",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=CONFIG["chunk_size"],
        help="Chunk size in characters.",
    )
    parser.add_argument(
        "--chunk-overlap", type=int, default=CONFIG["chunk_overlap"],
        help="Chunk overlap in characters.",
    )
    parser.add_argument(
        "--balanced-types", action="store_true", default=False,
        help=(
            "Enforce equal quota per question type. "
            "Each type gets len(chunks) // n_types tasks. "
            "Without this flag, types are sampled weighted by mastery distribution."
        ),
    )
    parser.add_argument(
        "--force-type", default=None, type=str,
        help=(
            "Force every task to use this question type, bypassing the "
            "content-aware selector entirely. Mastery is fixed to Expert, "
            "score_category is sampled 50/50 from moderate and strong. "
            "Use with --target for boost generation of underrepresented types."
        ),
    )
    parser.add_argument(
        "--target", type=int, default=None,
        help=(
            "Stop generation after this many successful samples. "
            "Primarily used with --force-type for boost generation."
        ),
    )
    parser.add_argument(
        "--skip-judges", action="store_true", default=False,
        help=(
            "Bypass all three LLM judges and write all structurally-valid MCQs "
            "directly to the output file. Useful for fast test runs or when "
            "judge keys are unavailable."
        ),
    )
    args = parser.parse_args()

    # ── Validate key availability ────────────────────────────────────────
    gen_keys = GENERATION_KEYS
    fallback = FALLBACK_KEYS
    all_gen_keys = gen_keys + fallback

    if not all_gen_keys:
        print(
            "ERROR: No generation keys found.\n"
            "Set OLLAMA_API_KEY_1..4 (primary) and/or "
            "OLLAMA_API_KEY_8..9 (fallback) in .env"
        )
        sys.exit(1)

    judge_keys_available = bool(JUDGE_B_KEY and JUDGE_C_KEY and JUDGE_D_KEY)
    if not judge_keys_available and not args.skip_judges:
        print(
            "WARNING: One or more judge keys missing "
            "(OLLAMA_API_KEY_5/6/7). LLM judges will be skipped.\n"
            "Use --skip-judges to silence this warning."
        )
        args.skip_judges = True

    # ── Print pipeline config ────────────────────────────────────────────
    print()
    print(f"  Generation model: {GENERATION_MODEL}")
    print(f"  Judge model:      {JUDGE_MODEL}")
    print(f"  Generation keys:  {len(gen_keys)} primary + {len(fallback)} fallback")
    if args.skip_judges:
        print("  Judges:           SKIPPED")
    else:
        print(f"  Judge B key:      {'SET' if JUDGE_B_KEY else 'MISSING'}")
        print(f"  Judge C key:      {'SET' if JUDGE_C_KEY else 'MISSING'}")
        print(f"  Judge D key:      {'SET' if JUDGE_D_KEY else 'MISSING'}")

    # ── Build generation key pool ────────────────────────────────────────
    key_pool = KeyPool(
        primary=gen_keys,
        backup=fallback,
        fail_threshold=CONFIG["key_fail_threshold"],
        cooldown=CONFIG["key_cooldown"],
    )

    # WorkerPool tracks hard failures and manages fallback cycling
    worker_pool = WorkerPool(
        primary_keys=gen_keys,
        fallback_keys=list(fallback),  # copy — WorkerPool mutates it
    )

    num_workers = min(args.workers, max(len(all_gen_keys), 1))
    logger.info(
        "data_generator_starting",
        workers=num_workers,
        generation_keys=len(gen_keys),
        fallback_keys=len(fallback),
        generation_model=GENERATION_MODEL,
        judge_model=JUDGE_MODEL,
        skip_judges=args.skip_judges,
        books_dir=args.books,
    )
    print(f"  Workers: {num_workers}")

    # ── Build judge clients (20B model, one per dedicated key) ───────────
    if not args.skip_judges:
        judge_b_client = _make_ollama_client(JUDGE_B_KEY, model=JUDGE_MODEL)
        judge_c_client = _make_ollama_client(JUDGE_C_KEY, model=JUDGE_MODEL)
        judge_d_client = _make_ollama_client(JUDGE_D_KEY, model=JUDGE_MODEL)
    else:
        judge_b_client = judge_c_client = judge_d_client = None

    # ── Ensure output directory exists ──────────────────────────────────
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    # ── Load chunks from PDFs (Scipy excluded automatically) ─────────────
    chunks = _load_chunks_from_pdfs(args.books, args.chunk_size, args.chunk_overlap)
    if not chunks:
        print("ERROR: No chunks loaded from books directory.")
        sys.exit(1)

    # Generate synthetic chunks to replace the removed Scipy PDF examples.
    # All generation keys are passed so the function can cycle through them
    # on per-call failures.  A JSONL cache file sits next to mcq_raw.jsonl so
    # an interrupted run reloads completed chunks instead of regenerating them.
    if all_gen_keys and not args.force_type:
        n_syn = CONFIG.get("n_synthetic_chunks", 180)
        _syn_cache = str(Path(args.output).parent / "mcq_synthetic_chunks_cache.jsonl")
        synthetic = generate_synthetic_chunks(
            n_chunks=n_syn,
            api_keys=all_gen_keys,
            cache_path=_syn_cache,
        )
        if synthetic:
            chunks = chunks + synthetic
            logger.info(
                "synthetic_chunks_added",
                synthetic=len(synthetic),
                total=len(chunks),
            )
        else:
            logger.warning("no_synthetic_chunks_generated")

    # Resumability: skip already-processed chunks
    existing_hashes = _load_existing_hashes(args.output)

    # ── Build task list ──────────────────────────────────────────────────
    if args.force_type:
        tasks = _build_tasks(chunks, existing_hashes, balanced_types=False)
        rng = random.Random(42)
        forced_tasks = []
        for i, task in enumerate(tasks):
            task["question_type"] = args.force_type
            task["mastery"] = "Expert"
            task["score_category"] = "moderate" if i % 2 == 0 else "strong"
            task["misconception_context"] = None
            forced_tasks.append(task)
        tasks = forced_tasks
        print(f"  Force-type mode: all tasks → Type {args.force_type}, Expert mastery")
        print(f"  Score categories: 50% moderate, 50% strong")
        if args.target:
            print(f"  Target: stop after {args.target} successful samples")
    else:
        tasks = _build_tasks(chunks, existing_hashes, balanced_types=args.balanced_types)

    if args.balanced_types:
        print(f"  Balanced mode: equal quota per question type")

    if not tasks:
        print("All chunks already processed. Nothing to do.")
        return

    # ── Build queues ─────────────────────────────────────────────────────
    task_queue: queue.Queue = queue.Queue()
    for task in tasks:
        task_queue.put(task)

    eval_queue: queue.Queue = queue.Queue(maxsize=CONFIG["eval_queue_maxsize"])

    total_tasks = len(tasks)
    logger.info("tasks_queued", total=total_tasks)

    # ── Shared state ─────────────────────────────────────────────────────
    file_lock  = threading.Lock()
    pbar_lock  = threading.Lock()
    eval_stats = EvalStats()
    all_stats: list[WorkerStats] = []

    display_total = args.target if args.target else total_tasks
    pbar = tqdm(
        total=display_total,
        desc="Generating MCQs",
        unit="task",
        dynamic_ncols=True,
        colour="green",
    )

    target_counter = None
    if args.target:
        target_counter = {
            "target": args.target,
            "count": 0,
            "lock": threading.Lock(),
        }

    # ── Launch evaluation worker first ───────────────────────────────────
    # The evaluation worker drains eval_queue and applies judges.
    # If judges are skipped, it writes all items directly.
    if args.skip_judges:
        # Fast path: bypass all judges — write directly in eval thread
        def _direct_eval_worker():
            while True:
                try:
                    item = eval_queue.get(timeout=10)
                except queue.Empty:
                    continue
                if item is None:
                    eval_queue.task_done()
                    break
                eval_stats.add_generated()
                eval_stats.add_accepted(item.get("personalization_score", 0.0))
                with file_lock:
                    with open(args.output, "a", encoding="utf-8") as f:
                        f.write(json.dumps(item) + "\n")
                eval_queue.task_done()

        eval_thread = threading.Thread(target=_direct_eval_worker, daemon=True)
    else:
        eval_thread = threading.Thread(
            target=_evaluation_worker,
            args=(
                eval_queue, args.output, file_lock,
                judge_b_client, judge_c_client, judge_d_client,
                eval_stats,
            ),
            daemon=True,
        )
    eval_thread.start()

    # ── Launch generation workers ────────────────────────────────────────
    gen_threads: list[threading.Thread] = []
    for i in range(num_workers):
        stats = WorkerStats()
        all_stats.append(stats)
        t = threading.Thread(
            target=_worker,
            args=(
                i, key_pool, task_queue, eval_queue,
                stats, all_stats, pbar, pbar_lock,
                target_counter,
            ),
            daemon=True,
        )
        t.start()
        gen_threads.append(t)

    t_start = time.time()
    try:
        for t in gen_threads:
            t.join()
    except KeyboardInterrupt:
        print("\n\nInterrupted — partial results saved. Run again to resume.")
    finally:
        elapsed = time.time() - t_start
        success_total = sum(s.success for s in all_stats)
        failure_total = sum(s.failure for s in all_stats)
        pbar.set_postfix(success=success_total, fail=failure_total)
        pbar.close()

    # Signal evaluation worker to stop and wait for it to drain
    eval_queue.put(None)
    eval_thread.join()

    _print_report(
        all_stats,
        args.output,
        total_tasks,
        elapsed=elapsed,
        eval_stats=eval_stats,
        worker_pool=worker_pool,
    )


if __name__ == "__main__":
    main()
