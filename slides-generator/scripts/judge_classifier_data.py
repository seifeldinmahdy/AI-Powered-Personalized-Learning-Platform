#!/usr/bin/env python3
"""
Independent LLM-judge data-cleaning pass for the visual classifier dataset.

Why this exists (graduation-project methodology):
    The training labels are produced by a GENERATOR LLM (gpt-oss:120b). Using
    the same model to also validate them is circular. This script adds a SECOND,
    INDEPENDENT annotator — a DIFFERENT judge model (e.g. deepseek-v3.1) — that
    re-classifies every chunk *blind to the generator's label*, using the exact
    same taxonomy/prompt. We then:

      • measure inter-annotator agreement (raw % and Cohen's κ),
      • keep samples where generator and judge AGREE  → high-confidence "gold",
      • optionally ADJUDICATE disagreements with a THIRD model (2-of-3 majority),
      • discard items with no majority.

    This yields a cleaner, defensible training set plus an agreement report
    (κ, per-class agreement, generator-vs-judge confusion matrix) suitable for
    the thesis's data-quality section.

Independence is REQUIRED: --judge-model must differ from the model that produced
the labels. The judge reuses ClassifierDataGenerator.classify_one (same prompt),
so it is a genuine second annotator, not a "do you agree?" rubber stamp.

Usage:
    # Judge a dataset with deepseek as the independent annotator
    python scripts/judge_classifier_data.py \
        --input data/classifier_v2/final_balanced.jsonl \
        --output-dir data/classifier_v2 \
        --judge-model deepseek-v3.1:671b

    # Recover disagreements via a third adjudicator (2-of-3 majority)
    python scripts/judge_classifier_data.py \
        --input data/classifier_v2/final_balanced.jsonl \
        --output-dir data/classifier_v2 \
        --judge-model deepseek-v3.1:671b \
        --mode adjudicate --adjudicator-model qwen3.5:397b
"""

import argparse
import hashlib
import json
import os
import queue as _queue
import sys
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from slide_gen.training.classifier_data_generator import ClassifierDataGenerator  # noqa: E402
from slide_gen.data_engine.key_pool import (  # noqa: E402
    load_ollama_keys, describe_key_sources, probe_live_keys,
)
from slide_gen.core.hierarchy import get_category  # noqa: E402

try:
    from sklearn.metrics import cohen_kappa_score
    _HAVE_SKLEARN = True
except ImportError:
    _HAVE_SKLEARN = False


def _text_hash(text: str) -> str:
    return hashlib.md5(text.strip().encode("utf-8")).hexdigest()[:12]


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float:
    """Cohen's κ between two annotators (manual fallback if sklearn absent)."""
    if _HAVE_SKLEARN:
        try:
            return float(cohen_kappa_score(labels_a, labels_b))
        except Exception:
            pass
    n = len(labels_a)
    if n == 0:
        return 0.0
    cats = sorted(set(labels_a) | set(labels_b))
    po = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / n
    ca = Counter(labels_a)
    cb = Counter(labels_b)
    pe = sum((ca.get(c, 0) / n) * (cb.get(c, 0) / n) for c in cats)
    return (po - pe) / (1 - pe) if (1 - pe) > 1e-9 else 1.0


def make_generators(model: str, n: int, api_keys, prompts_path, out_dir, max_retries):
    """One ClassifierDataGenerator per worker, each pinned to a distinct key."""
    return [
        ClassifierDataGenerator(
            prompts_path=prompts_path, output_dir=out_dir,
            ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            model=model, max_retries=max_retries,
            api_key=api_keys[i % len(api_keys)],
        )
        for i in range(n)
    ]


