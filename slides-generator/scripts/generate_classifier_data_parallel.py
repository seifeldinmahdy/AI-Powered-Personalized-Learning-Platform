#!/usr/bin/env python3
"""
generate_classifier_data_parallel.py — Parallelized classifier training data generator.

Uses every available Ollama Cloud API key simultaneously — one worker thread
pinned per key — drawn from the shared key pool (mcq_service/.env's fleet first,
then slides-generator/.env). Workers pull from a shared thread-safe queue;
output is written to a single JSONL file with a threading.Lock() guard.

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
from slide_gen.data_engine.key_pool import (
    load_ollama_keys, describe_key_sources, probe_live_keys,
)
from slide_gen.training.classifier_data_generator import (
    validate_classifier_output,
    get_classifier_feedback,
)

load_dotenv(project_root / ".env")


# =============================================================================
# CONFIGURATION
# =============================================================================

CONFIG = {
    # API keys are loaded from the shared pool — mcq_service/.env's 13-key fleet
    # first, then slides-generator/.env fallbacks. One worker is pinned per key.
    "api_keys": load_ollama_keys(),
    "ollama_host": os.getenv("OLLAMA_HOST", "http://localhost:11434"),
    "model": os.getenv("OLLAMA_MODEL", "gpt-oss-120b"),
    "output_file": str(project_root / "data" / "agent_training" / "classifier_train_regenerated.jsonl"),
    "raw_books_dir": str(project_root / "data" / "raw_books"),
    "prompts_path": str(project_root / "config" / "prompts_classifier.yaml"),
    "chunk_size": 1000,
    "chunk_overlap": 100,
    "max_retries": 3,
    "retry_delay": 2,
    "num_workers": None,  # default: one worker per available key
    # Resilience: consecutive transport failures before a key is retired, and
    # how many times a single chunk is re-queued for content failures before it
    # is preserved to the failed-file (API/quota failures re-queue indefinitely
    # across keys and never count against the chunk).
    "key_fail_threshold": 3,
    "max_chunk_attempts": 3,
}


# =============================================================================
# RELABELING — normalize legacy sub-type labels produced before prompt fix
# =============================================================================

RELABEL_TO_CONCEPTUAL = {"concept_box", "comparison", "analogy_diagram"}
NONE_CAP = 300  # max none samples in final output


# =============================================================================
# SHARED STATE
# =============================================================================

class SharedState:
    """
    Holds all mutable shared state between worker threads.
    All counters are updated under their own locks.
    """

    def __init__(self, num_workers: int, key_fail_threshold: int = 3):
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

        # ── Key-health / resilience state ──────────────────────────────────
        self.num_workers = num_workers
        self.key_fail_threshold = key_fail_threshold
        self.key_lock = threading.Lock()
        self.dead_workers: set[int] = set()          # workers whose key is exhausted/dead
        self.key_consec_fail: dict[int, int] = {i: 0 for i in range(1, num_workers + 1)}
        self.requeued = 0                            # chunks put back for another key
        self.preserved_failed = 0                    # chunks written to the failed-file
        # Set when EVERY key is dead → workers stop and the run pauses (resume
        # later via output-hash). Not "complete" — remaining chunks are retried
        # on the next run.
        self.stop_event = threading.Event()


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
) -> tuple[str | None, str]:
    """
    Call the Ollama /api/generate endpoint with per-worker API key.

    Returns (response_text, status) where status is one of:
      "ok"         — got a response (text may still be empty)
      "rate_limit" — HTTP 429 (key over weekly/quota cap) — DO NOT retry this key
      "auth"       — HTTP 401/403 (bad/forbidden key) — key is dead
      "transport"  — network/5xx error after retries

    A "rate_limit"/"auth" key should be retired by the caller and the chunk
    re-queued for a different key. "transport" is transient.
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

            # Quota/rate limit — retrying the SAME key is futile; retire it.
            if resp.status_code == 429:
                return None, "rate_limit"

            # Auth errors — key is dead, no point retrying.
            if resp.status_code in (401, 403):
                return None, "auth"

            resp.raise_for_status()
            return resp.json().get("response", ""), "ok"

        except requests.RequestException as e:
            if attempt < max_retries:
                time.sleep(retry_delay)
            else:
                print(
                    f"\n  [W{worker_id}] ⚠️  transport error after {max_retries} "
                    f"tries for chunk {chunk_h}: {str(e)[:80]}"
                )
                return None, "transport"

    return None, "transport"


