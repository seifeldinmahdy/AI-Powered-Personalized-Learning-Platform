#!/usr/bin/env python3
"""
Reclassify Existing Classifier Data — Migrate labels to the updated hierarchy.

Reads an existing classifier_train.jsonl and selectively reclassifies samples
whose labels have changed under the new hierarchy.

Two modes:
  Default: Reclassifies grid, binary_tree, concept_box samples.
  --targeted: Reclassifies pie_chart, comparison, concept_box samples against
              the latest hierarchy (venn_diagram, analogy_diagram additions).

Outputs:
  1. classifier_train_reclassified.jsonl (or _final.jsonl in targeted mode)
  2. reclassification_report.json (or targeted_reclassification_report.json)

Supports checkpoint/resume: if interrupted, rerun to continue where it left off.

Usage:
    python scripts/reclassify_existing_data.py
    python scripts/reclassify_existing_data.py --input data/agent_training/classifier_train.jsonl
    python scripts/reclassify_existing_data.py --input <path> --output <path>
    python scripts/reclassify_existing_data.py --targeted
"""

import argparse
import json
import os
import signal
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

import requests
import yaml

from slide_gen.core.hierarchy import ALL_TEMPLATE_IDS
from slide_gen.data_engine.utils import extract_json_from_response


# =========================================================================
# CONSTANTS
# =========================================================================

# Default mode: Labels that require LLM reclassification
# layered_stack is added here because it was merged into architecture_diagram
LABELS_REQUIRING_LLM = {"grid", "binary_tree", "concept_box", "layered_stack"}

# Default mode: Labels that are kept as-is (valid in new hierarchy and unchanged)
LABELS_KEEP_AS_IS = {
    "linear_chain", "stack", "queue", "graph",
    "flowchart", "cycle", "comparison",
    "bar_chart", "none",
    "architecture_diagram",
}

# Targeted mode: Labels that need rechecking for architecture_diagram + cleanup
TARGETED_LABELS_REQUIRING_LLM = {"concept_box", "comparison", "analogy_diagram", "venn_diagram"}


# =========================================================================
# LLM RECLASSIFIER
# =========================================================================

class Reclassifier:
    """
    Reclassifies existing training samples against the updated hierarchy
    using the same Ollama calling pattern as ClassifierDataGenerator.
    """

    def __init__(
        self,
        prompts_path: Path,
        ollama_host: str,
        model: str,
        max_retries: int = 3,
        api_key: str | None = None,
    ):
        # Load the updated prompts (architecture_diagram covers all architectural templates)
        with open(prompts_path, "r") as f:
            prompts = yaml.safe_load(f)

        self.system_prompt = prompts["classifier_system_prompt"]
        self.user_template = prompts["classifier_user_template"]
        self.ollama_host = ollama_host.rstrip("/")
        self.model = model
        self.max_retries = max_retries
        self.api_key = api_key

    def _call_ollama(self, prompt: str) -> str | None:
        """
        Call Ollama API and return raw response text.

        Mirrors ClassifierDataGenerator._call_ollama exactly:
        uses /api/generate, system prompt, stream=False.
        """
        url = f"{self.ollama_host}/api/generate"

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": self.system_prompt,
            "stream": False,
            "options": {
                "temperature": 0.3,   # Lower temp for more deterministic reclassification
                "top_p": 0.9,
            },
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=120)
            response.raise_for_status()
            result = response.json()
            return result.get("response", "")
        except requests.RequestException as e:
            return None

    def reclassify(self, text: str, original_label: str) -> tuple[str | None, str]:
        """
        Reclassify a single sample using the LLM with retry logic.

        Returns:
            (new_label or None, status) where status is one of:
            "confirmed", "updated", "invalid_response", "failed"
        """
        # Build the prompt using the same template as ClassifierDataGenerator
        title = text.split(".")[0][:80] if "." in text else text[:80]
        prompt = self.user_template.format(
            bullets_text=text,
            title=title,
        )

        for attempt in range(self.max_retries):
            response_text = self._call_ollama(prompt)
            if not response_text:
                continue

            parsed = extract_json_from_response(response_text)
            if not parsed:
                continue

            template_id = parsed.get("template_id", "").strip().lower()
            if not template_id:
                continue

            # Validate the LLM returned a template that exists in the new hierarchy
            if template_id not in ALL_TEMPLATE_IDS:
                return None, "invalid_response"

            # Compare with original
            if template_id == original_label:
                return template_id, "confirmed"
            else:
                return template_id, "updated"

        # All retries exhausted
        return None, "failed"


