#!/usr/bin/env python3
"""
generate_classifier_data_parallel.py — Parallelized classifier training data generator.

Uses 4 Ollama API keys simultaneously across 4 worker threads.
Workers pull from a shared thread-safe queue; output is written to a
single JSONL file with a threading.Lock() guard.

Fully resumable: chunks already present in the output file are skipped
on restart using an MD5 hash of the chunk text.

Usage:
    python scripts/generate_classifier_data_parallel.py
    python scripts/generate_classifier_data_parallel.py \\
        --books data/raw_books \\
        --output data/agent_training/classifier_train_regenerated.jsonl \\
        --workers 4
"""

import argparse
import hashlib
import json
import os
import queue
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv
from tqdm import tqdm

# ── Path setup ──────────────────────────────────────────────────────────────
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from slide_gen.data_engine.pdf_loader import load_and_chunk_pdf
from slide_gen.data_engine.utils import extract_json_from_response, is_valid_chunk
from slide_gen.training.classifier_data_generator import (
    validate_classifier_output,
    get_classifier_feedback,
)

load_dotenv(project_root / ".env")


# =============================================================================
# CONFIGURATION
# =============================================================================

CONFIG = {
    "api_keys": [
        os.getenv("OLLAMA_API_KEY_1", "bcf07a378dfb44da818ad681b764218c.Cj45gsSIZV1b6mGBydzcxV1w"),
        os.getenv("OLLAMA_API_KEY_2", "41b275bb75b94608b0b2282017007a20.3-B2BlRstnRgISP3o031hC_y"),
        os.getenv("OLLAMA_API_KEY_3", "4de258e1b9f74e18aa87bf851ec04509.S6em4rsHYaW2AuHKdjkquutt"),
        os.getenv("OLLAMA_API_KEY_4", "0f109a4a8f3d4e82ba1989088d44b634.KOrFmimtJol5WpYEu5ixbuki"),
        os.getenv("OLLAMA_API_KEY_5", "ea17157f34474347bdc8b250133cf210.52w4zyYC7b8X2gvNkH-YPYMm"),
    ],
    "ollama_host": os.getenv("OLLAMA_HOST", "http://localhost:11434"),
    "model": os.getenv("OLLAMA_MODEL", "gpt-oss-120b"),
    "output_file": str(project_root / "data" / "agent_training" / "classifier_train_regenerated.jsonl"),
    "raw_books_dir": str(project_root / "data" / "raw_books"),
    "prompts_path": str(project_root / "config" / "prompts_classifier.yaml"),
    "chunk_size": 1000,
    "chunk_overlap": 100,
    "max_retries": 3,
    "retry_delay": 2,
    "num_workers": 5,
}


# =============================================================================
# EXCLUDED LABELS — handled by LLM enrichment layer, never valid classifier outputs
# =============================================================================

EXCLUDED_LABELS = {"concept_box", "comparison", "analogy_diagram"}


# =============================================================================
# SHARED STATE
# =============================================================================

class SharedState:
    """
    Holds all mutable shared state between worker threads.
    All counters are updated under their own locks.
    """

    def __init__(self, num_workers: int):
        # File write lock — all JSONL appends go through this
        self.file_lock = threading.Lock()

        # Progress bar lock — for clean postfix updates
        self.pbar_lock = threading.Lock()

        # Per-worker success/failure counters (worker_id → count)
        self.worker_success: dict[int, int] = {i: 0 for i in range(1, num_workers + 1)}
        self.worker_fail: dict[int, int] = {i: 0 for i in range(1, num_workers + 1)}
        self.counter_lock = threading.Lock()

        # Label distribution (label → count)
        self.label_dist: Counter = Counter()
        self.label_lock = threading.Lock()

        # Total processed (success + fail) — drives tqdm
        self.total_processed = 0

        # Progress bar — set after creation
        self.pbar: tqdm | None = None


# =============================================================================
# CHUNK HASHING
# =============================================================================

