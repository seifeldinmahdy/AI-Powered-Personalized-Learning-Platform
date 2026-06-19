#!/usr/bin/env python3
"""
Targeted synthetic-chunk generator — fill & balance under-represented classes.

Unlike the generic MCQ-style synthetic chunks (which mostly collapse into
`conceptual`), this generator uses a DEDICATED per-class prompt
(config/prompts_synthetic_chunks.yaml) engineered to make the teacher LLM write
CS content that triggers a SPECIFIC visual-template label. Each generated chunk
is then VERIFIED by running it through the real visual classifier; only chunks
the classifier confirms as the intended target are kept (strict mode, default),
so the resulting data is correctly labeled AND moves the dataset toward balance.

Pipeline position (run AFTER the book-sourced data exists):
    1. Generate from books:  scripts/generate_classifier_data.py
    2. Inspect / plan:        this script with --plan-only --reference <books.jsonl>
    3. Generate & verify:     this script (fills each class up to --target-per-class)
    4. Merge:                 this script with --merge-into <final.jsonl>

Two LLM calls happen per attempt: one to GENERATE the chunk (generation system
prompt) and one to CLASSIFY it (the existing ClassifierDataGenerator). Generation
is oversampled by --oversample because not every attempt lands on the target.

Examples
--------
# See current distribution + how many of each class are needed to reach 300:
python scripts/generate_targeted_synthetic_chunks.py \
    --reference data/agent_training/classifier_train_books_cleaned.jsonl \
    --target-per-class 300 --plan-only

# Generate & verify chunks to fill the deficits (writes a staging file):
python scripts/generate_targeted_synthetic_chunks.py \
    --reference data/agent_training/classifier_train_books_cleaned.jsonl \
    --target-per-class 300 --workers 4 \
    --output classifier_train_targeted_synthetic.jsonl

# Force a fixed count for specific classes (ignores the reference deficit):
python scripts/generate_targeted_synthetic_chunks.py \
    --classes graph,queue,general_tree --count 200 \
    --output classifier_train_targeted_synthetic.jsonl

# Merge the verified staging file into the final training file (dedup by text):
python scripts/generate_targeted_synthetic_chunks.py \
    --output classifier_train_targeted_synthetic.jsonl \
    --merge-into data/agent_training/classifier_train_regenerated_cleaned.jsonl
"""

import argparse
import hashlib
import json
import math
import os
import queue as _queue
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv
from tqdm import tqdm

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from slide_gen.training.classifier_data_generator import ClassifierDataGenerator  # noqa: E402
from slide_gen.data_engine.key_pool import (  # noqa: E402
    load_ollama_keys, describe_key_sources, probe_live_keys,
    load_nvidia_keys, get_nvidia_config,
)
from slide_gen.data_engine.nvidia_client import (  # noqa: E402
    NvidiaClient, NvidiaRateLimitError, NvidiaAuthError,
)

# Generation-call status codes (shared by both backends).
OK, RATE, AUTH, TRANSPORT = "ok", "rate_limit", "auth", "transport"


def _text_hash(text: str) -> str:
    return hashlib.md5(text.strip().encode("utf-8")).hexdigest()[:12]


# ──────────────────────────────────────────────────────────────────────────────
# Distribution helpers
# ──────────────────────────────────────────────────────────────────────────────

def label_distribution(path: Path) -> Counter:
    counts = Counter()
    if not path or not path.exists():
        return counts
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                counts[json.loads(line).get("label", "none")] += 1
            except json.JSONDecodeError:
                continue
    return counts


def load_done_counts(output_path: Path) -> tuple[Counter, set]:
    """Per-label counts and text-hashes already present in the staging file."""
    counts = Counter()
    hashes = set()
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
                counts[rec.get("label", "none")] += 1
                if rec.get("text"):
                    hashes.add(_text_hash(rec["text"]))
    return counts, hashes


def load_existing_texts(path: Path) -> set:
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
    print(f"\n{'=' * 60}\nMERGE COMPLETE")
    print(f"  Target: {target_path}")
    print(f"  Before: {before}  |  Added: {len(to_add)}  |  After: {before + len(to_add)}")
    print(f"{'=' * 60}")


# ──────────────────────────────────────────────────────────────────────────────
# Generation
# ──────────────────────────────────────────────────────────────────────────────