# =========================================================================
# CHECKPOINT MANAGEMENT
# =========================================================================

def load_checkpoint(checkpoint_path: Path) -> dict:
    """Load checkpoint from disk, or return defaults."""
    if checkpoint_path.exists():
        return json.loads(checkpoint_path.read_text())
    return {"last_processed_line": -1}


def save_checkpoint(checkpoint_path: Path, last_processed_line: int):
    """Save progress checkpoint."""
    checkpoint_path.write_text(json.dumps({"last_processed_line": last_processed_line}))


# =========================================================================
# MAIN RECLASSIFICATION PIPELINE
# =========================================================================

def run_reclassification(
    input_path: Path,
    output_path: Path,
    report_path: Path,
    reclassifier: Reclassifier,
    labels_requiring_llm: set[str] | None = None,
):
    """
    Run the full reclassification pipeline with resumability.

    Args:
        input_path: Path to input JSONL
        output_path: Path to output JSONL
        report_path: Path to report JSON
        reclassifier: Reclassifier instance
        labels_requiring_llm: Set of labels to reclassify via LLM.
                              If None, uses the default LABELS_REQUIRING_LLM.
    """
    if labels_requiring_llm is None:
        labels_requiring_llm = LABELS_REQUIRING_LLM

    checkpoint_path = output_path.parent / f".{output_path.name}.checkpoint.json"

    # ── Load all samples ──
    samples = []
    with open(input_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))

    total = len(samples)
    print(f"\n📊 Loaded {total} samples from {input_path}")

    # ── Label distribution (before) ──
    before_dist = Counter(s["label"] for s in samples)
    needs_llm = sum(before_dist.get(l, 0) for l in labels_requiring_llm)
    skipped = total - needs_llm
    print(f"   Samples needing LLM reclassification: {needs_llm}")
    print(f"   Samples kept as-is (no LLM call):     {skipped}")

    for label in sorted(labels_requiring_llm):
        count = before_dist.get(label, 0)
        if count > 0:
            print(f"     → {label}: {count} samples")

    # ── Resume logic ──
    checkpoint = load_checkpoint(checkpoint_path)
    start_idx = checkpoint["last_processed_line"] + 1

    # Load already-processed results from output file
    results: list[dict] = []
    if start_idx > 0 and output_path.exists():
        with open(output_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    results.append(json.loads(line))

        # Trim to exactly start_idx results (in case of partial writes)
        results = results[:start_idx]

        print(f"\n♻️  RESUMING from checkpoint:")
        print(f"   Sample {start_idx + 1}/{total}")
        print(f"   Already processed: {start_idx}")
    else:
        start_idx = 0
        results = []

    # ── Tracking stats ──
    confirmed = 0
    updated = 0
    failed = 0
    invalid = 0
    transition_map: dict[str, Counter] = defaultdict(Counter)
    updated_samples_preview: list[dict] = []  # First 10 updated samples

    # Count stats from already-processed results
    for i, res in enumerate(results):
        orig = samples[i]["label"]
        new = res["label"]
        if orig not in labels_requiring_llm:
            confirmed += 1
        elif orig == new:
            confirmed += 1
        else:
            updated += 1
            transition_map[orig][new] += 1

    # ── Graceful shutdown ──
    shutdown_requested = False

    def handle_signal(signum, frame):
        nonlocal shutdown_requested
        if shutdown_requested:
            print("\n\n⚠️  Force exit (checkpoint already saved)")
            sys.exit(1)
        shutdown_requested = True
        print("\n\n⏸️  Graceful shutdown — saving checkpoint...")

    original_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, handle_signal)

    # ── Main loop ──
    try:
        with tqdm(total=total, initial=start_idx,
                  desc="Reclassifying") as pbar:
            for idx in range(start_idx, total):
                if shutdown_requested:
                    # Flush results up to current point
                    _write_results(output_path, results)
                    save_checkpoint(checkpoint_path, idx - 1)
                    print(f"   ✅ Checkpoint saved at sample {idx}")
                    print(f"   Run the same command to resume.\n")
                    break

                sample = samples[idx]
                text = sample["text"]
                original_label = sample["label"]

                # ── Decision tree ──
                if original_label not in labels_requiring_llm:
                    # Keep as-is: not in the targeted set
                    results.append({"text": text, "label": original_label})
                    confirmed += 1
                else:
                    # Needs LLM reclassification
                    new_label, status = reclassifier.reclassify(text, original_label)

                    if status == "confirmed":
                        results.append({"text": text, "label": original_label})
                        confirmed += 1
                    elif status == "updated":
                        results.append({"text": text, "label": new_label})
                        updated += 1
                        transition_map[original_label][new_label] += 1
                        if len(updated_samples_preview) < 10:
                            updated_samples_preview.append({
                                "original_label": original_label,
                                "new_label": new_label,
                                "text_preview": text[:100],
                            })
                    elif status == "invalid_response":
                        # LLM returned a label not in hierarchy — keep original if it's still valid
                        # For removed labels, fall back to concept_box
                        if original_label in ALL_TEMPLATE_IDS:
                            results.append({"text": text, "label": original_label})
                        else:
                            results.append({"text": text, "label": "concept_box"})
                        invalid += 1
                    else:  # failed
                        # Keep original if valid, else concept_box
                        if original_label in ALL_TEMPLATE_IDS:
                            results.append({"text": text, "label": original_label})
                        else:
                            results.append({"text": text, "label": "concept_box"})
                        failed += 1

                # Save checkpoint every 10 samples
                if (idx + 1) % 10 == 0:
                    _write_results(output_path, results)
                    save_checkpoint(checkpoint_path, idx)

                pbar.set_postfix({
                    "confirmed": confirmed,
                    "updated": updated,
                    "failed": failed,
                })
                pbar.update(1)

    except Exception as e:
        _write_results(output_path, results)
        save_checkpoint(checkpoint_path, len(results) - 1)
        print(f"\n\n❌ Error: {e}")
        print(f"   ✅ Checkpoint saved — run again to resume.")
    finally:
        signal.signal(signal.SIGINT, original_sigint)

    # ── Final write ──
    _write_results(output_path, results)

    # ── Clear checkpoint if complete ──
    if not shutdown_requested and len(results) == total:
        if checkpoint_path.exists():
            checkpoint_path.unlink()
        print("\n🎉 Reclassification complete — checkpoint cleared.")

    # ── Write report ──
    after_dist = Counter(r["label"] for r in results)

    # Build transition breakdown
    transitions_summary = {}
    for old_label, new_counter in sorted(transition_map.items()):
        for new_label, count in new_counter.most_common():
            key = f"{old_label} → {new_label}"
            transitions_summary[key] = count

    report = {
        "total_samples": total,
        "kept_unchanged": confirmed,
        "updated": updated,
        "llm_failures": failed,
        "invalid_llm_responses": invalid,
        "label_distribution_before": dict(before_dist.most_common()),
        "label_distribution_after": dict(after_dist.most_common()),
        "transitions": transitions_summary,
        "updated_samples_preview": updated_samples_preview,
    }

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    # ── Print summary ──
    _print_summary(report)