def chunk_hash(text: str) -> str:
    """Return a 12-char MD5 prefix identifying this chunk."""
    return hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def load_already_processed(output_path: Path) -> set[str]:
    """
    Read the output JSONL and collect all _chunk_hash values.
    Returns a set of hashes for chunks already generated.
    """
    done: set[str] = set()
    if not output_path.exists():
        return done
    with open(output_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                h = obj.get("_chunk_hash")
                if h:
                    done.add(h)
            except json.JSONDecodeError:
                continue
    return done


# =============================================================================
# OLLAMA CALL
# =============================================================================

def call_ollama(
    host: str,
    model: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    worker_id: int,
    max_retries: int,
    retry_delay: float,
    chunk_h: str,
) -> str | None:
    """
    Call the Ollama /api/generate endpoint with per-worker API key.

    Returns raw response text or None on total failure.
    Retries up to max_retries times with retry_delay seconds between attempts.
    On auth failure (HTTP 401/403), immediately returns None without retrying.
    """
    url = f"{host.rstrip('/')}/api/generate"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": model,
        "prompt": user_prompt,
        "system": system_prompt,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "top_p": 0.9,
        },
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=120)

            # Auth errors — no point retrying
            if resp.status_code in (401, 403):
                print(
                    f"\n  [W{worker_id}] ❌ Auth error (HTTP {resp.status_code}) "
                    f"for key ...{api_key[-8:]}. Worker will exit."
                )
                return None

            resp.raise_for_status()
            return resp.json().get("response", "")

        except requests.RequestException as e:
            if attempt < max_retries:
                time.sleep(retry_delay)
            else:
                print(
                    f"\n  [W{worker_id}] ⚠️  All {max_retries} retries failed "
                    f"for chunk {chunk_h}: {e}"
                )
                return None

    return None


# =============================================================================
# WORKER
# =============================================================================

def worker(
    worker_id: int,
    api_key: str,
    chunk_queue: queue.Queue,
    state: SharedState,
    output_path: Path,
    host: str,
    model: str,
    system_prompt: str,
    user_template: str,
    max_retries: int,
    retry_delay: float,
) -> None:
    """
    Worker thread function.

    Pulls chunks from chunk_queue one at a time.
    Calls Ollama, validates output, writes result to JSONL.
    Exits cleanly when queue is exhausted or on auth failure.
    """
    while True:
        # ── Pull next chunk ──
        try:
            chunk_text, book_name = chunk_queue.get(timeout=5)
        except queue.Empty:
            break  # Queue exhausted — exit cleanly

        chunk_h = chunk_hash(chunk_text)
        title = chunk_text.split(".")[0][:80] if "." in chunk_text else chunk_text[:80]

        # ── Build prompt (same template as ClassifierDataGenerator) ──
        base_prompt = user_template.format(
            bullets_text=chunk_text,
            title=title,
        )

        # ── Classify with retry-feedback (mirrors classify_one logic) ──
        result_record = None
        last_error = None
        prompt = base_prompt

        for attempt in range(max_retries):
            if attempt > 0 and last_error:
                feedback = get_classifier_feedback(last_error, chunk_text=chunk_text)
                prompt = (
                    f"{base_prompt}\n\n"
                    f"## PREVIOUS ATTEMPT FEEDBACK:\n{feedback}\n\n"
                    f"Fix the issue. Output ONLY valid JSON."
                )

            raw = call_ollama(
                host=host,
                model=model,
                api_key=api_key,
                system_prompt=system_prompt,
                user_prompt=prompt,
                worker_id=worker_id,
                max_retries=1,          # outer loop already handles retries
                retry_delay=retry_delay,
                chunk_h=chunk_h,
            )

            # Auth failure — worker exits
            if raw is None and attempt == 0:
                # Check if it's an auth failure (call_ollama already printed)
                # We can't distinguish network from auth at this point unless
                # we propagate a flag; simplest: break on first None and skip chunk
                last_error = "no_response"
                break

            if not raw:
                last_error = "no_response"
                continue

            parsed = extract_json_from_response(raw)
            if not parsed:
                last_error = "json_parse_error"
                continue

            if "template_id" not in parsed:
                last_error = "missing_fields"
                continue

            parsed["template_id"] = parsed["template_id"].strip().lower()

            is_valid, error_code = validate_classifier_output(parsed, chunk_text)
            if not is_valid:
                last_error = error_code
                continue

            # ── Success ──
            label = parsed["template_id"]
            result_record = {
                "text": chunk_text,
                "label": label,
                "_chunk_hash": chunk_h,
                "_worker_id": worker_id,
                "_book": book_name,
            }
            break

        # ── Write result ──
        if result_record is not None:
            with state.file_lock:
                with open(output_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(result_record) + "\n")

            with state.counter_lock:
                state.worker_success[worker_id] += 1
                state.total_processed += 1

            with state.label_lock:
                state.label_dist[result_record["label"]] += 1
        else:
            with state.counter_lock:
                state.worker_fail[worker_id] += 1
                state.total_processed += 1

        # ── Update progress bar ──
        if state.pbar is not None:
            with state.pbar_lock:
                state.pbar.update(1)
                with state.counter_lock:
                    desc_parts = " ".join(
                        f"W{wid}:{state.worker_success[wid]}"
                        for wid in sorted(state.worker_success)
                    )
                total_ok = sum(state.worker_success.values())
                total_all = sum(state.worker_success.values()) + sum(state.worker_fail.values())
                rate = total_ok / max(total_all, 1) * 100
                state.pbar.set_description(f"{desc_parts} | ok={rate:.0f}%")

        chunk_queue.task_done()