# =============================================================================
# WORKER
# =============================================================================

def worker(
    worker_id: int,
    api_key: str,
    chunk_queue: queue.Queue,
    state: SharedState,
    output_path: Path,
    failed_path: Path,
    host: str,
    model: str,
    system_prompt: str,
    user_template: str,
    max_retries: int,
    retry_delay: float,
    max_chunk_attempts: int,
) -> None:
    """
    Worker thread function (resilient).

    Pulls chunks from chunk_queue one at a time and classifies them. Key rules:
      • API error (429/auth/transport): the CHUNK IS RE-QUEUED for another key —
        never dropped. The failing key is penalized; on 429/auth (or repeated
        transport failures) the key is retired and this worker exits.
      • If every key is retired, the run PAUSES (state.stop_event) — remaining
        chunks stay unprocessed and are picked up on the next run via the
        output-hash resume (no separate checkpoint needed).
      • Content failure (LLM answered but output unusable): re-queued up to
        max_chunk_attempts, then PRESERVED to the failed-file (never silently
        dropped) so the chunk can be inspected/re-run later.
    """
    def _mark_pbar(advance: bool = True):
        if state.pbar is None:
            return
        with state.pbar_lock, state.counter_lock:
            if advance:
                state.pbar.update(1)
            total_ok = sum(state.worker_success.values())
            total_all = total_ok + sum(state.worker_fail.values())
            rate = total_ok / max(total_all, 1) * 100
            live = state.num_workers - len(state.dead_workers)
            state.pbar.set_description(
                f"ok={total_ok} rq={state.requeued} keys={live}/{state.num_workers} | {rate:.0f}%"
            )

    def _retire_key(reason: str) -> bool:
        """Record a key failure; return True if this worker should exit."""
        with state.key_lock:
            if reason in ("rate_limit", "auth"):
                state.dead_workers.add(worker_id)
                retire = True
            else:  # transport — only retire after repeated consecutive failures
                state.key_consec_fail[worker_id] += 1
                retire = state.key_consec_fail[worker_id] >= state.key_fail_threshold
                if retire:
                    state.dead_workers.add(worker_id)
            all_dead = len(state.dead_workers) >= state.num_workers
        if all_dead and not state.stop_event.is_set():
            state.stop_event.set()
            tqdm.write("\n  ⏸️  All API keys exhausted/dead — pausing. Re-run the "
                       "same command to resume (already-saved chunks are skipped).")
        if retire:
            tqdm.write(f"  🔌 [W{worker_id}] key ...{(api_key or '')[-8:]} retired "
                       f"({reason}); its chunks were re-queued for other keys.")
        return retire

    while not state.stop_event.is_set():
        # ── Pull next chunk ──
        try:
            chunk_text, book_name, attempts = chunk_queue.get(timeout=5)
        except queue.Empty:
            break  # Queue exhausted — exit cleanly

        chunk_h = chunk_hash(chunk_text)
        title = chunk_text.split(".")[0][:80] if "." in chunk_text else chunk_text[:80]
        base_prompt = user_template.format(bullets_text=chunk_text, title=title)

        # ── Classify with retry-feedback (mirrors classify_one logic) ──
        result_record = None
        api_error = None            # set if an LLM API/transport error occurred
        last_error = None           # content-level error code
        prompt = base_prompt

        for attempt in range(max_retries):
            if attempt > 0 and last_error:
                feedback = get_classifier_feedback(last_error, chunk_text=chunk_text)
                prompt = (
                    f"{base_prompt}\n\n"
                    f"## PREVIOUS ATTEMPT FEEDBACK:\n{feedback}\n\n"
                    f"Fix the issue. Output ONLY valid JSON."
                )

            raw, status = call_ollama(
                host=host, model=model, api_key=api_key,
                system_prompt=system_prompt, user_prompt=prompt,
                worker_id=worker_id, max_retries=2, retry_delay=retry_delay,
                chunk_h=chunk_h,
            )

            # API/transport failure — stop the content loop, handle re-queue
            if status != "ok":
                api_error = status
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

            result_record = {
                "text": chunk_text,
                "label": parsed["template_id"],
                "_chunk_hash": chunk_h,
                "_worker_id": worker_id,
                "_book": book_name,
            }
            break

        # ── Outcome handling ──────────────────────────────────────────────
        if result_record is not None:
            # Success — reset this key's consecutive-failure counter.
            with state.key_lock:
                state.key_consec_fail[worker_id] = 0
            with state.file_lock:
                with open(output_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(result_record) + "\n")
            with state.counter_lock:
                state.worker_success[worker_id] += 1
                state.total_processed += 1
            with state.label_lock:
                state.label_dist[result_record["label"]] += 1
            _mark_pbar(advance=True)
            chunk_queue.task_done()

        elif api_error is not None:
            # PRESERVE the chunk — re-queue it for a different key (same attempt
            # count; the failure was the key's fault, not the chunk's).
            chunk_queue.put((chunk_text, book_name, attempts))
            with state.key_lock:
                state.requeued += 1
            chunk_queue.task_done()
            _mark_pbar(advance=False)
            should_exit = _retire_key(api_error)
            if should_exit:
                return
            time.sleep(retry_delay)  # brief backoff on transient transport error

        else:
            # Content failure (LLM responded but output unusable).
            if attempts + 1 < max_chunk_attempts:
                chunk_queue.put((chunk_text, book_name, attempts + 1))
                with state.key_lock:
                    state.requeued += 1
                chunk_queue.task_done()
                _mark_pbar(advance=False)
            else:
                # Out of attempts — PRESERVE to the failed-file, never drop.
                with state.file_lock:
                    with open(failed_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps({
                            "text": chunk_text, "_book": book_name,
                            "_reason": last_error or "unknown",
                            "_chunk_hash": chunk_h,
                        }) + "\n")
                with state.counter_lock:
                    state.worker_fail[worker_id] += 1
                    state.total_processed += 1
                with state.key_lock:
                    state.preserved_failed += 1
                _mark_pbar(advance=True)
                chunk_queue.task_done()