def _write_results(output_path: Path, results: list[dict]):
    """Atomically write all results to the output file."""
    with open(output_path, "w") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")


def _print_summary(report: dict):
    """Print a human-readable summary."""
    print(f"\n{'=' * 70}")
    print("📊 RECLASSIFICATION REPORT")
    print(f"{'=' * 70}")

    print(f"\n📋 Overview:")
    print(f"   Total samples:        {report['total_samples']}")
    print(f"   Kept unchanged:       {report['kept_unchanged']}")
    print(f"   Updated:              {report['updated']}")
    print(f"   LLM failures:         {report['llm_failures']}")
    print(f"   Invalid LLM responses: {report['invalid_llm_responses']}")

    if report["transitions"]:
        print(f"\n🔀 Label Transitions:")
        for transition, count in sorted(report["transitions"].items(), key=lambda x: -x[1]):
            print(f"   {transition}: {count} samples")

    before = report["label_distribution_before"]
    after = report["label_distribution_after"]

    print(f"\n📊 Label Distribution (Before → After):")
    all_labels = sorted(set(list(before.keys()) + list(after.keys())))
    for label in all_labels:
        b = before.get(label, 0)
        a = after.get(label, 0)
        delta = a - b
        delta_str = f"+{delta}" if delta > 0 else str(delta) if delta != 0 else "="
        print(f"   {label:20s}: {b:4d} → {a:4d}  ({delta_str})")

    if report["updated_samples_preview"]:
        print(f"\n🔍 Updated Samples Preview (first {len(report['updated_samples_preview'])}):")
        for i, sp in enumerate(report["updated_samples_preview"]):
            print(f"   {i+1}. [{sp['original_label']}] → [{sp['new_label']}]")
            print(f"      \"{sp['text_preview']}...\"")

    print(f"\n{'=' * 70}")