# =============================================================================
# POST-PROCESSING FILTER
# =============================================================================

def filter_excluded_labels(output_path: Path) -> dict:
    """
    Remove any samples labeled with EXCLUDED_LABELS from the output file.

    Rewrites the file in-place. Returns a summary dict with counts.
    Called once after all workers finish, before the final report.
    """
    with open(output_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    parsed = []
    for line in lines:
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    original_count = len(parsed)
    filtered = [s for s in parsed if s.get("label") not in EXCLUDED_LABELS]
    removed_count = original_count - len(filtered)

    removed_by_label: dict[str, int] = {}
    for s in parsed:
        label = s.get("label")
        if label in EXCLUDED_LABELS:
            removed_by_label[label] = removed_by_label.get(label, 0) + 1

    with open(output_path, "w", encoding="utf-8") as f:
        for sample in filtered:
            f.write(json.dumps(sample) + "\n")

    return {
        "original_count": original_count,
        "filtered_count": len(filtered),
        "removed_count": removed_count,
        "removed_by_label": removed_by_label,
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Parallelized classifier training data generator (4 API keys)"
    )
    parser.add_argument(
        "--books", type=str, default=None,
        help="Directory containing PDF files (default: data/raw_books)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSONL file path (default: data/agent_training/classifier_train_regenerated.jsonl)",
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help="Number of parallel workers (default: 4, or number of valid API keys)",
    )
    args = parser.parse_args()

    # ── Override config from CLI args ──
    raw_books_dir = Path(args.books) if args.books else Path(CONFIG["raw_books_dir"])
    output_path   = Path(args.output) if args.output else Path(CONFIG["output_file"])
    requested_workers = args.workers if args.workers else CONFIG["num_workers"]

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Validate API keys ──
    api_keys_raw = CONFIG["api_keys"]
    valid_keys: list[str] = []
    for i, key in enumerate(api_keys_raw, 1):
        if key:
            valid_keys.append(key)
        else:
            print(f"  ⚠️  OLLAMA_API_KEY_{i} is None — skipping worker {i}")

    num_workers = min(requested_workers, len(valid_keys))
    if num_workers == 0:
        print("❌ No valid API keys found. Set OLLAMA_API_KEY_1 … OLLAMA_API_KEY_4 in your .env")
        sys.exit(1)

    assigned_keys = valid_keys[:num_workers]

    print("=" * 70)
    print("PARALLEL CLASSIFIER DATA GENERATOR")
    print("=" * 70)
    print(f"  Ollama host:  {CONFIG['ollama_host']}")
    print(f"  Model:        {CONFIG['model']}")
    print(f"  Workers:      {num_workers}")
    print(f"  Output:       {output_path}")
    print(f"  Books dir:    {raw_books_dir}")

    # ── Load prompts ──
    prompts_path = Path(CONFIG["prompts_path"])
    if not prompts_path.exists():
        print(f"❌ Prompts not found: {prompts_path}")
        sys.exit(1)
    with open(prompts_path) as f:
        prompts = yaml.safe_load(f)
    system_prompt = prompts["classifier_system_prompt"]
    user_template = prompts["classifier_user_template"]

    # ── Load all PDF chunks ──
    pdf_files = sorted(raw_books_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"❌ No PDFs found in {raw_books_dir}")
        sys.exit(1)

    print(f"\n📚 Loading PDFs ({len(pdf_files)} files)...")
    all_chunks: list[tuple[str, str]] = []   # (chunk_text, book_name)
    for pdf_path in pdf_files:
        print(f"  Loading: {pdf_path.name}")
        try:
            raw_chunks = load_and_chunk_pdf(
                pdf_path,
                chunk_size=CONFIG["chunk_size"],
                chunk_overlap=CONFIG["chunk_overlap"],
            )
            valid_count = 0
            for chunk in raw_chunks:
                ok, _ = is_valid_chunk(chunk)
                if ok:
                    all_chunks.append((chunk, pdf_path.name))
                    valid_count += 1
            print(f"    → {valid_count} valid chunks (of {len(raw_chunks)} total)")
        except Exception as e:
            print(f"    ⚠️  Error loading {pdf_path.name}: {e}")

    print(f"\n  Total valid chunks: {len(all_chunks)}")

    # ── Resumability: skip already-processed chunks ──
    print(f"\n🔍 Checking for existing output (resumability)...")
    already_done = load_already_processed(output_path)
    print(f"  Already processed: {len(already_done)} chunks")

    pending: list[tuple[str, str]] = [
        (text, book)
        for text, book in all_chunks
        if chunk_hash(text) not in already_done
    ]
    print(f"  Remaining:         {len(pending)} chunks to process")

    if not pending:
        print("\n✅ All chunks already processed. Nothing to do.")
        sys.exit(0)

    # ── Fill queue ──
    chunk_q: queue.Queue = queue.Queue()
    for item in pending:
        chunk_q.put(item)

    total_chunks = len(pending)

    # ── Shared state ──
    state = SharedState(num_workers)

    # ── Progress bar ──
    state.pbar = tqdm(
        total=total_chunks,
        desc="Starting...",
        unit="chunk",
        dynamic_ncols=True,
    )

    # ── Launch workers ──
    start_time = time.time()
    threads: list[threading.Thread] = []

    for wid in range(1, num_workers + 1):
        t = threading.Thread(
            target=worker,
            name=f"Worker-{wid}",
            kwargs=dict(
                worker_id=wid,
                api_key=assigned_keys[wid - 1],
                chunk_queue=chunk_q,
                state=state,
                output_path=output_path,
                host=CONFIG["ollama_host"],
                model=CONFIG["model"],
                system_prompt=system_prompt,
                user_template=user_template,
                max_retries=CONFIG["max_retries"],
                retry_delay=CONFIG["retry_delay"],
            ),
            daemon=True,
        )
        threads.append(t)
        t.start()

    # ── Wait for all workers to finish ──
    for t in threads:
        t.join()

    state.pbar.close()

    elapsed = time.time() - start_time

    # ── Filter excluded labels ──
    print("\n🔎 Filtering excluded labels...")
    filter_results: dict = {}
    if output_path.exists():
        filter_results = filter_excluded_labels(output_path)
        removed_by_label = filter_results.get("removed_by_label", {})
        for label in sorted(EXCLUDED_LABELS):
            n = removed_by_label.get(label, 0)
            print(f"   Removed {label:25s}: {n} samples")
        print(f"   Total removed:              {filter_results.get('removed_count', 0)} samples")
        print(f"   Final sample count:         {filter_results.get('filtered_count', 0)} samples")

    # ── Count final output lines ──
    final_line_count = 0
    if output_path.exists():
        with open(output_path) as f:
            final_line_count = sum(1 for line in f if line.strip())

    # ── Final report ──
    total_ok  = sum(state.worker_success.values())
    total_fail = sum(state.worker_fail.values())
    success_rate = total_ok / max(total_ok + total_fail, 1) * 100

    print(f"\n{'=' * 70}")
    print("📊 PARALLEL GENERATION REPORT")
    print(f"{'=' * 70}")

    print(f"\n📋 Overview:")
    print(f"   Total chunks in queue:      {total_chunks}")
    print(f"   Successfully generated:     {total_ok}")
    print(f"   Failed / skipped:           {total_fail}")
    print(f"   Success rate:               {success_rate:.1f}%")
    print(f"   Total time elapsed:         {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f"   Output file:                {output_path}")
    print(f"   Final line count:           {final_line_count}")

    print(f"\n👷 Per-Worker Results:")
    for wid in sorted(state.worker_success.keys()):
        ok   = state.worker_success[wid]
        fail = state.worker_fail[wid]
        key_preview = assigned_keys[wid - 1][-8:] if wid <= len(assigned_keys) else "N/A"
        print(f"   Worker {wid} (key ...{key_preview}): {ok} ok, {fail} fail")

    if state.label_dist:
        max_count = max(state.label_dist.values())
        print(f"\n📊 Label Distribution (newly generated):")
        for label, count in state.label_dist.most_common():
            pct = count / max(total_ok, 1) * 100
            bar = "█" * int(count / max_count * 30)
            print(f"   {label:25s}: {count:4d} ({pct:5.1f}%) {bar}")

    print(f"\n✅ Done. Output → {output_path}")
    print(f"{'=' * 70}\n")


if __name__ == "__main__":
    main()