# =============================================================================
# POST-PROCESSING
# =============================================================================

def postprocess_output(output_path: Path) -> dict:
    """
    Two-step post-processor applied once after all workers finish:

    Step 1 — Relabeling: any sample labeled concept_box, comparison, or
      analogy_diagram gets relabeled to conceptual. These labels were produced
      before the prompt was updated and should be normalized.

    Step 2 — none cap: randomly retain at most NONE_CAP=300 none samples.
      Excess none samples are removed to reduce class imbalance.

    Rewrites the file in-place. Returns a summary dict.
    """
    import random as _random

    with open(output_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    parsed = []
    for line in lines:
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    original_count = len(parsed)

    # ── Step 1: Relabel ──
    relabeled_count = 0
    for sample in parsed:
        if sample.get("label") in RELABEL_TO_CONCEPTUAL:
            sample["label"] = "conceptual"
            relabeled_count += 1

    # ── Step 2: Cap none ──
    none_samples = [s for s in parsed if s.get("label") == "none"]
    other_samples = [s for s in parsed if s.get("label") != "none"]
    none_removed = max(0, len(none_samples) - NONE_CAP)
    _random.seed(42)
    none_kept = _random.sample(none_samples, min(NONE_CAP, len(none_samples)))
    final = other_samples + none_kept
    _random.shuffle(final)

    with open(output_path, "w", encoding="utf-8") as f:
        for sample in final:
            f.write(json.dumps(sample) + "\n")

    return {
        "original_count": original_count,
        "relabeled_count": relabeled_count,
        "none_removed": none_removed,
        "final_count": len(final),
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
        help="Number of parallel workers (default: one per available API key)",
    )
    parser.add_argument(
        "--no-probe-keys", action="store_true",
        help="Skip the startup key-health probe (dead keys are still retired at runtime)",
    )
    args = parser.parse_args()

    # ── Override config from CLI args ──
    raw_books_dir = Path(args.books) if args.books else Path(CONFIG["raw_books_dir"])
    output_path   = Path(args.output) if args.output else Path(CONFIG["output_file"])

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Validate API keys ──
    valid_keys: list[str] = [k for k in CONFIG["api_keys"] if k]
    if not valid_keys:
        print("❌ No API keys found. Set OLLAMA_API_KEY_1 … in mcq_service/.env "
              "(or OLLAMA_API_KEY in slides-generator/.env)")
        sys.exit(1)

    # Drop keys that are already weekly-exhausted/forbidden so we don't spawn
    # dead workers. (Runtime handling still re-queues + retires keys that die
    # mid-run, but probing up front avoids wasted churn.)
    if not args.no_probe_keys:
        print(f"🔍 Probing {len(valid_keys)} keys for free-plan quota...")
        live = probe_live_keys(valid_keys, host=CONFIG["ollama_host"])
        dead = len(valid_keys) - len(live)
        if live:
            print(f"   → {len(live)} live, {dead} exhausted/forbidden (dropped)")
            valid_keys = live
        else:
            print("   ⚠️  No live keys detected — proceeding with all (may pause quickly).")

    # Default to one worker per key; --workers caps it (keys are then round-robined).
    requested_workers = args.workers if args.workers else len(valid_keys)
    num_workers = min(requested_workers, len(valid_keys))
    assigned_keys = valid_keys[:num_workers]

    print("=" * 70)
    print("PARALLEL CLASSIFIER DATA GENERATOR")
    print("=" * 70)
    print(f"  Ollama host:  {CONFIG['ollama_host']}")
    print(f"  Model:        {CONFIG['model']}")
    print(f"  Key sources:  {describe_key_sources()}")
    print(f"  API keys:     {len(valid_keys)}")
    print(f"  Workers:      {num_workers} (one pinned per key)")
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

    # Chunks that have repeatedly failed CONTENT validation are preserved here
    # (never silently dropped) so they can be inspected / re-run.
    failed_path = output_path.with_name(output_path.stem + "_failed.jsonl")

    # ── Fill queue ── (3-tuple: text, book, attempt_count)
    chunk_q: queue.Queue = queue.Queue()
    for text, book in pending:
        chunk_q.put((text, book, 0))

    total_chunks = len(pending)

    # ── Shared state ──
    state = SharedState(num_workers, key_fail_threshold=CONFIG["key_fail_threshold"])

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
                failed_path=failed_path,
                host=CONFIG["ollama_host"],
                model=CONFIG["model"],
                system_prompt=system_prompt,
                user_template=user_template,
                max_retries=CONFIG["max_retries"],
                retry_delay=CONFIG["retry_delay"],
                max_chunk_attempts=CONFIG["max_chunk_attempts"],
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

    # ── Paused? (all keys died) — skip post-processing, leave remainder for resume ──
    paused = state.stop_event.is_set()
    remaining = chunk_q.qsize()
    if paused:
        print(f"\n{'=' * 70}")
        print("⏸️  GENERATION PAUSED — all API keys were exhausted/dead.")
        print(f"{'=' * 70}")
        print(f"   Chunks left unprocessed: ~{remaining} (preserved — NOT dropped).")
        print(f"   They are not in the output, so re-running the SAME command after")
        print(f"   your weekly quota resets (or with fresh keys) resumes exactly")
        print(f"   where it stopped. Post-processing skipped until the run completes.")
        # Still report what was done this run, but don't cap/relabel a partial file.
        pp_results: dict = {}
    else:
        # ── Post-processing: relabel + cap none (only on a COMPLETE run) ──
        print("\n🔎 Post-processing output...")
        pp_results = {}
        if output_path.exists():
            pp_results = postprocess_output(output_path)
            print(f"   Relabeled to conceptual:    {pp_results.get('relabeled_count', 0)} samples")
            print(f"   none samples removed (cap): {pp_results.get('none_removed', 0)} samples")
            print(f"   Final sample count:         {pp_results.get('final_count', 0)} samples")

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
    print(f"   Re-queued (API errors):     {state.requeued}  (preserved, retried on another key)")
    print(f"   Preserved to failed-file:   {state.preserved_failed}")
    print(f"   Dead/exhausted keys:        {len(state.dead_workers)}/{num_workers}")
    print(f"   Success rate:               {success_rate:.1f}%")
    print(f"   Total time elapsed:         {elapsed:.1f}s ({elapsed/60:.1f} min)")
    print(f"   Output file:                {output_path}")
    if state.preserved_failed:
        print(f"   Failed-file:                {failed_path}")
    print(f"   Final line count:           {final_line_count}")
    if paused:
        print(f"   ⏸️  PAUSED — ~{remaining} chunks remain; re-run to resume.")

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
