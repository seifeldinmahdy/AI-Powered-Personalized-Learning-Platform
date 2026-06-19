#!/usr/bin/env python3
"""
Generate classifier training data from SYNTHETIC chunks (MCQ-style).

Mirrors the MCQ synthetic-chunk approach: instead of harvesting raw PDF
passages, we reuse the clean, reference-free CS paragraphs already generated
for the MCQ pipeline (mcq_synthetic_chunks_cache.jsonl) and run each one
through the visual-template classifier LLM to produce a {text, label} pair.

Why a dedicated script (vs. ClassifierDataGenerator.run_from_chunks):
    run_from_chunks() filters chunks with is_valid_chunk(), which rejects any
    chunk shorter than 3 lines. The MCQ synthetic chunks are single-paragraph
    prose (one line each, ~800 chars), so they would ALL be dropped as
    "too_few_lines". They are already clean and validated, so we call
    classify_one() directly and skip that PDF-oriented filter.

Features:
- Parallel classification (ThreadPoolExecutor) — Ollama Cloud handles concurrency
- Checkpoint/resume by chunk-hash (re-running only labels what's missing)
- Writes to a STAGING file by default; merge into the main training file with
  --merge-into (deduplicates by text before appending).

Usage:
    # 1. Label all synthetic chunks into a staging file
    python scripts/generate_classifier_data_from_synthetic.py

    # 2. Inspect the staging file, then append into the main training file
    python scripts/generate_classifier_data_from_synthetic.py \
        --merge-into data/agent_training/classifier_train_regenerated_cleaned.jsonl
"""

import argparse
import hashlib
import json
import os
import queue as _queue
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from slide_gen.training.classifier_data_generator import ClassifierDataGenerator  # noqa: E402
from slide_gen.data_engine.key_pool import load_ollama_keys, describe_key_sources  # noqa: E402

# Default source: the MCQ synthetic chunk cache (sibling service)
DEFAULT_SYNTHETIC = (
    project_root.parent
    / "mcq_service" / "data" / "mcq_training" / "mcq_synthetic_chunks_cache.jsonl"
)


def _text_hash(text: str) -> str:
    return hashlib.md5(text.strip().encode("utf-8")).hexdigest()[:12]


def load_synthetic_chunks(path: Path) -> list[dict]:
    """Load {text, topic, book} entries from a synthetic-chunk JSONL cache."""
    chunks = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = (entry.get("text") or "").strip()
            if text:
                chunks.append(entry)
    return chunks


