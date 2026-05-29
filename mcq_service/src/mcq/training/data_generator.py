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
import random
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

CONFIG = {
    "api_keys": [
        os.getenv("OLLAMA_API_KEY_1"),
        os.getenv("OLLAMA_API_KEY_2"),
        os.getenv("OLLAMA_API_KEY_3"),
        os.getenv("OLLAMA_API_KEY_4"),
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


def _load_chunks_from_pdfs(books_dir: str, chunk_size: int, chunk_overlap: int) -> list[dict]:
    """Load and chunk all PDFs from the books directory."""
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
    pdf_files = list(books_path.glob("*.pdf"))
    logger.info("found_pdf_files", count=len(pdf_files), dir=books_dir)

    for pdf_path in pdf_files:
        try:
            loader = PyPDFLoader(str(pdf_path))
            pages = loader.load()
            splits = splitter.split_documents(pages)
            for doc in splits:
                text = doc.page_content.strip()
                if len(text) < 50:
                    continue
                topic = doc.metadata.get("topic", pdf_path.stem)
                all_chunks.append({
                    "text": text,
                    "topic": topic,
                    "book": pdf_path.name,
                })
        except Exception:
            logger.exception("pdf_load_failed", path=str(pdf_path))

    logger.info("total_chunks_loaded", count=len(all_chunks))
    return all_chunks


def _build_tasks(
    chunks: list[dict],
    existing_hashes: set[str],
) -> list[dict]:
    """Build generation tasks from chunks with weighted sampling.

    For each chunk, samples one (mastery, score_category) pair and uses the
    selector to determine the question type.  20% of examples get a
    misconception_context populated.
    """
    # Lazy import — selector is read-only, we only call it
    mcq_src = str(Path(__file__).resolve().parent.parent.parent)
    if mcq_src not in sys.path:
        sys.path.insert(0, mcq_src)

    from mcq.question_types import MASTERY_TYPE_ELIGIBILITY, TYPE_COGNITIVE_LEVEL

    tasks: list[dict] = []

    for chunk in chunks:
        text = chunk["text"]
        ch = _chunk_hash(text)

        if ch in existing_hashes:
            continue

        mastery = _weighted_sample(MASTERY_WEIGHTS)
        score_category = _weighted_sample(SCORE_CATEGORY_WEIGHTS)

        # Pick question type from mastery eligibility
        eligible = MASTERY_TYPE_ELIGIBILITY.get(mastery, ["4a"])
        question_type = random.choice(eligible)

        # 20% chance: generate with misconception context
        misconception_context = None
        if random.random() < 0.20:
            # Simulate a failed question — escalate one level
            original_type = question_type
            question_type = _ESCALATION_MAP.get(question_type, question_type)
            misconception_context = (
                f"student chose a wrong answer for a Type {original_type} "
                f"question on this topic"
            )

        tasks.append({
            "text": text,
            "topic": chunk.get("topic", "General"),
            "book": chunk.get("book", "unknown"),
            "chunk_hash": ch,
            "mastery": mastery,
            "score_category": score_category,
            "question_type": question_type,
            "misconception_context": misconception_context,
        })

    random.shuffle(tasks)
    logger.info("tasks_built", total=len(tasks), skipped_existing=len(chunks) - len(tasks))
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
    api_key: str,
    task_queue: queue.Queue,
    output_path: str,
    file_lock: threading.Lock,
    stats: WorkerStats,
    progress_counter: list,
    progress_lock: threading.Lock,
):
    """Worker thread: pulls tasks, calls Ollama, writes results."""
    client = _make_ollama_client(api_key)

    while True:
        try:
            task = task_queue.get(timeout=5)
        except queue.Empty:
            break

        prompt = _build_generation_prompt(task)
        result = None

        for attempt in range(1, CONFIG["max_retries"] + 1):
            try:
                data = client.chat_json(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    timeout_override=180,
                )

                if not isinstance(data, dict):
                    continue

                # Validate required fields
                if not all(k in data for k in ("question", "correct_answer", "distractors")):
                    logger.warning(
                        "worker_missing_keys",
                        worker=worker_id,
                        keys=list(data.keys()),
                        chunk_hash=task["chunk_hash"],
                    )
                    continue

                distractors = data.get("distractors", [])
                if not isinstance(distractors, list) or len(distractors) != 3:
                    logger.warning(
                        "worker_bad_distractors",
                        worker=worker_id,
                        count=len(distractors) if isinstance(distractors, list) else 0,
                    )
                    continue

                # Validate: no distractor matches correct answer
                correct_lower = str(data["correct_answer"]).strip().lower()
                distractor_strs = [str(d).strip() for d in distractors]
                if any(d.lower() == correct_lower for d in distractor_strs):
                    continue

                # Validate: no duplicate distractors
                if len(set(d.lower() for d in distractor_strs)) < 3:
                    continue

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
                }
                break

            except Exception as exc:
                logger.warning(
                    "worker_attempt_failed",
                    worker=worker_id,
                    attempt=attempt,
                    chunk_hash=task["chunk_hash"],
                    error=str(exc)[:100],
                )
                if attempt < CONFIG["max_retries"]:
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

        with progress_lock:
            progress_counter[0] += 1

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
):
    """Print final generation report."""
    total_success = sum(s.success for s in all_stats)
    total_failure = sum(s.failure for s in all_stats)

    # Count output lines and distributions
    type_dist: Counter = Counter()
    mastery_dist: Counter = Counter()
    category_dist: Counter = Counter()
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
                except json.JSONDecodeError:
                    pass

    print("\n" + "=" * 60)
    print("MCQ TRAINING DATA GENERATION — FINAL REPORT")
    print("=" * 60)
    print(f"  Total chunks queued:      {total_tasks}")
    print(f"  Successful generations:   {total_success}")
    print(f"  Failures:                 {total_failure}")
    print()
    print("  Per-worker success counts:")
    for i, s in enumerate(all_stats):
        print(f"    Worker {i}: {s.success} success, {s.failure} failure")
    print()
    print("  Question type distribution:")
    for t, c in sorted(type_dist.items()):
        print(f"    Type {t}: {c}")
    print()
    print("  Mastery level distribution:")
    for m, c in sorted(mastery_dist.items()):
        print(f"    {m}: {c}")
    print()
    print("  Score category distribution:")
    for cat, c in sorted(category_dist.items()):
        print(f"    {cat}: {c}")
    print()
    print(f"  Output file line count:   {line_count}")
    print(f"  Output file:              {output_path}")
    print("=" * 60 + "\n")


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
    args = parser.parse_args()

    # Filter API keys — only use non-None keys
    valid_keys = [k for k in CONFIG["api_keys"] if k]
    if not valid_keys:
        print("ERROR: No valid API keys found in OLLAMA_API_KEY_1..4 env vars.")
        sys.exit(1)

    num_workers = min(args.workers, len(valid_keys))
    logger.info(
        "data_generator_starting",
        workers=num_workers,
        available_keys=len(valid_keys),
        books_dir=args.books,
    )

    # Ensure output directory exists
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)

    # Load chunks
    chunks = _load_chunks_from_pdfs(args.books, args.chunk_size, args.chunk_overlap)
    if not chunks:
        print("ERROR: No chunks loaded from books directory.")
        sys.exit(1)

    # Resumability: skip already-processed chunks
    existing_hashes = _load_existing_hashes(args.output)
    tasks = _build_tasks(chunks, existing_hashes)

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
    progress_counter = [0]
    progress_lock = threading.Lock()
    all_stats: list[WorkerStats] = []

    # Start workers
    threads: list[threading.Thread] = []
    for i in range(num_workers):
        stats = WorkerStats()
        all_stats.append(stats)
        t = threading.Thread(
            target=_worker,
            args=(
                i, valid_keys[i], task_queue, args.output,
                file_lock, stats, progress_counter, progress_lock,
            ),
            daemon=True,
        )
        t.start()
        threads.append(t)

    # Progress monitor
    try:
        while any(t.is_alive() for t in threads):
            with progress_lock:
                done = progress_counter[0]
            success_total = sum(s.success for s in all_stats)
            failure_total = sum(s.failure for s in all_stats)
            print(
                f"\r  Progress: {done}/{total_tasks} | "
                f"Success: {success_total} | Failures: {failure_total}",
                end="", flush=True,
            )
            time.sleep(2)
    except KeyboardInterrupt:
        print("\n\nInterrupted — partial results saved. Run again to resume.")
        return

    # Wait for all threads
    for t in threads:
        t.join()

    print()  # newline after progress
    _print_report(all_stats, args.output, total_tasks)


if __name__ == "__main__":
    main()
