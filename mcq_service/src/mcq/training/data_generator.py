"""Training data generator — multi-threaded Ollama pipeline for QG/DG pairs.

Generates raw MCQ training data by calling Ollama to produce complete MCQ
objects (question + correct answer + 3 distractors) for each chunk sampled
with weighted mastery/score_category distributions.  Workers write results
thread-safely to a single JSONL output file.

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
from pathlib import Path

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
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

CONFIG = {
    # Primary key set — used first
    "api_keys_primary": [
        k for k in [
            os.getenv("OLLAMA_API_KEY_1"),
            os.getenv("OLLAMA_API_KEY_2"),
            os.getenv("OLLAMA_API_KEY_3"),
            os.getenv("OLLAMA_API_KEY_4"),
        ] if k
    ],
    # Backup key set — activated when primary keys fail
    "api_keys_backup": [
        k for k in [
            os.getenv("OLLAMA_API_KEY_B1"),
            os.getenv("OLLAMA_API_KEY_B2"),
            os.getenv("OLLAMA_API_KEY_B3"),
            os.getenv("OLLAMA_API_KEY_B4"),
            os.getenv("OLLAMA_API_KEY_B5"),
        ] if k
    ],
    "ollama_host": os.getenv("OLLAMA_HOST", "https://ollama.com"),
    "model": os.getenv("OLLAMA_MODEL", "gpt-oss:120b"),
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


def _load_chunks_from_pdfs(books_dir: str, chunk_size: int, chunk_overlap: int) -> list[dict]:
    """Load and chunk all PDFs from the books directory.

    Books are processed in **alphabetical order** so the task queue always
    starts from the first book, first chunk.  Chunk artifacts (headers,
    page numbers, edition lines) are stripped before returning.
    """
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    books_path = Path(books_dir)
    if not books_path.exists():
        logger.error("books_dir_not_found", path=books_dir)
        return []

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
        logger.info("book_order", index=i + 1, name=p.name)

    for pdf_path in pdf_files:
        try:
            loader = PyPDFLoader(str(pdf_path))
            pages = loader.load()
            splits = splitter.split_documents(pages)
            book_stem = pdf_path.stem
            for doc in splits:
                raw_text = doc.page_content.strip()
                text = _clean_chunk_text(raw_text, book_stem)
                if len(text) < 50:
                    continue
                # Use the PDF filename stem as topic — ignore langchain's
                # metadata.topic which leaks page-level noise.
                all_chunks.append({
                    "text": text,
                    "topic": book_stem,
                    "book": pdf_path.name,
                })
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
            mastery = random.choice(compatible_masteries) if compatible_masteries \
                else _weighted_sample(MASTERY_WEIGHTS)

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


def _make_ollama_client(api_key: str):
    """Create an OllamaClient with a specific API key."""
    pathway_src = str(
        Path(__file__).resolve().parent.parent.parent.parent.parent / "course_pathway" / "src"
    )
    if pathway_src not in sys.path:
        sys.path.insert(0, pathway_src)

    from pathway.llm.naming import OllamaClient  # type: ignore

    return OllamaClient(
        host=CONFIG["ollama_host"],
        model=CONFIG["model"],
        api_key=api_key,
        max_retries=3,
        timeout=180,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PROMPT BUILDING
# ═══════════════════════════════════════════════════════════════════════════════


def _build_generation_prompt(task: dict) -> str:
    """Build a combined QG+DG generation prompt for a single MCQ."""
    mcq_src = str(Path(__file__).resolve().parent.parent.parent)
    if mcq_src not in sys.path:
        sys.path.insert(0, mcq_src)

    from mcq.question_types import QUESTION_TYPE_TAXONOMY
    from mcq.scoring_categories import score_category_description

    category_desc = score_category_description(task["score_category"])
    misconception_block = ""
    if task["misconception_context"]:
        misconception_block = f"""
MISCONCEPTION CONTEXT:
Previously, {task['misconception_context']}.
Generate a question that approaches this topic from a different angle to
address the underlying gap.  One distractor should target the same
misconception from a new perspective.
"""

    return f"""\
You are an expert educational question writer.

{QUESTION_TYPE_TAXONOMY}

TASK: Generate a complete multiple-choice question of Type {task['question_type']} \
for the topic "{task['topic']}".

STUDENT PROFILE:
- Mastery level: {task['mastery']}
- Topic score category: {task['score_category']}
- {category_desc}
{misconception_block}
SOURCE CONTENT:
\"\"\"
{task['text']}
\"\"\"

Generate exactly ONE question with the correct answer, explanation, and exactly \
3 wrong-but-plausible distractors.

REQUIREMENTS:
1. The question MUST be Type {task['question_type']} as defined in the taxonomy.
2. The question must be answerable from the source content alone.
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
# KEY POOL  — thread-safe primary ↔ backup rotation
# ═══════════════════════════════════════════════════════════════════════════════