def load_done_hashes(output_path: Path) -> set[str]:
    """Read already-labeled texts so a re-run only fills the gaps."""
    done = set()
    if output_path.exists():
        with open(output_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("text"):
                    done.add(_text_hash(rec["text"]))
    return done


def load_existing_texts(path: Path) -> set[str]:
    """Hashes of all texts already present in a training file (for dedup on merge)."""
    seen = set()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("text"):
                    seen.add(_text_hash(rec["text"]))
    return seen


def merge_into(staging_path: Path, target_path: Path) -> None:
    """Append staging {text,label} records into the main training file (dedup by text)."""
    existing = load_existing_texts(target_path)
    to_add = []
    with open(staging_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            h = _text_hash(rec["text"])
            if h not in existing:
                existing.add(h)
                to_add.append(rec)

    before = sum(1 for _ in open(target_path)) if target_path.exists() else 0
    with open(target_path, "a", encoding="utf-8") as f:
        for rec in to_add:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    after = before + len(to_add)
    print(f"\n{'=' * 60}")
    print(f"MERGE COMPLETE")
    print(f"  Target:        {target_path}")
    print(f"  Before:        {before} examples")
    print(f"  Added:         {len(to_add)} (new, deduplicated)")
    print(f"  After:         {after} examples")
    print(f"{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(
        description="Label synthetic chunks into classifier training data"
    )
    parser.add_argument(
        "--synthetic-path", type=str, default=str(DEFAULT_SYNTHETIC),
        help="Path to synthetic-chunk JSONL (MCQ cache format: {text, topic, book})",
    )
    parser.add_argument(
        "--output", type=str,
        default="classifier_train_synthetic.jsonl",
        help="Staging output filename (joined to --output-dir)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="data/agent_training",
        help="Directory for the staging file (default: data/agent_training)",
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help="Parallel workers (default: one per available API key)",
    )
    parser.add_argument(
        "--max-keys", type=int, default=None,
        help="Cap the number of API keys used from the pool",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Only process the first N chunks (for testing)",
    )
    parser.add_argument(
        "--merge-into", type=str, default=None,
        help="If set, ONLY merge the staging file into this training file "
             "(deduplicated by text) and exit — no LLM calls.",
    )
    args = parser.parse_args()

    load_dotenv(project_root / ".env")

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = project_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / args.output

    # ── Merge-only mode ───────────────────────────────────────────────────
    if args.merge_into:
        target = Path(args.merge_into)
        if not target.is_absolute():
            target = project_root / target
        if not output_path.exists():
            print(f"❌ Staging file not found: {output_path}")
            print("   Run labeling first (without --merge-into).")
            sys.exit(1)
        merge_into(output_path, target)
        return

    # ── Labeling mode ─────────────────────────────────────────────────────
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
    max_retries = int(os.getenv("MAX_RETRIES", "3"))
    prompts_path = project_root / "config" / "prompts_classifier.yaml"

    # Multi-key fleet (mcq_service/.env first), one worker pinned per key.
    api_keys = load_ollama_keys(max_keys=args.max_keys)
    if not api_keys:
        api_keys = [None]  # fall back to unauthenticated/local
    n_workers = args.workers if args.workers else len(api_keys)

    synthetic_path = Path(args.synthetic_path)
    if not synthetic_path.exists():
        print(f"❌ Synthetic chunk file not found: {synthetic_path}")
        sys.exit(1)

    chunks = load_synthetic_chunks(synthetic_path)
    if args.limit:
        chunks = chunks[: args.limit]

    done = load_done_hashes(output_path)
    pending = [c for c in chunks if _text_hash(c["text"]) not in done]

    print("=" * 70)
    print("CLASSIFIER DATA FROM SYNTHETIC CHUNKS")
    print("=" * 70)
    print(f"Source:        {synthetic_path}")
    print(f"Ollama:        {ollama_host} / {ollama_model}")
    print(f"Key sources:   {describe_key_sources()}")
    print(f"API keys:      {len(api_keys)} ({'cloud' if api_keys[0] else 'local'})")
    print(f"Total chunks:  {len(chunks)}")
    print(f"Already done:  {len(done)}")
    print(f"To label:      {len(pending)}")
    print(f"Workers:       {n_workers} (one pinned per key)")
    print(f"Staging file:  {output_path}\n")

    if not pending:
        print("✅ Nothing to do — all chunks already labeled.")
        print(f"   Merge with: --merge-into <training_file>")
        return

    # One generator per worker, each pinned to a distinct API key (round-robin
    # if workers > keys). Mirrors the MCQ pipeline's one-thread-per-key model.
    generators = [
        ClassifierDataGenerator(
            prompts_path=prompts_path,
            output_dir=output_dir,
            ollama_host=ollama_host,
            model=ollama_model,
            max_retries=max_retries,
            api_key=api_keys[i % len(api_keys)],
        )
        for i in range(n_workers)
    ]

    write_lock = threading.Lock()
    label_dist = Counter()
    stats = {"ok": 0, "fail": 0}

    out_fh = open(output_path, "a", encoding="utf-8")

    # Shared task queue — every worker drains it, staying pinned to its own key.
    task_q: _queue.Queue = _queue.Queue()
    for chunk in pending:
        task_q.put(chunk)

    pbar = tqdm(total=len(pending), desc="Labeling", unit="chunk")

    def worker(worker_idx: int):
        gen = generators[worker_idx]
        while True:
            try:
                chunk = task_q.get_nowait()
            except _queue.Empty:
                return
            try:
                title = str(chunk.get("topic", "")).replace("_", " ").title()
                result = gen.classify_one(chunk["text"], title)
            except Exception as e:  # noqa: BLE001
                result = None
                tqdm.write(f"  ⚠️  worker {worker_idx} error: {str(e)[:120]}")
            with write_lock:
                if result:
                    out_fh.write(json.dumps(result, ensure_ascii=False) + "\n")
                    out_fh.flush()
                    label_dist[result["label"]] += 1
                    stats["ok"] += 1
                else:
                    stats["fail"] += 1
                pbar.set_postfix(ok=stats["ok"], fail=stats["fail"])
                pbar.update(1)

    try:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = [pool.submit(worker, i) for i in range(n_workers)]
            for fut in futures:
                exc = fut.exception()
                if exc:
                    tqdm.write(f"  ⚠️  worker thread crashed: {str(exc)[:160]}")
    finally:
        pbar.close()
        out_fh.close()

    print(f"\n{'=' * 70}")
    print("LABELING COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Labeled OK:  {stats['ok']}")
    print(f"  Failed:      {stats['fail']}")
    print(f"\n  Label distribution (this run):")
    for label, count in label_dist.most_common():
        print(f"    {label:22s}: {count}")
    print(f"\n  Staging file: {output_path}")
    print(f"\n  Next: merge into the training file with")
    print(f"    python scripts/generate_classifier_data_from_synthetic.py \\")
    print(f"        --merge-into data/agent_training/classifier_train_regenerated_cleaned.jsonl")


if __name__ == "__main__":
    main()