def main():
    p = argparse.ArgumentParser(description="Independent LLM-judge cleaning pass")
    p.add_argument("--input", required=True, help="Input classifier JSONL ({text,label})")
    p.add_argument("--output-dir", default="data/classifier_v2",
                   help="Directory for verified/discarded/report outputs")
    # Defaults are FREE-PLAN Ollama Cloud models (verified accessible without a
    # subscription). Three distinct families give a meaningful independent signal:
    #   generator = gpt-oss, judge = gemma (Google), adjudicator = nemotron (NVIDIA).
    # glm-4.7 is strong but a slow reasoning model (times out under bulk load);
    # deepseek/qwen big models are subscription-only — do NOT use on the free plan.
    p.add_argument("--judge-model", default="gemma3:27b",
                   help="Independent judge model, free-plan (MUST differ from the generator)")
    p.add_argument("--gen-model", default=None,
                   help="Name of the model that produced the labels (for the report only)")
    p.add_argument("--mode", choices=["agreement", "adjudicate"], default="adjudicate",
                   help="agreement = keep only gen==judge; adjudicate = 2-of-3 majority on disagreement")
    p.add_argument("--adjudicator-model", default="nemotron-3-nano:30b",
                   help="Third model (free-plan, third family) to break disagreements")
    p.add_argument("--no-probe-keys", action="store_true",
                   help="Skip the startup key-health probe (faster, but dead keys corrupt κ)")
    p.add_argument("--prompts", default="config/prompts_classifier.yaml")
    p.add_argument("--workers", type=int, default=None,
                   help="Parallel workers (default: one per API key)")
    p.add_argument("--max-keys", type=int, default=None)
    p.add_argument("--limit", type=int, default=None, help="Judge only first N rows (testing)")
    args = p.parse_args()

    load_dotenv(project_root / ".env")
    gen_model = args.gen_model or os.getenv("OLLAMA_MODEL", "gpt-oss:120b")

    if args.judge_model == gen_model:
        print(f"❌ --judge-model ({args.judge_model}) must DIFFER from the generator "
              f"model ({gen_model}) for an independent agreement measurement.")
        sys.exit(1)

    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = project_root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    prompts_path = Path(args.prompts)
    if not prompts_path.is_absolute():
        prompts_path = project_root / prompts_path

    in_path = Path(args.input)
    if not in_path.is_absolute():
        in_path = project_root / in_path
    rows = load_jsonl(in_path)
    if args.limit:
        rows = rows[: args.limit]

    stem = in_path.stem
    verified_path = out_dir / f"{stem}_verified.jsonl"
    discarded_path = out_dir / f"{stem}_discarded.jsonl"
    report_path = out_dir / f"{stem}_judge_report.md"

    # ── Resume: skip rows already judged ──────────────────────────────────
    done_hashes = set()
    for pth in (verified_path, discarded_path):
        if pth.exists():
            for r in load_jsonl(pth):
                if r.get("text"):
                    done_hashes.add(_text_hash(r["text"]))
    pending = [r for r in rows if _text_hash(r.get("text", "")) not in done_hashes]

    api_keys = load_ollama_keys(max_keys=args.max_keys) or [None]
    if not args.no_probe_keys and api_keys[0] is not None:
        print(f"Probing {len(api_keys)} keys for free-plan weekly quota...")
        live = probe_live_keys(api_keys)
        dead = len(api_keys) - len(live)
        if live:
            print(f"  → {len(live)} live, {dead} exhausted/forbidden (dropped)")
            api_keys = live
        else:
            print("  ⚠️  No live keys detected — proceeding with all (may all fail).")
    n_workers = args.workers if args.workers else len(api_keys)
    max_retries = int(os.getenv("MAX_RETRIES", "3"))

    print("=" * 72)
    print("INDEPENDENT LLM-JUDGE DATA CLEANING")
    print("=" * 72)
    print(f"Input:           {in_path}  ({len(rows)} rows)")
    print(f"Generator model: {gen_model}  (produced the labels)")
    print(f"Judge model:     {args.judge_model}  (independent annotator)")
    print(f"Mode:            {args.mode}"
          + (f"  | adjudicator: {args.adjudicator_model}" if args.mode == "adjudicate" else ""))
    print(f"Key sources:     {describe_key_sources()}")
    print(f"Workers:         {n_workers} (one per key)")
    print(f"Already judged:  {len(done_hashes)}  |  To judge: {len(pending)}")
    print(f"Outputs:         {verified_path.name}, {discarded_path.name}, {report_path.name}\n")

    if not pending:
        print("✅ Nothing to judge — all rows already processed.")
        return

    judges = make_generators(args.judge_model, n_workers, api_keys, prompts_path, out_dir, max_retries)
    adjudicators = (
        make_generators(args.adjudicator_model, n_workers, api_keys, prompts_path, out_dir, max_retries)
        if args.mode == "adjudicate" else None
    )

    write_lock = threading.Lock()
    vf = open(verified_path, "a", encoding="utf-8")
    df = open(discarded_path, "a", encoding="utf-8")

    # Pair tracking for κ (only rows where both gen+judge produced a label)
    gen_labels: list[str] = []
    judge_labels: list[str] = []
    per_class_agree = defaultdict(lambda: [0, 0])  # gen_label → [agree, total]
    stats = Counter()  # keys: agree, relabeled, discarded, judge_fail

    task_q: _queue.Queue = _queue.Queue()
    for r in pending:
        task_q.put(r)
    pbar = tqdm(total=len(pending), desc="Judging", unit="row")

    def worker(wid: int):
        judge = judges[wid]
        adj = adjudicators[wid] if adjudicators else None
        while True:
            try:
                row = task_q.get_nowait()
            except _queue.Empty:
                return
            text = row.get("text", "")
            gen_label = row.get("label", "none")
            try:
                jres = judge.classify_one(text)
                judge_label = jres["label"] if jres else None
            except Exception:
                judge_label = None

            final_label = None
            kind = None
            if judge_label is None:
                kind = "judge_fail"  # keep generator label, flag as unjudged
                final_label = gen_label
            elif judge_label == gen_label:
                kind = "agree"
                final_label = gen_label
            else:
                # Disagreement
                if adj is not None:
                    try:
                        ares = adj.classify_one(text)
                        adj_label = ares["label"] if ares else None
                    except Exception:
                        adj_label = None
                    votes = Counter([gen_label, judge_label] + ([adj_label] if adj_label else []))
                    top_label, top_n = votes.most_common(1)[0]
                    if top_n >= 2:
                        kind = "relabeled" if top_label != gen_label else "agree"
                        final_label = top_label
                    else:
                        kind = "discarded"
                else:
                    kind = "discarded"

            with write_lock:
                if judge_label is not None:
                    gen_labels.append(gen_label)
                    judge_labels.append(judge_label)
                    per_class_agree[gen_label][1] += 1
                    if judge_label == gen_label:
                        per_class_agree[gen_label][0] += 1
                stats[kind] += 1
                rec = {"text": text, "label": final_label} if final_label else {"text": text, "label": gen_label}
                if kind == "discarded":
                    df.write(json.dumps({"text": text, "gen_label": gen_label,
                                         "judge_label": judge_label}, ensure_ascii=False) + "\n")
                    df.flush()
                else:
                    vf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    vf.flush()
                pbar.set_postfix(agree=stats["agree"], relabel=stats["relabeled"],
                                 disc=stats["discarded"])
                pbar.update(1)

    try:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futs = [pool.submit(worker, i) for i in range(n_workers)]
            for f in futs:
                exc = f.exception()
                if exc:
                    tqdm.write(f"  ⚠️  worker crashed: {str(exc)[:160]}")
    finally:
        pbar.close()
        vf.close()
        df.close()

    # ── Agreement metrics (this run's judged pairs) ───────────────────────
    kappa = cohen_kappa(gen_labels, judge_labels) if gen_labels else 0.0
    raw_agree = (sum(1 for a, b in zip(gen_labels, judge_labels) if a == b) / len(gen_labels)
                 if gen_labels else 0.0)
    # Category-level agreement (L1) — usually higher than template-level
    cat_agree = (sum(1 for a, b in zip(gen_labels, judge_labels)
                     if get_category(a) == get_category(b)) / len(gen_labels)
                 if gen_labels else 0.0)

    print(f"\n{'=' * 72}\nJUDGE REPORT (this run)\n{'=' * 72}")
    print(f"  Judged pairs:        {len(gen_labels)}")
    print(f"  Raw agreement:       {raw_agree:.3f}")
    print(f"  Category agreement:  {cat_agree:.3f}")
    print(f"  Cohen's κ:           {kappa:.3f}")
    print(f"  Agree:     {stats['agree']}")
    print(f"  Relabeled: {stats['relabeled']}  (majority overruled the generator)")
    print(f"  Discarded: {stats['discarded']}")
    print(f"  Judge fail:{stats['judge_fail']}  (kept generator label, flagged)")

    # ── Write markdown report ─────────────────────────────────────────────
    with open(report_path, "w", encoding="utf-8") as rf:
        rf.write(f"# Visual-Classifier Data Judge Report\n\n")
        rf.write(f"- **Input:** `{in_path.name}` ({len(rows)} rows; {len(pending)} judged this run)\n")
        rf.write(f"- **Generator (labeler):** `{gen_model}`\n")
        rf.write(f"- **Judge (independent annotator):** `{args.judge_model}`\n")
        rf.write(f"- **Mode:** `{args.mode}`"
                 + (f" (adjudicator: `{args.adjudicator_model}`)\n" if args.mode == "adjudicate" else "\n"))
        rf.write(f"\n## Inter-annotator agreement (generator vs judge)\n\n")
        rf.write(f"| Metric | Value |\n|---|---|\n")
        rf.write(f"| Judged pairs | {len(gen_labels)} |\n")
        rf.write(f"| Raw template agreement | {raw_agree:.3f} |\n")
        rf.write(f"| Category (L1) agreement | {cat_agree:.3f} |\n")
        rf.write(f"| Cohen's κ | {kappa:.3f} |\n")
        rf.write(f"\n## Outcome\n\n")
        rf.write(f"| Outcome | Count |\n|---|---|\n")
        rf.write(f"| Agree (kept) | {stats['agree']} |\n")
        rf.write(f"| Relabeled (majority) | {stats['relabeled']} |\n")
        rf.write(f"| Discarded (no majority) | {stats['discarded']} |\n")
        rf.write(f"| Judge failed (kept gen label) | {stats['judge_fail']} |\n")
        rf.write(f"\n## Per-class agreement (generator label → judge agreed)\n\n")
        rf.write(f"| Generator label | Agreement | n |\n|---|---|---|\n")
        for lbl in sorted(per_class_agree, key=lambda k: -per_class_agree[k][1]):
            ag, tot = per_class_agree[lbl]
            rf.write(f"| {lbl} | {ag/tot:.3f} | {tot} |\n")

    print(f"\n  📄 Report: {report_path}")
    print(f"  ✅ Verified set: {verified_path}")
    print(f"  🗑️  Discarded:    {discarded_path}")
    print(f"\n  Train on the verified set:")
    print(f"    {verified_path}")


if __name__ == "__main__":
    main()
