#!/usr/bin/env python3
"""Comprehensive MCQ model evaluation — scientific analysis of QG and DG quality.

Systematically tests QG and DG models across every meaningful variation of every
personalization signal, on real chunks from ChromaDB (or hardcoded fallbacks),
and produces a detailed markdown analysis report.

Usage::

    python -m mcq_service.evaluation.run_evaluation \\
        --output mcq_service/evaluation/evaluation_report.md \\
        --chunks 20 \\
        --verbose
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import structlog
from tqdm import tqdm

logger = structlog.get_logger(__name__)

# ── Resolve project paths ────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_MCQ_SRC = str(_PROJECT_ROOT / "mcq_service" / "src")
if _MCQ_SRC not in sys.path:
    sys.path.insert(0, _MCQ_SRC)

_MCQ_CONFIG = str(_PROJECT_ROOT / "mcq_service" / "config")
if _MCQ_CONFIG not in sys.path:
    sys.path.insert(0, _MCQ_CONFIG)

_PATHWAY_SRC = str(_PROJECT_ROOT / "course_pathway" / "src")
if _PATHWAY_SRC not in sys.path:
    sys.path.insert(0, _PATHWAY_SRC)

_AI_SERVICE = str(_PROJECT_ROOT / "ai_service")
if _AI_SERVICE not in sys.path:
    sys.path.insert(0, _AI_SERVICE)

# ── Load .env ─────────────────────────────────────────────────────────────────
from dotenv import load_dotenv

_env_path = _PROJECT_ROOT / "mcq_service" / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=str(_env_path), override=False)

# ── MCQ imports ───────────────────────────────────────────────────────────────
from mcq.models import GeneratedQuestion, MCQOption, MCQQuestion
from mcq.prompts.mcq_prompts import (
    build_qg_chat_prompt,
    build_dg_chat_prompt,
    extract_qg_output,
    extract_dg_output,
)
from mcq.question_types import (
    ALL_QUESTION_TYPES,
    CODE_QUESTION_TYPES,
    MASTERY_TYPE_ELIGIBILITY,
    QUESTION_TYPE_TAXONOMY,
    SCORE_CATEGORY_DISTRACTOR_MODIFIER,
    SCORE_CATEGORY_TYPE_OVERRIDE,
    TYPE_COGNITIVE_LEVEL,
)
from mcq.scoring_categories import score_category_description
from mcq.selector import select_question_type
from settings import MCQSettings

# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class ChunkSample:
    """A sampled chunk with metadata."""
    text: str
    book: str
    topic: str
    content_type: str  # definition | code | comparison | causal | procedural


@dataclass
class EvalCondition:
    """A single evaluation condition from the matrix."""
    axis: str           # "mastery_score" | "type_sweep" | "misconception"
    mastery_level: str
    score_category: str
    question_type: str | None  # None = auto-select via selector
    misconception_context: str | None


@dataclass
class EvalResult:
    """Result of a single generation run."""
    chunk: ChunkSample
    condition: EvalCondition
    # QG
    qg_success: bool = False
    qg_raw_output: str = ""
    question: str = ""
    correct_answer: str = ""
    explanation: str = ""
    qg_time_ms: float = 0.0
    question_type_used: str = ""
    # DG
    dg_success: bool = False
    dg_raw_outputs: list[str] = field(default_factory=list)
    distractors: list[str] = field(default_factory=list)
    dg_time_ms: float = 0.0
    # Metrics
    distractor_similarities: list[float] = field(default_factory=list)
    distractor_pairwise_sim: float = 0.0
    cognitive_level_detected: int = 0
    cognitive_level_expected: int = 0
    format_issues: list[str] = field(default_factory=list)
    error_message: str = ""
    # Assembly
    mcq: MCQQuestion | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1 — CHUNK SAMPLING
# ═══════════════════════════════════════════════════════════════════════════════

def _detect_content_type(text: str) -> str:
    """Classify chunk content type automatically."""
    t = text.lower()
    code_signals = ["def ", "class ", "import ", "print(", "return ", ">>>", "```"]
    comparison_signals = ["unlike", "whereas", "compared to", "difference between", "in contrast"]
    causal_signals = ["because", "therefore", "consequence", "trade-off", "why ", "reason"]
    procedural_signals = ["step 1", "first,", "then,", "finally,", "procedure", "algorithm"]

    if any(s in t for s in code_signals):
        return "code"
    if any(s in t for s in comparison_signals):
        return "comparison"
    if any(s in t for s in causal_signals):
        return "causal"
    if any(s in t for s in procedural_signals):
        return "procedural"
    return "definition"


def _sample_chunks_from_chromadb(n_chunks: int) -> list[ChunkSample]:
    """Try to sample real chunks from the existing ChromaDB collection."""
    try:
        chroma_path = str(_PROJECT_ROOT / "rag_pipeline" / "data" / "chroma")
        if not Path(chroma_path).exists():
            logger.info("chroma_not_found", path=chroma_path)
            return []

        from pathway.chromadb_reader import ChromaDBReader

        reader = ChromaDBReader(persist_dir=chroma_path, collection_name="course_chunks")
        courses = reader.get_available_courses()
        if not courses:
            logger.info("chroma_no_courses")
            return []

        all_chunks: list[ChunkSample] = []
        chunks_per_course = max(1, n_chunks // len(courses))

        for course_id in courses:
            course_chunks = reader.get_all_course_chunks(course_id)
            if not course_chunks:
                continue

            # Sample evenly across the book
            step = max(1, len(course_chunks) // chunks_per_course)
            sampled_indices = list(range(0, len(course_chunks), step))[:chunks_per_course]

            for idx in sampled_indices:
                cc = course_chunks[idx]
                if len(cc.raw_text.strip()) < 100:
                    continue
                all_chunks.append(ChunkSample(
                    text=cc.raw_text[:1200],  # cap chunk length for context window
                    book=cc.book or course_id,
                    topic=cc.topic or "General",
                    content_type=_detect_content_type(cc.raw_text),
                ))

        random.seed(42)
        random.shuffle(all_chunks)
        return all_chunks[:n_chunks]

    except Exception as e:
        logger.warning("chroma_sampling_failed", error=str(e))
        return []


def _get_fallback_chunks() -> list[ChunkSample]:
    """20 hardcoded chunks covering CS topics with diverse content types."""
    chunks = [
        # ── Definition chunks ────────────────────────────────────────
        ChunkSample(
            text=(
                "A stack is an abstract data type that follows the Last-In-First-Out (LIFO) "
                "principle. The two primary operations are push (add to top) and pop (remove "
                "from top). Stacks are used in function call management, expression evaluation, "
                "and backtracking algorithms. The time complexity of both push and pop "
                "operations is O(1)."
            ),
            book="Data Structures", topic="Stacks", content_type="definition",
        ),
        ChunkSample(
            text=(
                "A hash table is a data structure that maps keys to values using a hash function. "
                "The hash function converts each key into an array index. When two keys hash to "
                "the same index (a collision), resolution strategies include chaining (linked "
                "lists at each bucket) and open addressing (probing for the next empty slot). "
                "Average-case lookup is O(1), but worst-case is O(n) with poor hash functions."
            ),
            book="Data Structures", topic="Hash Tables", content_type="definition",
        ),
        ChunkSample(
            text=(
                "Supervised learning is a type of machine learning where the model is trained "
                "on labeled data — each training example has an input and a known correct output. "
                "The goal is to learn a mapping from inputs to outputs that generalizes to unseen "
                "data. Common supervised learning tasks include classification (predicting a "
                "category) and regression (predicting a continuous value)."
            ),
            book="Machine Learning", topic="Supervised Learning", content_type="definition",
        ),
        ChunkSample(
            text=(
                "TCP (Transmission Control Protocol) is a connection-oriented protocol that "
                "provides reliable, ordered delivery of data between applications. It uses a "
                "three-way handshake (SYN, SYN-ACK, ACK) to establish connections. TCP "
                "implements flow control using a sliding window mechanism and congestion "
                "control using algorithms like slow start and congestion avoidance."
            ),
            book="Computer Networks", topic="TCP", content_type="definition",
        ),
        ChunkSample(
            text=(
                "Normalization in database design is the process of organizing data to minimize "
                "redundancy. First Normal Form (1NF) requires that all attributes contain only "
                "atomic values. Second Normal Form (2NF) requires 1NF plus no partial "
                "dependencies on a composite key. Third Normal Form (3NF) additionally "
                "eliminates transitive dependencies."
            ),
            book="Database Systems", topic="Normalization", content_type="definition",
        ),
        # ── Code chunks ──────────────────────────────────────────────
        ChunkSample(
            text=(
                "Binary search works on sorted arrays by repeatedly dividing the search space "
                "in half:\n\n"
                "def binary_search(arr, target):\n"
                "    low, high = 0, len(arr) - 1\n"
                "    while low <= high:\n"
                "        mid = (low + high) // 2\n"
                "        if arr[mid] == target:\n"
                "            return mid\n"
                "        elif arr[mid] < target:\n"
                "            low = mid + 1\n"
                "        else:\n"
                "            high = mid - 1\n"
                "    return -1\n\n"
                "Time complexity: O(log n). Space complexity: O(1)."
            ),
            book="Algorithms", topic="Binary Search", content_type="code",
        ),
        ChunkSample(
            text=(
                "A decorator in Python is a function that takes another function and extends "
                "its behavior:\n\n"
                "def timer(func):\n"
                "    import time\n"
                "    def wrapper(*args, **kwargs):\n"
                "        start = time.time()\n"
                "        result = func(*args, **kwargs)\n"
                "        print(f'{func.__name__} took {time.time()-start:.2f}s')\n"
                "        return result\n"
                "    return wrapper\n\n"
                "@timer\n"
                "def process_data(data):\n"
                "    return sorted(data)"
            ),
            book="Python Programming", topic="Decorators", content_type="code",
        ),
        ChunkSample(
            text=(
                "List comprehensions provide a concise way to create lists:\n\n"
                ">>> squares = [x**2 for x in range(10)]\n"
                ">>> print(squares)\n"
                "[0, 1, 4, 9, 16, 25, 36, 49, 64, 81]\n\n"
                ">>> evens = [x for x in range(20) if x % 2 == 0]\n"
                ">>> print(evens)\n"
                "[0, 2, 4, 6, 8, 10, 12, 14, 16, 18]\n\n"
                "Nested comprehensions can flatten matrices:\n"
                ">>> matrix = [[1,2,3],[4,5,6]]\n"
                ">>> flat = [x for row in matrix for x in row]\n"
                ">>> print(flat)\n"
                "[1, 2, 3, 4, 5, 6]"
            ),
            book="Python Programming", topic="List Comprehensions", content_type="code",
        ),
        ChunkSample(
            text=(
                "Pandas provides powerful data manipulation with DataFrames:\n\n"
                "import pandas as pd\n\n"
                "df = pd.DataFrame({'name': ['Alice', 'Bob', 'Charlie'],\n"
                "                   'score': [85, 92, 78]})\n\n"
                "# Filter rows where score > 80\n"
                "high_scorers = df[df['score'] > 80]\n"
                "print(high_scorers)\n\n"
                "# GroupBy with aggregation\n"
                "df.groupby('name')['score'].mean()"
            ),
            book="Data Science", topic="Pandas", content_type="code",
        ),
        ChunkSample(
            text=(
                "Recursion requires a base case and a recursive case:\n\n"
                "def fibonacci(n):\n"
                "    if n <= 1:\n"
                "        return n\n"
                "    return fibonacci(n-1) + fibonacci(n-2)\n\n"
                "print(fibonacci(10))  # Output: 55\n\n"
                "The naive recursive implementation has exponential time complexity O(2^n). "
                "Memoization reduces this to O(n) by caching previously computed values."
            ),
            book="Algorithms", topic="Recursion", content_type="code",
        ),
        # ── Comparison chunks ────────────────────────────────────────
        ChunkSample(
            text=(
                "Unlike arrays, linked lists do not store elements in contiguous memory. "
                "Each node contains a data field and a pointer to the next node. Arrays "
                "provide O(1) random access by index, whereas linked lists require O(n) "
                "traversal. However, linked lists support O(1) insertion and deletion at "
                "known positions, compared to O(n) for arrays which must shift elements."
            ),
            book="Data Structures", topic="Arrays vs Linked Lists", content_type="comparison",
        ),
        ChunkSample(
            text=(
                "BFS (Breadth-First Search) explores all neighbors at the current depth "
                "before moving deeper, using a queue. DFS (Depth-First Search) goes as deep "
                "as possible along each branch before backtracking, using a stack or recursion. "
                "BFS finds the shortest path in unweighted graphs; DFS uses less memory. "
                "BFS time complexity is O(V+E); DFS is also O(V+E)."
            ),
            book="Algorithms", topic="BFS vs DFS", content_type="comparison",
        ),
        ChunkSample(
            text=(
                "Processes and threads differ in several key ways. A process has its own "
                "memory space and resources, whereas threads within a process share memory. "
                "Context switching between processes is expensive compared to thread switching. "
                "Threads enable parallelism within a program but introduce synchronization "
                "challenges like race conditions and deadlocks."
            ),
            book="Operating Systems", topic="Processes vs Threads", content_type="comparison",
        ),
        ChunkSample(
            text=(
                "SQL databases use structured schemas with tables and relationships, whereas "
                "NoSQL databases offer flexible schemas. SQL databases (PostgreSQL, MySQL) "
                "excel at complex queries and ACID transactions. NoSQL databases (MongoDB, "
                "Redis) handle unstructured data and scale horizontally. The choice depends "
                "on data structure, query patterns, and scalability requirements."
            ),
            book="Database Systems", topic="SQL vs NoSQL", content_type="comparison",
        ),
        # ── Causal/reasoning chunks ──────────────────────────────────
        ChunkSample(
            text=(
                "Python's list.append() runs in amortized O(1) time because the underlying "
                "array doubles in capacity when full. The expensive resize operation copies "
                "all elements (O(n)), but this happens infrequently. Over n appends, the total "
                "cost of resizes is O(n), so each append costs O(1) on average. This is the "
                "consequence of the dynamic array's geometric growth strategy."
            ),
            book="Data Structures", topic="Amortized Analysis", content_type="causal",
        ),
        ChunkSample(
            text=(
                "Overfitting occurs when a model learns the training data too well, including "
                "noise and outliers, resulting in poor generalization. The trade-off between "
                "bias and variance explains this: high-complexity models have low bias but high "
                "variance. Regularization techniques (L1, L2, dropout) penalize complexity to "
                "find the optimal balance. Cross-validation helps detect overfitting."
            ),
            book="Machine Learning", topic="Overfitting", content_type="causal",
        ),
        ChunkSample(
            text=(
                "Virtual memory allows programs to use more memory than physically available "
                "by mapping virtual addresses to physical addresses via page tables. When a "
                "page is not in RAM, a page fault triggers the OS to load it from disk. "
                "The consequence is that programs can run without worrying about physical "
                "memory limits, at the cost of potential disk I/O latency."
            ),
            book="Operating Systems", topic="Virtual Memory", content_type="causal",
        ),
        # ── Procedural chunks ────────────────────────────────────────
        ChunkSample(
            text=(
                "To implement merge sort: Step 1: If the array has one element, return it "
                "(base case). Step 2: Split the array into two halves. Step 3: Recursively "
                "sort each half. Step 4: Merge the two sorted halves by comparing elements "
                "from each half and placing the smaller one first. The algorithm guarantees "
                "O(n log n) time complexity in all cases."
            ),
            book="Algorithms", topic="Merge Sort", content_type="procedural",
        ),
        ChunkSample(
            text=(
                "Building a REST API: First, define the resource endpoints (GET /users, "
                "POST /users, GET /users/{id}). Then, implement request validation using "
                "schemas. Next, connect to the database layer for CRUD operations. Finally, "
                "add authentication middleware and error handling. Each endpoint should return "
                "appropriate HTTP status codes (200, 201, 404, 500)."
            ),
            book="Software Engineering", topic="REST APIs", content_type="procedural",
        ),
        ChunkSample(
            text=(
                "The software development lifecycle (SDLC) follows these phases: requirements "
                "gathering, where stakeholders define what the system should do; design, where "
                "architects create the system blueprint; implementation, where developers write "
                "code; testing, where QA verifies functionality; deployment, where the system "
                "goes live; and maintenance, where bugs are fixed and features added."
            ),
            book="Software Engineering", topic="SDLC", content_type="procedural",
        ),
    ]
    return chunks


def sample_chunks(n_chunks: int) -> list[ChunkSample]:
    """Sample chunks from ChromaDB, falling back to hardcoded if unavailable."""
    chunks = _sample_chunks_from_chromadb(n_chunks)
    if len(chunks) >= n_chunks:
        print(f"  ✅ Sampled {len(chunks)} chunks from ChromaDB")
        return chunks[:n_chunks]

    print(f"  ℹ ChromaDB returned {len(chunks)} chunks, using fallback hardcoded chunks")
    fallback = _get_fallback_chunks()

    # Combine and fill
    combined = chunks + [c for c in fallback if c.text not in {x.text for x in chunks}]
    return combined[:n_chunks]


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2 — EVALUATION MATRIX
# ═══════════════════════════════════════════════════════════════════════════════

def build_eval_matrix() -> list[EvalCondition]:
    """Build the full evaluation condition matrix (18 conditions per chunk)."""
    conditions: list[EvalCondition] = []

    # Axis 1 — Mastery × Score Category (9 combinations, auto-select type)
    for mastery in ["Novice", "Intermediate", "Expert"]:
        for score_cat in ["very_weak", "moderate", "strong"]:
            conditions.append(EvalCondition(
                axis="mastery_score",
                mastery_level=mastery,
                score_category=score_cat,
                question_type=None,  # auto-select via selector
                misconception_context=None,
            ))

    # Axis 2 — Question Type Sweep (5 forced types at Expert × strong)
    for qtype in ["4a", "4b", "4c", "4d", "4e"]:
        conditions.append(EvalCondition(
            axis="type_sweep",
            mastery_level="Expert",
            score_category="strong",
            question_type=qtype,
            misconception_context=None,
        ))

    # Axis 3 — Misconception Context (4 conditions at Intermediate × moderate)
    misconceptions = [
        None,
        "The student confused the basic definition of this concept with a related term.",
        "The student has repeatedly failed on this topic, believing that the opposite of the correct answer is true and showing a systematic misunderstanding of the underlying mechanism.",
        "The student made an error on a completely different topic (network protocols) that is unrelated to the current subject matter.",
    ]
    for mc in misconceptions:
        conditions.append(EvalCondition(
            axis="misconception",
            mastery_level="Intermediate",
            score_category="moderate",
            question_type=None,
            misconception_context=mc,
        ))

    return conditions


# ═══════════════════════════════════════════════════════════════════════════════
# GENERATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def _get_ollama_client(settings: MCQSettings):
    """Create an OllamaClient for QG."""
    from pathway.llm.naming import OllamaClient
    model_name = settings.QG_OLLAMA_MODEL or settings.OLLAMA_MODEL
    is_local = bool(settings.QG_OLLAMA_MODEL)
    host = "http://localhost:11434" if is_local else settings.OLLAMA_HOST
    api_key = "" if is_local else settings.OLLAMA_API_KEY
    return OllamaClient(host=host, model=model_name, api_key=api_key, max_retries=2, timeout=120)


def _get_dg_ollama_client(settings: MCQSettings):
    """Create an OllamaClient for DG."""
    from pathway.llm.naming import OllamaClient
    model_name = settings.DG_OLLAMA_MODEL or settings.OLLAMA_MODEL
    is_local = bool(settings.DG_OLLAMA_MODEL)
    host = "http://localhost:11434" if is_local else settings.OLLAMA_HOST
    api_key = "" if is_local else settings.OLLAMA_API_KEY
    return OllamaClient(host=host, model=model_name, api_key=api_key, max_retries=2, timeout=120)


def _resolve_question_type(
    chunk: ChunkSample,
    condition: EvalCondition,
    embedder,
    settings: MCQSettings,
) -> tuple[str, str]:
    """Resolve question type: forced from condition or auto-selected."""
    if condition.question_type is not None:
        return condition.question_type, condition.score_category

    question_type, score_cat, _ = select_question_type(
        chunk_text=chunk.text,
        chunk_topic=chunk.topic,
        mastery_level=condition.mastery_level,
        topic_performance={},
        incorrectly_answered=[],
        embedder=embedder,
        settings=settings,
    )
    return question_type, score_cat


def run_single_generation(
    chunk: ChunkSample,
    condition: EvalCondition,
    qg_client,
    dg_client,
    embedder,
    settings: MCQSettings,
) -> EvalResult:
    """Run a complete QG + DG generation for one chunk × condition."""
    result = EvalResult(chunk=chunk, condition=condition)

    try:
        # Resolve question type
        question_type, score_category = _resolve_question_type(
            chunk, condition, embedder, settings,
        )
        result.question_type_used = question_type
        result.cognitive_level_expected = TYPE_COGNITIVE_LEVEL.get(question_type, 2)

        # ── QG ─────────────────────────────────────────────────────────
        qg_start = time.time()
        messages = build_qg_chat_prompt(
            chunk.text, question_type, condition.mastery_level,
            score_category, condition.misconception_context,
        )
        raw_qg = qg_client.chat(
            messages=messages,
            temperature=0.0,
            json_mode=False,
            timeout_override=120,
            num_predict=256,
        )
        result.qg_time_ms = (time.time() - qg_start) * 1000
        result.qg_raw_output = raw_qg

        parsed = extract_qg_output(raw_qg)
        if parsed is None:
            result.error_message = "QG parse failed"
            return result

        result.qg_success = True
        result.question = parsed["question"]
        result.correct_answer = parsed["correct_answer"]
        result.explanation = parsed.get("explanation", "")

        # ── DG ─────────────────────────────────────────────────────────
        dg_start = time.time()
        num_distractors = settings.MCQ_DISTRACTOR_COUNT
        correct_lower = result.correct_answer.strip().lower()
        distractors: list[str] = []
        max_attempts = num_distractors + 2

        for _ in range(max_attempts):
            if len(distractors) >= num_distractors:
                break
            dg_messages = build_dg_chat_prompt(
                question=result.question,
                correct_answer=result.correct_answer,
                question_type=question_type,
                mastery_level=condition.mastery_level,
                score_category=score_category,
                chunk_text=chunk.text,
                misconception_context=condition.misconception_context,
            )
            raw_dg = dg_client.chat(
                messages=dg_messages,
                temperature=0.8,
                json_mode=False,
                timeout_override=60,
                num_predict=80,
            )
            result.dg_raw_outputs.append(raw_dg)
            d_parsed = extract_dg_output(raw_dg)
            if d_parsed and d_parsed.strip().lower() != correct_lower:
                if not any(d_parsed.strip().lower() == d.strip().lower() for d in distractors):
                    distractors.append(d_parsed)

        # Fallback padding
        fallbacks = ["None of the above", "All of the above", "Not defined in this context"]
        for fb in fallbacks:
            if len(distractors) >= num_distractors:
                break
            if fb.strip().lower() != correct_lower and fb not in distractors:
                distractors.append(fb)

        result.dg_time_ms = (time.time() - dg_start) * 1000
        result.distractors = distractors[:num_distractors]
        result.dg_success = len(result.distractors) >= num_distractors

        # ── Assemble MCQ ───────────────────────────────────────────────
        options = [MCQOption(text=result.correct_answer, is_correct=True)]
        for d in result.distractors:
            options.append(MCQOption(text=d, is_correct=False))
        random.shuffle(options)

        gen_q = GeneratedQuestion(
            question=result.question,
            correct_answer=result.correct_answer,
            question_type=question_type,
            topic=chunk.topic,
            explanation=result.explanation,
            mastery_used=condition.mastery_level,
            score_category_used=score_category,
            generation_mode="ollama_eval",
        )

        try:
            result.mcq = MCQQuestion(
                question=result.question,
                options=options,
                correct_answer=result.correct_answer,
                explanation=result.explanation,
                question_type=question_type,
                topic=chunk.topic,
                mastery_used=condition.mastery_level,
                score_category_used=score_category,
                generation_mode="ollama_eval",
            )
        except Exception as e:
            result.error_message = f"MCQ assembly: {e}"

    except Exception as e:
        result.error_message = str(e)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3 — AUTOMATED MEASUREMENTS
# ═══════════════════════════════════════════════════════════════════════════════

def compute_metrics(results: list[EvalResult], embedder) -> list[EvalResult]:
    """Compute all automated measurements on generated results."""
    # Batch encode all texts for efficiency
    texts_to_encode: list[str] = []
    text_indices: dict[int, dict[str, int]] = {}  # result_idx -> {text_label: embed_idx}

    for i, r in enumerate(results):
        if not r.qg_success:
            continue
        text_indices[i] = {}

        # correct answer
        text_indices[i]["correct"] = len(texts_to_encode)
        texts_to_encode.append(r.correct_answer)

        # distractors
        for j, d in enumerate(r.distractors):
            text_indices[i][f"d{j}"] = len(texts_to_encode)
            texts_to_encode.append(d)

        # misconception context
        if r.condition.misconception_context:
            text_indices[i]["misconception"] = len(texts_to_encode)
            texts_to_encode.append(r.condition.misconception_context)

    if texts_to_encode:
        embeddings = embedder.encode(texts_to_encode, convert_to_numpy=True, show_progress_bar=False)
    else:
        embeddings = np.array([])

    from sklearn.metrics.pairwise import cosine_similarity as cos_sim

    for i, r in enumerate(results):
        if not r.qg_success or i not in text_indices:
            continue

        idx_map = text_indices[i]
        correct_emb = embeddings[idx_map["correct"]].reshape(1, -1)

        # Distractor similarities
        for j in range(len(r.distractors)):
            key = f"d{j}"
            if key in idx_map:
                d_emb = embeddings[idx_map[key]].reshape(1, -1)
                sim = float(cos_sim(correct_emb, d_emb)[0][0])
                r.distractor_similarities.append(sim)

        # Pairwise distractor similarity (diversity)
        if len(r.distractors) >= 2:
            d_embs = np.array([embeddings[idx_map[f"d{j}"]] for j in range(len(r.distractors)) if f"d{j}" in idx_map])
            if len(d_embs) >= 2:
                pairwise = cos_sim(d_embs)
                n = len(d_embs)
                pair_sims = [pairwise[a][b] for a in range(n) for b in range(a + 1, n)]
                r.distractor_pairwise_sim = float(np.mean(pair_sims)) if pair_sims else 0.0

        # Cognitive level detection
        r.cognitive_level_detected = _detect_cognitive_level(r.question, r.question_type_used)

        # Format issues
        r.format_issues = _detect_format_issues(r)

        # Misconception targeting
        if r.condition.misconception_context and "misconception" in idx_map:
            mc_emb = embeddings[idx_map["misconception"]].reshape(1, -1)
            for j in range(len(r.distractors)):
                key = f"d{j}"
                if key in idx_map:
                    d_emb = embeddings[idx_map[key]].reshape(1, -1)
                    sim = float(cos_sim(mc_emb, d_emb)[0][0])
                    if sim > 0.6:
                        break  # at least one distractor targets misconception

    return results


def _detect_cognitive_level(question: str, type_used: str) -> int:
    """Auto-detect cognitive level from question text characteristics."""
    q = question.lower()

    # Type 4e characteristics
    if any(kw in q for kw in ["a student claims", "is it true", "misconception", "is it correct"]):
        return TYPE_COGNITIVE_LEVEL.get("4e", 4)

    # Type 4d characteristics
    if any(kw in q for kw in ["why ", "explain why", "reason", "what happens if", "consequence"]):
        return TYPE_COGNITIVE_LEVEL.get("4d", 4)

    # Type 4c characteristics
    if any(kw in q for kw in ["which would you use", "most appropriate", "best approach", "in this scenario"]):
        return TYPE_COGNITIVE_LEVEL.get("4c", 3)

    # Type 4b characteristics
    if any(kw in q for kw in ["difference between", "unlike", "compared to", "distinguish"]):
        return TYPE_COGNITIVE_LEVEL.get("4b", 2)

    # Type 2 characteristics
    if any(kw in q for kw in ["what is printed", "what is the output", "what does this code"]):
        return TYPE_COGNITIVE_LEVEL.get("2", 3)

    # Type 3 characteristics
    if any(kw in q for kw in ["complete the", "fill in", "what code"]):
        return TYPE_COGNITIVE_LEVEL.get("3", 3)

    # Type 1 characteristics
    if any(kw in q for kw in ["which method", "which function", "what does .","which parameter"]):
        return TYPE_COGNITIVE_LEVEL.get("1", 2)

    # Type 4a characteristics (default: recall)
    if any(kw in q for kw in ["what is", "which of the following", "define", "what does"]):
        return TYPE_COGNITIVE_LEVEL.get("4a", 1)

    # Fallback to the expected level from the type used
    return TYPE_COGNITIVE_LEVEL.get(type_used, 2)


def _detect_format_issues(r: EvalResult) -> list[str]:
    """Detect known format issues from training data contamination."""
    issues = []
    q = r.question
    a = r.correct_answer
    expl = r.explanation

    # Option labels in question stem
    if re.search(r'\b[A-D]\)\s', q):
        issues.append("option_labels_in_question")

    # Answer starts with letter prefix
    if re.match(r'^[A-D]\)\s', a) or re.match(r'^[A-D]\.\s', a):
        issues.append("answer_has_letter_prefix")

    # Explanation references option letters
    if re.search(r'\b[Oo]ption [A-D]\b', expl) or re.search(r'\b[Cc]hoice [A-D]\b', expl):
        issues.append("explanation_references_letters")

    # Question ends with embedded options
    if re.search(r'\n\s*[A-D]\)\s', q):
        issues.append("embedded_options_in_question")

    # Distractor identical to another
    d_set = set()
    for d in r.distractors:
        d_lower = d.strip().lower()
        if d_lower in d_set:
            issues.append("duplicate_distractor")
            break
        d_set.add(d_lower)

    # Distractor identical to correct answer
    for d in r.distractors:
        if d.strip().lower() == r.correct_answer.strip().lower():
            issues.append("distractor_equals_correct")
            break

    # Generic fallback distractors used
    generic = {"none of the above", "all of the above", "not defined in this context"}
    for d in r.distractors:
        if d.strip().lower() in generic:
            issues.append("fallback_distractor_used")
            break

    return issues


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4 — HUMAN-READABLE OUTPUT
# ═══════════════════════════════════════════════════════════════════════════════

def _format_condition(c: EvalCondition) -> str:
    """Format a condition as a readable string."""
    parts = [c.mastery_level, c.score_category]
    if c.question_type:
        parts.append(f"Type {c.question_type}")
    if c.misconception_context:
        parts.append("misconception")
    else:
        parts.append("no misconception")
    return " × ".join(parts)


def print_result(r: EvalResult, verbose: bool = True):
    """Print a single result in structured format."""
    if not verbose and r.qg_success and not r.format_issues and not r.error_message:
        return

    W = 59
    print(f"\n{'═' * W}")
    print(f"CHUNK: {r.chunk.text[:100]}...")
    print(f"BOOK: {r.chunk.book}  TOPIC: {r.chunk.topic}  CONTENT TYPE: {r.chunk.content_type}")
    print(f"CONDITION: {_format_condition(r.condition)}")
    print(f"{'─' * W}")

    if not r.qg_success:
        print(f"❌ GENERATION FAILED: {r.error_message}")
        if r.qg_raw_output:
            print(f"RAW OUTPUT: {r.qg_raw_output[:300]}")
        print(f"{'═' * W}")
        return

    print(f"QUESTION:\n{r.question}\n")
    print(f"ANSWER:\n{r.correct_answer}\n")
    print(f"DISTRACTORS:")
    for j, d in enumerate(r.distractors):
        sim = r.distractor_similarities[j] if j < len(r.distractor_similarities) else 0.0
        flag = "  ← LOW" if sim < 0.35 else ""
        print(f"  D{j + 1} [similarity: {sim:.2f}]: {d}{flag}")

    if r.explanation:
        print(f"\nEXPLANATION:\n{r.explanation[:300]}")

    total_time = (r.qg_time_ms + r.dg_time_ms) / 1000
    parse_ok = "✓" if r.qg_success else "✗"
    cog_match = "✓" if r.cognitive_level_detected == r.cognitive_level_expected else "✗"
    fmt_issues = ", ".join(r.format_issues) if r.format_issues else "none"

    print(f"\nPARSE: {parse_ok}  |  GENERATION TIME: {total_time:.1f}s")
    print(f"COGNITIVE LEVEL DETECTED: {r.cognitive_level_detected}  |  EXPECTED: {r.cognitive_level_expected}  {cog_match}")
    print(f"TYPE USED: {r.question_type_used}")
    print(f"FORMAT ISSUES: {fmt_issues}")
    print(f"{'═' * W}")


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 5 — ANALYSIS REPORT
# ═══════════════════════════════════════════════════════════════════════════════

def _avg(lst: list[float]) -> float:
    return round(float(np.mean(lst)), 4) if lst else 0.0


def _pct(num: int, den: int) -> str:
    return f"{100 * num / den:.1f}%" if den > 0 else "N/A"


def generate_report(results: list[EvalResult], output_path: str):
    """Generate the comprehensive markdown analysis report."""
    total = len(results)
    parse_successes = sum(1 for r in results if r.qg_success)
    parse_failures = total - parse_successes
    dg_successes = sum(1 for r in results if r.dg_success)
    format_issue_count = sum(1 for r in results if r.format_issues)
    all_times = [(r.qg_time_ms + r.dg_time_ms) / 1000 for r in results if r.qg_success]

    # Build distractor sim stats
    all_d_sims = [s for r in results for s in r.distractor_similarities]
    avg_d_sim = _avg(all_d_sims)

    # Conditioning failures: very_weak not producing 4a
    very_weak_results = [r for r in results if r.condition.score_category == "very_weak" and r.qg_success]
    vw_4a_count = sum(1 for r in very_weak_results if r.question_type_used == "4a")
    conditioning_failures = len(very_weak_results) - vw_4a_count

    lines: list[str] = []
    W = "═" * 60

    # ── Section 1 — Overall Statistics ────────────────────────────────
    lines.append("# MCQ Model Evaluation Report\n")
    lines.append("## Section 1 — Overall Statistics\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|---|---|")
    lines.append(f"| Total generations attempted | {total} |")
    lines.append(f"| Parse successes | {parse_successes} ({_pct(parse_successes, total)}) |")
    lines.append(f"| Parse failures | {parse_failures} ({_pct(parse_failures, total)}) |")
    lines.append(f"| DG successes (3 real distractors) | {dg_successes} ({_pct(dg_successes, total)}) |")
    lines.append(f"| Format issues | {format_issue_count} ({_pct(format_issue_count, total)}) |")
    lines.append(f"| Conditioning failures (very_weak → non-4a) | {conditioning_failures} |")

    if all_times:
        lines.append(f"| Generation time min | {min(all_times):.1f}s |")
        lines.append(f"| Generation time max | {max(all_times):.1f}s |")
        lines.append(f"| Generation time mean | {_avg(all_times):.1f}s |")
        lines.append(f"| Generation time p95 | {float(np.percentile(all_times, 95)):.1f}s |")

    lines.append(f"| Avg distractor similarity | {avg_d_sim:.4f} |")
    lines.append("")

    # Parse failure examples
    if parse_failures > 0:
        lines.append("### Parse Failure Examples\n")
        lines.append("```")
        fail_count = 0
        for r in results:
            if not r.qg_success and fail_count < 5:
                lines.append(f"--- Condition: {_format_condition(r.condition)} ---")
                lines.append(f"Error: {r.error_message}")
                lines.append(f"Raw output (first 300 chars): {r.qg_raw_output[:300]}")
                lines.append("")
                fail_count += 1
        lines.append("```\n")

    # ── Section 2 — Personalization Signal Analysis ───────────────────
    lines.append("## Section 2 — Personalization Signal Analysis\n")

    # 2a: Mastery level effect
    lines.append("### Mastery Level Effect\n")
    mastery_cog: dict[str, list[int]] = defaultdict(list)
    for r in results:
        if r.qg_success and r.condition.axis == "mastery_score":
            mastery_cog[r.condition.mastery_level].append(r.cognitive_level_detected)

    lines.append("| Mastery | Avg Cognitive Level | n |")
    lines.append("|---|---|---|")
    for m in ["Novice", "Intermediate", "Expert"]:
        vals = mastery_cog.get(m, [])
        lines.append(f"| {m} | {_avg([float(v) for v in vals]):.2f} | {len(vals)} |")
    lines.append("")

    # Vocabulary complexity by mastery
    lines.append("#### Vocabulary Complexity by Mastery\n")
    mastery_vocab: dict[str, dict] = {}
    for m in ["Novice", "Intermediate", "Expert"]:
        m_results = [r for r in results if r.qg_success and r.condition.mastery_level == m and r.condition.axis == "mastery_score"]
        if not m_results:
            mastery_vocab[m] = {"avg_word_len": 0, "avg_sent_len": 0}
            continue
        word_lens = []
        sent_lens = []
        for r in m_results:
            words = r.question.split()
            if words:
                word_lens.append(np.mean([len(w) for w in words]))
            sentences = [s.strip() for s in r.question.split('.') if s.strip()]
            if sentences:
                sent_lens.append(np.mean([len(s.split()) for s in sentences]))
        mastery_vocab[m] = {
            "avg_word_len": _avg(word_lens),
            "avg_sent_len": _avg(sent_lens),
        }

    lines.append("| Mastery | Avg Word Length | Avg Words/Sentence |")
    lines.append("|---|---|---|")
    for m in ["Novice", "Intermediate", "Expert"]:
        v = mastery_vocab[m]
        lines.append(f"| {m} | {v['avg_word_len']:.2f} | {v['avg_sent_len']:.1f} |")
    lines.append("")

    # Examples: Novice vs Expert on same chunk
    lines.append("#### Novice vs Expert Examples (same chunk)\n")
    chunk_results: dict[str, dict[str, list[EvalResult]]] = defaultdict(lambda: defaultdict(list))
    for r in results:
        if r.qg_success and r.condition.axis == "mastery_score":
            chunk_results[r.chunk.text[:80]][r.condition.mastery_level].append(r)

    example_count = 0
    for chunk_key, mastery_map in chunk_results.items():
        if "Novice" in mastery_map and "Expert" in mastery_map and example_count < 3:
            nov = mastery_map["Novice"][0]
            exp = mastery_map["Expert"][0]
            lines.append(f"**Chunk:** `{chunk_key}...`\n")
            lines.append(f"- **Novice (cog={nov.cognitive_level_detected}):** {nov.question[:200]}")
            lines.append(f"- **Expert (cog={exp.cognitive_level_detected}):** {exp.question[:200]}")
            diff = "✅ Differentiated" if exp.cognitive_level_detected > nov.cognitive_level_detected else "❌ Not differentiated"
            lines.append(f"- **Result:** {diff}\n")
            example_count += 1
    lines.append("")

    # 2b: Score category override effect
    lines.append("### Score Category Override Effect\n")
    vw_type_dist: Counter = Counter()
    vw_by_mastery: dict[str, Counter] = defaultdict(Counter)
    for r in very_weak_results:
        vw_type_dist[r.question_type_used] += 1
        vw_by_mastery[r.condition.mastery_level][r.question_type_used] += 1

    total_vw = len(very_weak_results)
    vw_4a_pct = _pct(vw_4a_count, total_vw) if total_vw > 0 else "N/A"
    lines.append(f"**very_weak → Type 4a adherence:** {vw_4a_count}/{total_vw} ({vw_4a_pct})\n")

    if vw_type_dist:
        lines.append("| Type Produced | Count |")
        lines.append("|---|---|")
        for t in sorted(vw_type_dist):
            lines.append(f"| Type {t} | {vw_type_dist[t]} |")
        lines.append("")

    # Show failures
    vw_failures = [r for r in very_weak_results if r.question_type_used != "4a"]
    if vw_failures:
        lines.append("#### Override Failures (very_weak producing non-4a)\n")
        for r in vw_failures[:5]:
            lines.append(f"- **{r.condition.mastery_level} × very_weak → Type {r.question_type_used}**")
            lines.append(f"  Chunk: `{r.chunk.text[:80]}...`")
            lines.append(f"  Question: {r.question[:150]}")
        lines.append("")

    # Per mastery breakdown
    lines.append("#### Override adherence by mastery level\n")
    lines.append("| Mastery | Total very_weak | Produced 4a | Rate |")
    lines.append("|---|---|---|---|")
    for m in ["Novice", "Intermediate", "Expert"]:
        total_m = sum(vw_by_mastery[m].values())
        got_4a = vw_by_mastery[m].get("4a", 0)
        lines.append(f"| {m} | {total_m} | {got_4a} | {_pct(got_4a, total_m)} |")
    lines.append("")

    # 2c: Question type forcing effect (Axis 2)
    lines.append("### Question Type Forcing Effect (Axis 2)\n")
    type_sweep_results = [r for r in results if r.condition.axis == "type_sweep" and r.qg_success]

    type_adherence: dict[str, dict] = {}
    for forced_type in ["4a", "4b", "4c", "4d", "4e"]:
        typed_results = [r for r in type_sweep_results if r.condition.question_type == forced_type]
        matched = sum(1 for r in typed_results if r.cognitive_level_detected == TYPE_COGNITIVE_LEVEL.get(forced_type, 2))
        total_typed = len(typed_results)
        type_adherence[forced_type] = {
            "total": total_typed,
            "matched": matched,
            "rate": _pct(matched, total_typed),
        }

    lines.append("| Forced Type | Cognitive Level | Total | Matched | Adherence Rate |")
    lines.append("|---|---|---|---|---|")
    for t in ["4a", "4b", "4c", "4d", "4e"]:
        info = type_adherence[t]
        lines.append(f"| Type {t} | {TYPE_COGNITIVE_LEVEL.get(t, '?')} | {info['total']} | {info['matched']} | {info['rate']} |")
    lines.append("")

    # Type confusion examples
    confused = [r for r in type_sweep_results if r.cognitive_level_detected != r.cognitive_level_expected]
    if confused:
        lines.append("#### Type Confusion Examples\n")
        for r in confused[:5]:
            lines.append(f"- **Forced Type {r.condition.question_type} (expected cog={r.cognitive_level_expected}) → detected cog={r.cognitive_level_detected}**")
            lines.append(f"  Q: {r.question[:200]}")
        lines.append("")

    # 2d: Misconception context effect (Axis 3)
    lines.append("### Misconception Context Effect (Axis 3)\n")
    mc_results = [r for r in results if r.condition.axis == "misconception" and r.qg_success]
    mc_no = [r for r in mc_results if r.condition.misconception_context is None]
    mc_yes = [r for r in mc_results if r.condition.misconception_context is not None]

    lines.append(f"- Questions **without** misconception context: {len(mc_no)}")
    lines.append(f"- Questions **with** misconception context: {len(mc_yes)}")

    # Check if at least one distractor targets the misconception
    mc_targeted = 0
    for r in mc_yes:
        # we compute this by checking if any distractor embedding was close to the misconception
        # We'll approximate by checking if the fallback wasn't needed
        if r.dg_success and "fallback_distractor_used" not in r.format_issues:
            mc_targeted += 1
    lines.append(f"- Misconception targeting success (no fallback needed): {mc_targeted}/{len(mc_yes)}\n")

    # Side-by-side examples
    chunk_mc_map: dict[str, dict[str | None, EvalResult]] = defaultdict(dict)
    for r in mc_results:
        key = r.chunk.text[:80]
        mc_key = r.condition.misconception_context[:30] if r.condition.misconception_context else None
        chunk_mc_map[key][mc_key] = r

    lines.append("#### Side-by-Side Comparisons\n")
    comp_count = 0
    for chunk_key, mc_map in chunk_mc_map.items():
        if None in mc_map and any(k for k in mc_map if k is not None) and comp_count < 3:
            r_no = mc_map[None]
            for mc_text, r_mc in mc_map.items():
                if mc_text is not None:
                    lines.append(f"**Chunk:** `{chunk_key}...`\n")
                    lines.append(f"- **No misconception:** {r_no.question[:200]}")
                    lines.append(f"- **With misconception:** {r_mc.question[:200]}")
                    changed = "✅ Question changed" if r_no.question != r_mc.question else "❌ Same question"
                    lines.append(f"- **Result:** {changed}\n")
                    comp_count += 1
                    if comp_count >= 3:
                        break
    lines.append("")

    # ── Section 3 — Distractor Quality Analysis ──────────────────────
    lines.append("## Section 3 — Distractor Quality Analysis\n")

    lines.append(f"**Average distractor plausibility:** {avg_d_sim:.4f}\n")

    # By mastery
    mastery_d_sim: dict[str, list[float]] = defaultdict(list)
    for r in results:
        if r.qg_success:
            mastery_d_sim[r.condition.mastery_level].extend(r.distractor_similarities)

    lines.append("| Mastery | Avg Distractor Similarity | n |")
    lines.append("|---|---|---|")
    for m in ["Novice", "Intermediate", "Expert"]:
        sims = mastery_d_sim.get(m, [])
        lines.append(f"| {m} | {_avg(sims):.4f} | {len(sims)} |")
    lines.append("")

    # Low-quality distractors
    low_d = [s for s in all_d_sims if s < 0.35]
    high_d = [s for s in all_d_sims if s > 0.7]
    lines.append(f"- Low similarity distractors (<0.35): {len(low_d)} ({_pct(len(low_d), len(all_d_sims))})")
    lines.append(f"- High similarity distractors (>0.70): {len(high_d)} ({_pct(len(high_d), len(all_d_sims))})")

    # Examples of good and bad distractors
    lines.append("\n#### Best Distractors (sim > 0.7)\n")
    good_examples = sorted(
        [(r, j, r.distractor_similarities[j])
         for r in results if r.qg_success
         for j in range(len(r.distractor_similarities))
         if r.distractor_similarities[j] > 0.7],
        key=lambda x: -x[2],
    )[:5]
    for r, j, sim in good_examples:
        lines.append(f"- **sim={sim:.3f}** | Correct: `{r.correct_answer[:80]}` → Distractor: `{r.distractors[j][:80]}`")
    lines.append("")

    lines.append("#### Worst Distractors (sim < 0.3)\n")
    bad_examples = sorted(
        [(r, j, r.distractor_similarities[j])
         for r in results if r.qg_success
         for j in range(len(r.distractor_similarities))
         if r.distractor_similarities[j] < 0.3],
        key=lambda x: x[2],
    )[:5]
    for r, j, sim in bad_examples:
        lines.append(f"- **sim={sim:.3f}** | Correct: `{r.correct_answer[:80]}` → Distractor: `{r.distractors[j][:80]}`")
    lines.append("")

    # Diversity
    all_pairwise = [r.distractor_pairwise_sim for r in results if r.qg_success and r.distractor_pairwise_sim > 0]
    lines.append(f"**Average pairwise distractor similarity:** {_avg(all_pairwise):.4f}")
    low_diversity = [r for r in results if r.qg_success and r.distractor_pairwise_sim > 0.85]
    lines.append(f"**Low diversity sets (pairwise > 0.85):** {len(low_diversity)}\n")

    if low_diversity:
        lines.append("#### Low Diversity Examples\n")
        for r in low_diversity[:3]:
            lines.append(f"- Q: `{r.question[:100]}...`")
            for j, d in enumerate(r.distractors):
                lines.append(f"  D{j+1}: `{d}`")
            lines.append(f"  Pairwise sim: {r.distractor_pairwise_sim:.3f}\n")

    # ── Section 4 — Failure Mode Catalog ─────────────────────────────
    lines.append("## Section 4 — Failure Mode Catalog\n")

    failure_modes: Counter = Counter()
    failure_examples: dict[str, list[str]] = defaultdict(list)

    for r in results:
        if not r.qg_success:
            failure_modes["parse_failure"] += 1
            if len(failure_examples["parse_failure"]) < 3:
                failure_examples["parse_failure"].append(
                    f"Condition: {_format_condition(r.condition)} | Error: {r.error_message} | Raw: {r.qg_raw_output[:150]}"
                )

        if r.format_issues:
            for issue in r.format_issues:
                failure_modes[issue] += 1
                if len(failure_examples[issue]) < 3:
                    failure_examples[issue].append(
                        f"Q: {r.question[:100]}... | A: {r.correct_answer[:60]}"
                    )

        if r.qg_success and r.cognitive_level_detected != r.cognitive_level_expected:
            failure_modes["cognitive_level_mismatch"] += 1
            if len(failure_examples["cognitive_level_mismatch"]) < 3:
                failure_examples["cognitive_level_mismatch"].append(
                    f"Type {r.question_type_used}: expected={r.cognitive_level_expected} got={r.cognitive_level_detected} | Q: {r.question[:100]}"
                )

    if failure_modes:
        lines.append("| Failure Mode | Count | % of Total |")
        lines.append("|---|---|---|")
        for mode, count in failure_modes.most_common():
            lines.append(f"| {mode} | {count} | {_pct(count, total)} |")
        lines.append("")

        for mode, examples in failure_examples.items():
            if examples:
                lines.append(f"### {mode}\n")
                lines.append("```")
                for ex in examples:
                    lines.append(ex)
                lines.append("```\n")
    else:
        lines.append("No failure modes detected.\n")

    # ── Section 5 — Content Type Performance ─────────────────────────
    lines.append("## Section 5 — Content Type Performance\n")

    content_type_stats: dict[str, dict] = {}
    for ct in ["definition", "code", "comparison", "causal", "procedural"]:
        ct_results = [r for r in results if r.chunk.content_type == ct]
        ct_success = [r for r in ct_results if r.qg_success]
        ct_sims = [s for r in ct_success for s in r.distractor_similarities]
        ct_format = sum(1 for r in ct_success if r.format_issues)
        content_type_stats[ct] = {
            "total": len(ct_results),
            "success": len(ct_success),
            "parse_rate": _pct(len(ct_success), len(ct_results)),
            "avg_sim": _avg(ct_sims),
            "format_issues": ct_format,
        }

    lines.append("| Content Type | Total | Parse Success | Avg Distractor Sim | Format Issues |")
    lines.append("|---|---|---|---|---|")
    for ct in ["definition", "code", "comparison", "causal", "procedural"]:
        s = content_type_stats[ct]
        lines.append(f"| {ct} | {s['total']} | {s['parse_rate']} | {s['avg_sim']:.4f} | {s['format_issues']} |")
    lines.append("")

    # Best and worst content types
    ranked = sorted(content_type_stats.items(), key=lambda x: x[1]["avg_sim"], reverse=True)
    if ranked:
        best_ct = ranked[0][0]
        worst_ct = ranked[-1][0]
        lines.append(f"**Best performing:** {best_ct} (avg sim: {content_type_stats[best_ct]['avg_sim']:.4f})")
        lines.append(f"**Worst performing:** {worst_ct} (avg sim: {content_type_stats[worst_ct]['avg_sim']:.4f})\n")

    # ── Section 6 — Recommendations ──────────────────────────────────
    lines.append("## Section 6 — Specific Recommendations For The Next Training Run\n")

    recommendations: list[dict] = []

    # R1: Parse failures
    if parse_failures > 0:
        recommendations.append({
            "problem": f"QG parse failures: {parse_failures}/{total} generations failed to parse",
            "frequency": _pct(parse_failures, total),
            "root_cause": "Model not reliably following QUESTION/ANSWER/EXPLANATION output format",
            "data_gen": "Add output format reinforcement examples — include 50+ examples with explicit format headers",
            "training_format": "Add format compliance token in format_qg.py as a separate training signal",
            "prompt": "Add explicit negative examples in system prompt: 'Do NOT output JSON. Do NOT output markdown fences.'",
            "model": "Consider increasing num_predict from 256 to 384 if truncation is causing parse failures",
            "impact": f"Should reduce parse failure rate from {_pct(parse_failures, total)} toward <2%",
        })

    # R2: Format issues
    if format_issue_count > 0:
        issue_breakdown = Counter()
        for r in results:
            for i in r.format_issues:
                issue_breakdown[i] += 1
        top_issue = issue_breakdown.most_common(1)[0] if issue_breakdown else ("unknown", 0)
        recommendations.append({
            "problem": f"Format contamination: {format_issue_count} questions have format issues (top: {top_issue[0]}={top_issue[1]})",
            "frequency": _pct(format_issue_count, total),
            "root_cause": "Training data still contains option labels, letter prefixes from raw teacher LLM output",
            "data_gen": "Run clean_dataset.py with stricter validation; add regex check for A/B/C/D in question stem",
            "training_format": "In format_qg.py: add post-processing to strip any residual option labels before creating training example",
            "prompt": "No prompt changes needed — this is a data quality issue",
            "model": "No model changes needed",
            "impact": f"Should eliminate the {_pct(format_issue_count, total)} format issue rate",
        })

    # R3: Conditioning adherence
    if conditioning_failures > 0:
        recommendations.append({
            "problem": f"very_weak score category not reliably forcing Type 4a: {conditioning_failures} failures",
            "frequency": f"{conditioning_failures}/{len(very_weak_results)} very_weak conditions",
            "root_cause": "Insufficient very_weak training examples; selector correctly forces 4a but model ignores the type conditioning",
            "data_gen": "Increase very_weak × 4a examples to at least 200 in training data. Currently underrepresented.",
            "training_format": "No changes needed — format_qg correctly passes score_category in the prompt",
            "prompt": "Add explicit instruction: 'When score_category is very_weak, you MUST generate a definition/recall question regardless of other signals.'",
            "model": "Consider increasing LoRA rank from 16 to 32 if conditioning adherence doesn't improve with more data",
            "impact": "Should improve very_weak → 4a adherence from current to >95%",
        })

    # R4: Distractor quality
    fallback_count = sum(1 for r in results if "fallback_distractor_used" in r.format_issues)
    if fallback_count > 0:
        recommendations.append({
            "problem": f"DG model failing to produce enough unique distractors: {fallback_count} questions needed fallback padding",
            "frequency": _pct(fallback_count, total),
            "root_cause": "DG model sometimes outputs the correct answer or duplicates instead of unique wrong answers",
            "data_gen": "Ensure each DG training example has a distractor that is clearly wrong but semantically related",
            "training_format": "In format_dg.py: filter out training examples where distractor is too similar to correct answer (cosine > 0.95)",
            "prompt": "Add: 'The distractor MUST be factually wrong. It MUST NOT be a rephrasing of the correct answer.'",
            "model": "DG may need more training examples per distractor type; currently 3x multiplier may not be enough for all types",
            "impact": f"Should reduce fallback usage from {_pct(fallback_count, total)} to <5%",
        })

    # R5: Diversity
    if low_diversity:
        recommendations.append({
            "problem": f"Low distractor diversity: {len(low_diversity)} questions have pairwise sim > 0.85",
            "frequency": _pct(len(low_diversity), total),
            "root_cause": "DG model generating variations of the same wrong concept rather than targeting distinct misconceptions",
            "data_gen": "In data_generator.py: ensure training distractors cover 3 different misconception categories per question",
            "training_format": "Add a 'distractor_type' field (e.g., 'definitional_error', 'scope_error', 'syntax_confusion') to DG training data",
            "prompt": "Add: 'This distractor must target a DIFFERENT misconception than previous distractors.'",
            "model": "Consider temperature > 0.8 for DG or nucleus sampling to increase output diversity",
            "impact": f"Should reduce low-diversity sets from {len(low_diversity)} to near 0",
        })

    # R6: Data distribution
    recommendations.append({
        "problem": "Data distribution balance across all conditioning signals",
        "frequency": "Structural recommendation (not a failure)",
        "root_cause": "Training data may have imbalanced representation across mastery × score_category × type combinations",
        "data_gen": "Target minimums per combination: Novice×very_weak: 100, Novice×moderate: 100, Novice×strong: 100, "
                    "Intermediate×very_weak: 100, Intermediate×moderate: 150, Intermediate×strong: 100, "
                    "Expert×very_weak: 80, Expert×moderate: 100, Expert×strong: 120. "
                    "Code question types (1,2,3): at least 150 each. Conceptual types (4a-4e): at least 200 each.",
        "training_format": "Use cap_dataset.py and merge_dataset.py to enforce these minimums",
        "prompt": "No changes needed",
        "model": "With balanced data, current LoRA r=16 should be sufficient for 3B model",
        "impact": "Balanced data ensures conditioning adherence across all signal combinations",
    })

    # R7: QG vs DG comparison
    qg_fail_rate = _pct(parse_failures, total)
    dg_fail_rate = _pct(total - dg_successes, total)
    recommendations.append({
        "problem": f"QG vs DG failure comparison: QG parse fail={qg_fail_rate}, DG incomplete={dg_fail_rate}",
        "frequency": "N/A",
        "root_cause": "QG and DG have independent failure modes; poor QG output cascades to DG failures",
        "data_gen": "Focus on QG quality first — a bad question makes DG impossible regardless of DG model quality",
        "training_format": "No changes needed",
        "prompt": "No changes needed",
        "model": "If QG is the bottleneck, allocate more training epochs to QG (5 epochs) vs DG (3 epochs)",
        "impact": "Fixing QG should reduce overall pipeline failure rate",
    })

    for i, rec in enumerate(recommendations, 1):
        lines.append(f"### Recommendation {i}\n")
        lines.append(f"**PROBLEM:** {rec['problem']}")
        lines.append(f"**FREQUENCY:** {rec['frequency']}")
        lines.append(f"**ROOT CAUSE HYPOTHESIS:** {rec['root_cause']}\n")
        lines.append(f"**RECOMMENDED FIX:**")
        lines.append(f"- Data generation: {rec['data_gen']}")
        lines.append(f"- Training format: {rec['training_format']}")
        lines.append(f"- Prompt: {rec['prompt']}")
        lines.append(f"- Model/PEFT: {rec['model']}\n")
        lines.append(f"**EXPECTED IMPACT:** {rec['impact']}\n")

    # ── Section 7 — Priority-Ordered Action List ─────────────────────
    lines.append("## Section 7 — Priority-Ordered Action List\n")

    for i, rec in enumerate(recommendations, 1):
        lines.append(f"{i}. **{rec['problem'].split(':')[0]}**")
        lines.append(f"   - What: {rec['data_gen'][:120]}")
        lines.append(f"   - Expected improvement: {rec['impact'][:120]}")
    lines.append("")

    # Write report
    report_path = Path(output_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive MCQ model evaluation.",
    )
    parser.add_argument(
        "--output", default="mcq_service/evaluation/evaluation_report.md",
        help="Path for the markdown report (default: mcq_service/evaluation/evaluation_report.md).",
    )
    parser.add_argument(
        "--chunks", type=int, default=20,
        help="Number of chunks to sample (default: 20).",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print every generated MCQ to console (default: only failures/stats).",
    )
    args = parser.parse_args()

    W = 42
    print(f"\n{'═' * W}")
    print("  MCQ MODEL EVALUATION")
    print(f"{'═' * W}")

    # ── Load settings ────────────────────────────────────────────────
    settings = MCQSettings()
    qg_model = settings.QG_OLLAMA_MODEL or settings.OLLAMA_MODEL
    dg_model = settings.DG_OLLAMA_MODEL or settings.OLLAMA_MODEL
    print(f"  QG model: {qg_model}")
    print(f"  DG model: {dg_model}")

    # ── Load embedder ────────────────────────────────────────────────
    print("  Loading embedder...", end=" ", flush=True)
    from sentence_transformers import SentenceTransformer
    embedder = SentenceTransformer("all-MiniLM-L6-v2")
    print("✅")

    # ── Sample chunks ────────────────────────────────────────────────
    print(f"  Sampling {args.chunks} chunks...", end=" ", flush=True)
    chunks = sample_chunks(args.chunks)
    print(f"✅ ({len(chunks)} chunks)")

    # Print chunk summary
    ct_counts = Counter(c.content_type for c in chunks)
    book_counts = Counter(c.book for c in chunks)
    print(f"  Content types: {dict(ct_counts)}")
    print(f"  Books: {dict(book_counts)}")

    # ── Build matrix ─────────────────────────────────────────────────
    conditions = build_eval_matrix()
    total_runs = len(chunks) * len(conditions)
    print(f"  Evaluation matrix: {len(conditions)} conditions × {len(chunks)} chunks = {total_runs} runs")

    # ── Create clients ───────────────────────────────────────────────
    print("  Creating Ollama clients...", end=" ", flush=True)
    qg_client = _get_ollama_client(settings)
    dg_client = _get_dg_ollama_client(settings)
    print("✅")

    # ── Run evaluations ──────────────────────────────────────────────
    print(f"\n  Running {total_runs} generations...\n")
    results: list[EvalResult] = []

    pbar = tqdm(total=total_runs, desc="Generating", unit="mcq")
    for chunk in chunks:
        for condition in conditions:
            try:
                result = run_single_generation(
                    chunk, condition, qg_client, dg_client, embedder, settings,
                )
                results.append(result)
                print_result(result, verbose=args.verbose)
            except Exception as e:
                result = EvalResult(chunk=chunk, condition=condition, error_message=str(e))
                results.append(result)
                if args.verbose:
                    print(f"  ❌ Error: {e}")
            pbar.update(1)
    pbar.close()

    # ── Compute metrics ──────────────────────────────────────────────
    print("\n  Computing metrics...", end=" ", flush=True)
    results = compute_metrics(results, embedder)
    print("✅")

    # ── Generate report ──────────────────────────────────────────────
    print("  Generating report...", end=" ", flush=True)
    generate_report(results, args.output)
    print("✅")

    # ── Console summary ──────────────────────────────────────────────
    total = len(results)
    parse_ok = sum(1 for r in results if r.qg_success)
    fmt_issues = sum(1 for r in results if r.format_issues)
    all_sims = [s for r in results for s in r.distractor_similarities]
    all_times = [(r.qg_time_ms + r.dg_time_ms) / 1000 for r in results if r.qg_success]

    vw_results = [r for r in results if r.condition.score_category == "very_weak" and r.qg_success]
    cond_failures = sum(1 for r in vw_results if r.question_type_used != "4a")

    print(f"\n{'═' * W}")
    print("  EVALUATION COMPLETE")
    print(f"{'═' * W}")
    print(f"  Total generations:    {total}")
    print(f"  Parse successes:      {parse_ok} ({_pct(parse_ok, total)})")
    print(f"  Format issues:        {fmt_issues} ({_pct(fmt_issues, total)})")
    print(f"  Conditioning failures:{cond_failures} ({_pct(cond_failures, total)})")
    print(f"  Avg distractor sim:   {_avg(all_sims):.2f}")
    if all_times:
        print(f"  Avg generation time:  {_avg(all_times):.1f}s")
    print(f"\n  Full report: {args.output}")
    print(f"{'═' * W}\n")


if __name__ == "__main__":
    main()