def clean_generated(text: str) -> str:
    """Light cleanup — strip wrapping quotes/whitespace and collapse blank lines."""
    text = (text or "").strip()
    if len(text) >= 2 and text[0] in "\"'" and text[-1] in "\"'":
        text = text[1:-1].strip()
    lines = [ln.strip() for ln in text.splitlines()]
    text = " ".join(ln for ln in lines if ln)
    return text.strip()


def build_plan(prompts_classes, ref_counts, staged_counts, args):
    """Return {class: deficit} for classes we still need to fill."""
    plan = {}
    classes = (
        [c.strip() for c in args.classes.split(",")] if args.classes
        else list(prompts_classes.keys())
    )
    for cls in classes:
        if cls not in prompts_classes:
            print(f"  ⚠️  No prompt for class '{cls}' — skipping")
            continue
        if args.count is not None:
            target = args.count
            current = staged_counts.get(cls, 0)  # count toward fixed quota
        else:
            target = args.target_per_class
            current = ref_counts.get(cls, 0) + staged_counts.get(cls, 0)
        deficit = max(0, target - current)
        plan[cls] = deficit
    return plan


def print_plan(ref_counts, staged_counts, plan, args):
    print(f"\n{'=' * 74}")
    print("BALANCING PLAN")
    print(f"{'=' * 74}")
    mode = f"fixed count={args.count}" if args.count is not None \
        else f"target-per-class={args.target_per_class}"
    print(f"Mode: {mode}\n")
    print(f"  {'class':22s} {'in_ref':>7} {'staged':>7} {'deficit':>8}")
    print(f"  {'-'*22} {'-'*7} {'-'*7} {'-'*8}")
    for cls, deficit in sorted(plan.items(), key=lambda kv: -kv[1]):
        print(f"  {cls:22s} {ref_counts.get(cls,0):>7} "
              f"{staged_counts.get(cls,0):>7} {deficit:>8}")
    total = sum(plan.values())
    print(f"  {'-'*22} {'-'*7} {'-'*7} {'-'*8}")
    print(f"  {'TOTAL TO GENERATE':22s} {'':>7} {'':>7} {total:>8}")
    if args.count is None:
        print(f"\n  (in_ref = count in --reference; staged = already verified in --output)")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Generate class-targeted synthetic chunks")
    p.add_argument("--reference", type=str, default=None,
                   help="Existing classifier JSONL whose distribution sets the deficits")
    p.add_argument("--target-per-class", type=int, default=300,
                   help="Desired samples per class (reference + staged). Default 300")
    p.add_argument("--classes", type=str, default=None,
                   help="Comma-separated subset of classes to generate (default: all in config)")
    p.add_argument("--count", type=int, default=None,
                   help="Fixed number to generate per class (overrides --target-per-class deficit)")
    p.add_argument("--oversample", type=float, default=2.0,
                   help="Generate deficit×oversample attempts (not every attempt hits the target)")
    p.add_argument("--max-attempts-per-class", type=int, default=2000,
                   help="Hard cap on generation attempts per class")
    p.add_argument("--keep-mismatches", action="store_true",
                   help="Also keep chunks whose classifier label != target (under the actual label)")
    p.add_argument("--output", type=str, default="classifier_train_targeted_synthetic.jsonl",
                   help="Staging output filename (joined to --output-dir)")
    p.add_argument("--output-dir", type=str, default="data/agent_training",
                   help="Directory for the staging file (default: data/agent_training)")
    p.add_argument("--prompts", type=str, default="config/prompts_synthetic_chunks.yaml")
    p.add_argument("--workers", type=int, default=None,
                   help="Ollama parallel workers (default: one per live API key)")
    p.add_argument("--max-keys", type=int, default=None,
                   help="Cap the number of Ollama API keys used from the pool")
    p.add_argument("--no-probe-keys", action="store_true",
                   help="Skip the startup Ollama key-health probe")
    p.add_argument("--ollama-model", type=str, default="gpt-oss:120b",
                   help="Ollama model for generation + classification")
    # ── NVIDIA NIM second backend (runs in parallel; takes over if Ollama dies) ──
    p.add_argument("--no-nvidia", action="store_true",
                   help="Disable the NVIDIA NIM backend (Ollama only)")
    p.add_argument("--nvidia-model", type=str, default="openai/gpt-oss-120b",
                   help="NVIDIA NIM model (OpenAI-compatible name for gpt-oss:120b)")
    p.add_argument("--nvidia-workers", type=int, default=8,
                   help="NVIDIA worker threads sharing the pooled account RPM limiter")
    p.add_argument("--temperature", type=float, default=0.85)
    p.add_argument("--plan-only", action="store_true",
                   help="Print the distribution + balancing plan and exit (no LLM calls)")
    p.add_argument("--merge-into", type=str, default=None,
                   help="Merge-only: append --output into this file (dedup by text) and exit")
    args = p.parse_args()

    load_dotenv(project_root / ".env")
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = project_root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / args.output

    # ── Merge-only mode ───────────────────────────────────────────────────
    if args.merge_into:
        target = Path(args.merge_into)
        if not target.is_absolute():
            target = project_root / target
        if not output_path.exists():
            print(f"❌ Staging file not found: {output_path}")
            sys.exit(1)
        merge_into(output_path, target)
        return

    # ── Load prompts ──────────────────────────────────────────────────────
    prompts_path = Path(args.prompts)
    if not prompts_path.is_absolute():
        prompts_path = project_root / prompts_path
    with open(prompts_path) as f:
        pcfg = yaml.safe_load(f)
    gen_system = pcfg["generation_system_prompt"]
    prompts_classes = pcfg["classes"]

    # ── Build plan ────────────────────────────────────────────────────────
    ref_path = Path(args.reference) if args.reference else None
    if ref_path and not ref_path.is_absolute():
        ref_path = project_root / ref_path
    ref_counts = label_distribution(ref_path) if ref_path else Counter()
    staged_counts, done_hashes = load_done_counts(output_path)

    if ref_path:
        print(f"Reference: {ref_path}")
        print("Current reference distribution:")
        for k, v in ref_counts.most_common():
            print(f"  {k:22s}: {v}")

    plan = build_plan(prompts_classes, ref_counts, staged_counts, args)
    print_plan(ref_counts, staged_counts, plan, args)

    if args.plan_only:
        print("\n(--plan-only set — no generation performed)")
        return

    to_make = {c: d for c, d in plan.items() if d > 0}
    if not to_make:
        print("\n✅ All targeted classes already at target. Nothing to generate.")
        print(f"   Merge with: --output {args.output} --merge-into <final.jsonl>")
        return

    # ── LLM config ────────────────────────────────────────────────────────
    host = os.getenv("OLLAMA_HOST", "https://ollama.com").rstrip("/")
    ollama_model = args.ollama_model
    max_retries = int(os.getenv("MAX_RETRIES", "3"))
    classifier_prompts = project_root / "config" / "prompts_classifier.yaml"

    # ── Backend transports (return (text, status)) ─────────────────────────
    def ollama_gen(key):
        def _g(system, user, temperature):
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            payload = {"model": ollama_model, "prompt": user, "system": system,
                       "stream": False,
                       "options": {"temperature": temperature, "top_p": 0.95}}
            try:
                r = requests.post(f"{host}/api/generate", json=payload,
                                  headers=headers, timeout=120)
                if r.status_code == 429:
                    return None, RATE
                if r.status_code in (401, 403):
                    return None, AUTH
                if r.status_code >= 500:
                    return None, TRANSPORT
                r.raise_for_status()
                return r.json().get("response", ""), OK
            except requests.RequestException:
                return None, TRANSPORT
        return _g

    def nvidia_gen(client):
        def _g(system, user, temperature):
            try:
                txt = client.chat(
                    [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
                    temperature=temperature,
                )
                return txt, OK
            except NvidiaRateLimitError:
                return None, RATE
            except NvidiaAuthError:
                return None, AUTH
            except Exception:
                return None, TRANSPORT
        return _g

    def nvidia_classify_override(client):
        def _call(system, user):
            try:
                return client.chat(
                    [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
                    temperature=0.7,
                )
            except Exception:
                return None
        return _call

    class Agent:
        __slots__ = ("name", "kind", "gen", "clf", "dead")
        def __init__(self, name, kind, gen, clf):
            self.name, self.kind, self.gen, self.clf = name, kind, gen, clf
            self.dead = False

    agents: list[Agent] = []

    # ── Ollama agents: one worker per LIVE cloud key ───────────────────────
    ollama_keys = load_ollama_keys(max_keys=args.max_keys)
    if ollama_keys and not args.no_probe_keys:
        print(f"Probing {len(ollama_keys)} Ollama key(s) for live quota...")
        live = probe_live_keys(ollama_keys, host=host)
        print(f"  live: {len(live)}/{len(ollama_keys)}")
        ollama_keys = live
    n_ollama_workers = (args.workers if args.workers else len(ollama_keys)) if ollama_keys else 0
    for i in range(n_ollama_workers):
        key = ollama_keys[i % len(ollama_keys)]
        clf = ClassifierDataGenerator(
            prompts_path=classifier_prompts, output_dir=out_dir,
            ollama_host=host, model=ollama_model, max_retries=max_retries,
            api_key=key,
        )
        agents.append(Agent(f"ollama#{i+1}", "ollama", ollama_gen(key), clf))

    # ── NVIDIA agents: N workers sharing ONE pooled account RPM limiter ─────
    if not args.no_nvidia:
        nvidia_keys = load_nvidia_keys()
        if nvidia_keys:
            ncfg = get_nvidia_config()
            print(f"NVIDIA: {ncfg['base_url']} / {args.nvidia_model}  "
                  f"({len(nvidia_keys)} key(s), pooled {ncfg['rpm']} RPM, "
                  f"{args.nvidia_workers} workers)")
            for j in range(args.nvidia_workers):
                key = nvidia_keys[j % len(nvidia_keys)]
                client = NvidiaClient(
                    base_url=ncfg["base_url"], model=args.nvidia_model,
                    api_key=key, rpm=ncfg["rpm"],
                )
                clf = ClassifierDataGenerator(
                    prompts_path=classifier_prompts, output_dir=out_dir,
                    ollama_host=host, model=args.nvidia_model,
                    max_retries=max_retries,
                    call_override=nvidia_classify_override(client),
                )
                agents.append(Agent(f"nvidia#{j+1}", "nvidia", nvidia_gen(client), clf))
        else:
            print("NVIDIA: no keys found in env — skipping NVIDIA backend")

    n_ollama = sum(1 for a in agents if a.kind == "ollama")
    n_nvidia = sum(1 for a in agents if a.kind == "nvidia")
    if not agents:
        print("❌ No live backends (no live Ollama keys, NVIDIA disabled/missing). Aborting.")
        sys.exit(1)

    print(f"\nKey sources: {describe_key_sources()}")
    print(f"Backends: {n_ollama} Ollama + {n_nvidia} NVIDIA = {len(agents)} workers  "
          f"|  oversample: {args.oversample}  |  strict: {not args.keep_mismatches}\n")

    # ── Build the attempt task queue ──────────────────────────────────────
    task_q: _queue.Queue = _queue.Queue()
    n_tasks = 0
    for cls, deficit in to_make.items():
        n_attempts = min(args.max_attempts_per_class,
                         int(math.ceil(deficit * args.oversample)))
        subs = prompts_classes[cls]["subtopics"]
        for i in range(n_attempts):
            task_q.put((cls, subs[i % len(subs)]))
            n_tasks += 1

    write_lock = threading.Lock()
    alive_lock = threading.Lock()
    stop_event = threading.Event()
    alive = {"ollama": n_ollama, "nvidia": n_nvidia, "total": len(agents)}
    kept_per_class = Counter()          # confirmed target matches written
    kept_mismatch = Counter()           # mismatches written (if --keep-mismatches)
    actual_label_dist = Counter()
    stats = {"gen_fail": 0, "clf_fail": 0, "dup": 0, "skipped": 0,
             "requeued": 0, "retired": 0}

    out_fh = open(output_path, "a", encoding="utf-8")
    pbar = tqdm(total=n_tasks, desc="Generate+verify", unit="try")

    def retire(agent, status):
        with alive_lock:
            if agent.dead:
                return
            agent.dead = True
            alive[agent.kind] -= 1
            alive["total"] -= 1
            stats["retired"] += 1
            tqdm.write(f"  ⚠️  retiring {agent.name} ({status}) — "
                       f"alive: {alive['ollama']} Ollama / {alive['nvidia']} NVIDIA")
            if alive["ollama"] == 0 and alive["nvidia"] > 0:
                tqdm.write("  ↪️  all Ollama keys exhausted — continuing on NVIDIA only.")
            if alive["total"] <= 0:
                stop_event.set()
                tqdm.write("  ⏸️  all backends dead — pausing. Re-run to resume "
                           "(staging file is preserved; nothing dropped).")

    def worker(agent):
        clf = agent.clf
        while not stop_event.is_set() and not agent.dead:
            try:
                cls, subtopic = task_q.get_nowait()
            except _queue.Empty:
                return
            requeued = False
            try:
                # Skip generation if this class is already filled (saves quota).
                with write_lock:
                    already_full = kept_per_class[cls] >= to_make[cls]
                if already_full:
                    with write_lock:
                        stats["skipped"] += 1
                    continue

                instruction = prompts_classes[cls]["instruction"]
                user_prompt = (
                    f"{instruction}\n\n"
                    f"Focus the passage on this specific topic: {subtopic}.\n\n"
                    f"Remember: describe it operationally/concretely, follow all hard "
                    f"rules, and output ONLY the passage."
                )
                raw, status = agent.gen(gen_system, user_prompt, args.temperature)

                # Quota/auth death → re-queue this attempt for another backend,
                # then retire this agent. Never drop the chunk.
                if status in (RATE, AUTH):
                    task_q.put((cls, subtopic))
                    with write_lock:
                        stats["requeued"] += 1
                    requeued = True
                    retire(agent, status)
                    return
                if status == TRANSPORT or not raw:
                    with write_lock:
                        stats["gen_fail"] += 1
                    continue

                text = clean_generated(raw)
                if "\n" in text:
                    text = text.replace("\n", " ").strip()
                if len(text.split()) < 40:
                    with write_lock:
                        stats["gen_fail"] += 1
                    continue
                result = clf.classify_one(text, str(cls).replace("_", " ").title())
                if not result:
                    with write_lock:
                        stats["clf_fail"] += 1
                    continue

                actual = result["label"]
                text = result["text"]
                h = _text_hash(text)
                with write_lock:
                    if h in done_hashes:
                        stats["dup"] += 1
                    elif actual == cls and kept_per_class[cls] < to_make[cls]:
                        done_hashes.add(h)
                        out_fh.write(json.dumps({"text": text, "label": actual},
                                                ensure_ascii=False) + "\n")
                        out_fh.flush()
                        kept_per_class[cls] += 1
                        actual_label_dist[actual] += 1
                    elif args.keep_mismatches and actual != cls:
                        done_hashes.add(h)
                        out_fh.write(json.dumps({"text": text, "label": actual},
                                                ensure_ascii=False) + "\n")
                        out_fh.flush()
                        kept_mismatch[actual] += 1
                        actual_label_dist[actual] += 1
            finally:
                if not requeued:
                    with write_lock:
                        pbar.set_postfix(kept=sum(kept_per_class.values()),
                                         miss=sum(kept_mismatch.values()),
                                         alive=alive["total"])
                        pbar.update(1)

    try:
        with ThreadPoolExecutor(max_workers=len(agents)) as pool:
            futures = [pool.submit(worker, a) for a in agents]
            for fut in futures:
                exc = fut.exception()
                if exc:
                    tqdm.write(f"  ⚠️  worker thread crashed: {str(exc)[:160]}")
    finally:
        pbar.close()
        out_fh.close()

    paused = stop_event.is_set()

    # ── Summary ───────────────────────────────────────────────────────────
    header = "TARGETED GENERATION PAUSED (all backends dead)" if paused \
        else "TARGETED GENERATION COMPLETE"
    print(f"\n{'=' * 74}\n{header}\n{'=' * 74}")
    print(f"  Gen failures: {stats['gen_fail']}  |  Classify failures: {stats['clf_fail']}"
          f"  |  Duplicates: {stats['dup']}")
    print(f"  Re-queued (key died): {stats['requeued']}  |  Backends retired: {stats['retired']}\n")
    if paused:
        print("  ⏸️  Quota exhausted on every backend. Nothing was dropped — re-run the\n"
              "      SAME command later to resume (staging file is the checkpoint).\n")
    print("  Kept (confirmed == target):")
    for cls in to_make:
        need = to_make[cls]
        got = kept_per_class.get(cls, 0)
        flag = "✅" if got >= need else "⚠️ "
        print(f"    {flag} {cls:22s}: {got}/{need}")
    if args.keep_mismatches and kept_mismatch:
        print("\n  Kept (mismatched, actual label):")
        for k, v in kept_mismatch.most_common():
            print(f"    {k:22s}: {v}")
    print(f"\n  Staging file: {output_path}")
    print(f"\n  Next: merge into the training file with")
    print(f"    python scripts/generate_targeted_synthetic_chunks.py \\")
    print(f"        --output {args.output} \\")
    print(f"        --merge-into data/agent_training/classifier_train_regenerated_cleaned.jsonl")


if __name__ == "__main__":
    main()
