#!/usr/bin/env python3
"""
relabel_layered_stack.py — Deterministic relabeling of layered_stack → architecture_diagram.

This is a one-shot, non-LLM migration script. Every sample with label
"layered_stack" in the input JSONL is unconditionally relabeled to
"architecture_diagram". No LLM calls are made; this is deterministic.

Usage:
    python scripts/relabel_layered_stack.py
    python scripts/relabel_layered_stack.py --input data/agent_training/classifier_train_v3_cleaned.jsonl
    python scripts/relabel_layered_stack.py --input <path> --output <path>
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def relabel(input_path: Path, output_path: Path) -> None:
    # Load
    samples = []
    with open(input_path) as f:
        for line in f:
            line = line.strip()
            if line:
                samples.append(json.loads(line))

    before = Counter(s["label"] for s in samples)
    n_layered = before.get("layered_stack", 0)

    print(f"  Input:           {input_path}")
    print(f"  Output:          {output_path}")
    print(f"  Total samples:   {len(samples)}")
    print(f"  layered_stack:   {n_layered} → will be relabeled to architecture_diagram")

    if n_layered == 0:
        print("\n  ✅ No layered_stack samples found — nothing to do.")
        if input_path != output_path:
            import shutil
            shutil.copy(input_path, output_path)
        return

    # Relabel
    migrated = 0
    for s in samples:
        if s["label"] == "layered_stack":
            s["label"] = "architecture_diagram"
            migrated += 1

    # Write
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for s in samples:
            f.write(json.dumps(s) + "\n")

    after = Counter(s["label"] for s in samples)

    print(f"\n  Migrated:        {migrated} samples")
    print(f"\n  Label Distribution (after):")
    for label, count in after.most_common():
        delta = count - before.get(label, 0)
        delta_str = f"  (+{delta})" if delta > 0 else ""
        print(f"    {label:25s}: {count}{delta_str}")

    print(f"\n  ✅ Done. Output written to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Deterministically relabel layered_stack → architecture_diagram"
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        default=None,
        help="Input JSONL path (default: data/agent_training/classifier_train_v3_cleaned.jsonl)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output JSONL path (default: same as input, overwrite in-place)",
    )
    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    default_input = project_root / "data" / "agent_training" / "classifier_train_v3_cleaned.jsonl"

    input_path = Path(args.input) if args.input else default_input
    output_path = Path(args.output) if args.output else input_path

    if not input_path.exists():
        print(f"❌ Error: Input file not found: {input_path}")
        sys.exit(1)

    print("=" * 60)
    print("LAYERED_STACK → ARCHITECTURE_DIAGRAM RELABELER")
    print("=" * 60)
    relabel(input_path, output_path)


if __name__ == "__main__":
    main()