class KeyPool:
    """Thread-safe API key pool with primary→backup→primary rotation.

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
    output_path: str,
    file_lock: threading.Lock,
    stats: WorkerStats,
    all_stats: list,
    pbar: tqdm,
    pbar_lock: threading.Lock,
):
    """Worker thread: pulls tasks, calls Ollama, writes results.

    Owns one active API key at a time. On any API/network error the key is
    reported to KeyPool which returns the next best key — possibly from the
    backup set. Validation errors (bad JSON structure) keep the current key
    and only append feedback to the conversation.
    """
    current_key = key_pool.get_initial_key()
    client = _make_ollama_client(current_key)

    while True:
        # Stop if KeyPool has determined that all keys are permanently dead
        if key_pool.all_failed:
            logger.error("worker_stopping_all_keys_failed", worker=worker_id)
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
                    client = _make_ollama_client(current_key)

                if key_pool.all_failed:
                    break

                if attempt < CONFIG["max_retries"]:
                    # Reset conversation history — start fresh with new key
                    messages = [{"role": "user", "content": prompt}]
                    time.sleep(CONFIG["retry_delay"])

        if result is not None:
            with file_lock:
                with open(output_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(result) + "\n")
            stats.record_success()
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
# FINAL REPORT
# ═══════════════════════════════════════════════════════════════════════════════


def _print_report(
    all_stats: list[WorkerStats],
    output_path: str,
    total_tasks: int,
    elapsed: float = 0.0,
):
    """Print comprehensive final generation report to terminal."""
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
                except json.JSONDecodeError:
                    pass

    file_size_mb = path.stat().st_size / 1e6 if path.exists() else 0.0
    success_rate = 100 * total_success / max(total_tasks, 1)
    avg_attempts = (sum(k * v for k, v in attempt_dist.items()) / max(line_count, 1))
    miscon_pct   = 100 * misconception_count / max(line_count, 1)
    dg_estimate  = line_count * 3  # each MCQ yields 3 DG examples

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
    print(f"  {'Output file:':<36} {output_path}")
    print("═" * W + "\n")


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
        help="Number of parallel worker threads.",
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
    args = parser.parse_args()

    # Build KeyPool from primary + backup key sets
    primary_keys = CONFIG["api_keys_primary"]
    backup_keys  = CONFIG["api_keys_backup"]
    all_keys = primary_keys + backup_keys
    if not all_keys:
        print("ERROR: No valid API keys found. Set OLLAMA_API_KEY_1..4 in .env")
        sys.exit(1)

    key_pool = KeyPool(
        primary=primary_keys,
        backup=backup_keys,
        fail_threshold=CONFIG["key_fail_threshold"],
        cooldown=CONFIG["key_cooldown"],
    )

    num_workers = min(args.workers, len(all_keys))
    logger.info(
        "data_generator_starting",
        workers=num_workers,
        primary_keys=len(primary_keys),
        backup_keys=len(backup_keys),
        books_dir=args.books,
    )
    print(f"  Keys: {len(primary_keys)} primary + {len(backup_keys)} backup = {len(all_keys)} total")
    print(f"  Workers: {num_workers}")

    # Ensure output directory exists
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    # Load chunks
    chunks = _load_chunks_from_pdfs(args.books, args.chunk_size, args.chunk_overlap)
    if not chunks:
        print("ERROR: No chunks loaded from books directory.")
        sys.exit(1)

    # Resumability: skip already-processed chunks
    existing_hashes = _load_existing_hashes(args.output)
    tasks = _build_tasks(chunks, existing_hashes, balanced_types=args.balanced_types)

    if args.balanced_types:
        print(f"  Balanced mode: equal quota per question type")

    if not tasks:
        print("All chunks already processed. Nothing to do.")
        return

    # Build task queue
    task_queue: queue.Queue = queue.Queue()
    for task in tasks:
        task_queue.put(task)

    total_tasks = len(tasks)
    logger.info("tasks_queued", total=total_tasks)

    # Shared state
    file_lock = threading.Lock()
    pbar_lock = threading.Lock()
    all_stats: list[WorkerStats] = []

    # tqdm progress bar
    pbar = tqdm(
        total=total_tasks,
        desc="Generating MCQs",
        unit="task",
        dynamic_ncols=True,
        colour="green",
    )

    # Start workers — all share the KeyPool, each gets its own stats
    threads: list[threading.Thread] = []
    for i in range(num_workers):
        stats = WorkerStats()
        all_stats.append(stats)
        t = threading.Thread(
            target=_worker,
            args=(
                i, key_pool, task_queue, args.output,
                file_lock, stats, all_stats, pbar, pbar_lock,
            ),
            daemon=True,
        )
        t.start()
        threads.append(t)

    t_start = time.time()
    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\n\nInterrupted — partial results saved. Run again to resume.")
    finally:
        elapsed = time.time() - t_start
        success_total = sum(s.success for s in all_stats)
        failure_total = sum(s.failure for s in all_stats)
        pbar.set_postfix(success=success_total, fail=failure_total)
        pbar.close()

    _print_report(all_stats, args.output, total_tasks, elapsed=elapsed)


if __name__ == "__main__":
    main()