# =========================================================================
# CLI ENTRY POINT
# =========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Reclassify existing classifier training data against updated hierarchy"
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        default=None,
        help="Path to existing classifier_train.jsonl (default: data/agent_training/classifier_train.jsonl)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Path for reclassified output (default: <input_dir>/classifier_train_reclassified.jsonl)",
    )
    parser.add_argument(
        "--report", "-r",
        type=str,
        default=None,
        help="Path for report JSON (default: <output_dir>/reclassification_report.json)",
    )
    parser.add_argument(
        "--targeted",
        action="store_true",
        help=(
            "Targeted reclassification: reads classifier_train_reclassified.jsonl and rechecks "
            "pie_chart (removed), comparison (venn_diagram now available), and concept_box "
            "(analogy_diagram now available). Writes to classifier_train_final.jsonl."
        ),
    )
    args = parser.parse_args()

    load_dotenv(project_root / ".env")

    # Resolve Ollama config
    ollama_host = os.getenv("OLLAMA_HOST")
    ollama_model = os.getenv("OLLAMA_MODEL", "llama3")
    max_retries = int(os.getenv("MAX_RETRIES", "3"))
    api_key = os.getenv("OLLAMA_API_KEY")

    prompts_path = project_root / "config" / "prompts_classifier.yaml"

    if args.targeted:
        # ── Targeted mode ──
        input_path = (
            Path(args.input) if args.input
            else project_root / "data" / "agent_training" / "classifier_train_reclassified.jsonl"
        )
        output_dir = input_path.parent
        output_path = (
            Path(args.output) if args.output
            else output_dir / "classifier_train_v3.jsonl"
        )
        report_path = (
            Path(args.report) if args.report
            else output_dir / "targeted_reclassification_report.json"
        )
        labels_to_reclassify = TARGETED_LABELS_REQUIRING_LLM

        print("=" * 70)
        print("TARGETED RECLASSIFICATION (architecture_diagram + hierarchy cleanup)")
        print("=" * 70)
    else:
        # ── Default mode ──
        input_path = (
            Path(args.input) if args.input
            else project_root / "data" / "agent_training" / "classifier_train.jsonl"
        )
        output_dir = input_path.parent
        output_path = (
            Path(args.output) if args.output
            else output_dir / "classifier_train_reclassified.jsonl"
        )
        report_path = (
            Path(args.report) if args.report
            else output_dir / "reclassification_report.json"
        )
        labels_to_reclassify = LABELS_REQUIRING_LLM

        print("=" * 70)
        print("CLASSIFIER DATA RECLASSIFIER (Hierarchy Migration)")
        print("=" * 70)

    if not input_path.exists():
        print(f"❌ Error: Input file not found: {input_path}")
        sys.exit(1)

    print(f"\nOllama:  {ollama_host} / {ollama_model}")
    print(f"Cloud API: {'Yes (API key set)' if api_key else 'No (local)'}")
    print(f"Max retries: {max_retries}")
    print(f"\nInput:   {input_path}")
    print(f"Output:  {output_path}")
    print(f"Report:  {report_path}")
    print(f"Labels to reclassify: {sorted(labels_to_reclassify)}")

    reclassifier = Reclassifier(
        prompts_path=prompts_path,
        ollama_host=ollama_host,
        model=ollama_model,
        max_retries=max_retries,
        api_key=api_key,
    )

    run_reclassification(
        input_path=input_path,
        output_path=output_path,
        report_path=report_path,
        reclassifier=reclassifier,
        labels_requiring_llm=labels_to_reclassify,
    )

    print(f"\n✅ Done!")
    print(f"   Output:  {output_path}")
    print(f"   Report:  {report_path}")


if __name__ == "__main__":
    main()
