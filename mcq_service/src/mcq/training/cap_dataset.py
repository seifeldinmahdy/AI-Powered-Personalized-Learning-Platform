"""Cap Type 4a samples with stratified balancing.

Reads the raw MCQ JSONL file, caps Type 4a at a configurable maximum using
stratified sampling across (mastery_level, score_category) combinations, and
writes the result to a new file.  All other question types are kept unchanged.

Usage::

    python -m mcq.training.cap_dataset \
        --input  data/mcq_training/mcq_raw.jsonl \
        --output data/mcq_training/mcq_raw_capped.jsonl \
        --cap 650
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

SEED = 42


def _load_jsonl(path: str) -> list[dict]:
    """Load all JSON objects from a JSONL file."""
    samples: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            samples.append(json.loads(line))
    return samples


def _stratified_cap(
    samples_4a: list[dict],
    cap: int,
    seed: int = SEED,
) -> list[dict]:
    """Cap Type 4a samples using stratified sampling.

    1. Group by (mastery_level, score_category).
    2. Allocate cap / n_groups per group.
    3. If a group has fewer, take all and redistribute remainder
       proportionally to the largest groups.
    4. Validate that no single group exceeds 40% of cap.
    """
    rng = random.Random(seed)

    # Group by (mastery_level, score_category)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for s in samples_4a:
        key = (s.get("mastery_level", "?"), s.get("score_category", "?"))
        groups[key].append(s)

    # Shuffle within each group for deterministic random sampling
    for key in groups:
        rng.shuffle(groups[key])

    n_groups = len(groups)
    if n_groups == 0:
        return []

    base_per_group = cap // n_groups
    logger.info(
        "stratified_cap_start",
        total_4a=len(samples_4a),
        cap=cap,
        n_groups=n_groups,
        base_per_group=base_per_group,
    )

    # First pass: take min(base_per_group, available) from each group
    selected: dict[tuple[str, str], list[dict]] = {}
    remainder = 0
    small_groups: set[tuple[str, str]] = set()
    large_groups: list[tuple[tuple[str, str], int]] = []

    for key, items in groups.items():
        take = min(base_per_group, len(items))
        selected[key] = items[:take]
        if len(items) < base_per_group:
            remainder += base_per_group - len(items)
            small_groups.add(key)
        else:
            leftover = len(items) - take
            large_groups.append((key, leftover))

    # Second pass: redistribute remainder proportionally to large groups
    if remainder > 0 and large_groups:
        total_leftover = sum(left for _, left in large_groups)
        for key, leftover in large_groups:
            if total_leftover == 0:
                break
            extra = int(round(remainder * leftover / total_leftover))
            extra = min(extra, leftover)
            already_taken = len(selected[key])
            selected[key] = groups[key][:already_taken + extra]

    # Trim to exactly `cap` if rounding pushed us over
    all_selected = []
    for key in sorted(selected):
        all_selected.extend(selected[key])

    if len(all_selected) > cap:
        rng.shuffle(all_selected)
        all_selected = all_selected[:cap]
    elif len(all_selected) < cap:
        # If we're still under cap, fill from the largest groups
        already_hashes = {s.get("_chunk_hash") for s in all_selected}
        deficit = cap - len(all_selected)
        for key, _ in sorted(large_groups, key=lambda x: -x[1]):
            for s in groups[key]:
                if s.get("_chunk_hash") not in already_hashes:
                    all_selected.append(s)
                    already_hashes.add(s.get("_chunk_hash"))
                    deficit -= 1
                    if deficit <= 0:
                        break
            if deficit <= 0:
                break

    # Validate 40% cap per combination
    combo_counts = Counter()
    for s in all_selected:
        combo_counts[(s.get("mastery_level", "?"), s.get("score_category", "?"))] += 1

    total_selected = len(all_selected)
    for combo, count in combo_counts.items():
        pct = count / max(total_selected, 1)
        if pct > 0.40:
            print(
                f"  ⚠ WARNING: Combination {combo} represents {100*pct:.1f}% "
                f"of capped 4a ({count}/{total_selected}) — exceeds 40% threshold."
            )

    return all_selected


def _print_distribution(label: str, samples: list[dict]):
    """Print per-type and per-(type, mastery, score_category) counts."""
    W = 66
    print(f"\n{'─' * W}")
    print(f"  {label}")
    print(f"{'─' * W}")

    type_counts: Counter = Counter()
    combo_counts: Counter = Counter()
    for s in samples:
        qt = s.get("question_type", "?")
        ml = s.get("mastery_level", "?")
        sc = s.get("score_category", "?")
        type_counts[qt] += 1
        combo_counts[(qt, ml, sc)] += 1

    total = len(samples)
    print(f"  Total samples: {total}\n")

    print("  PER-TYPE COUNTS:")
    for t in sorted(type_counts):
        c = type_counts[t]
        pct = 100 * c / max(total, 1)
        print(f"    Type {t:<4}: {c:>5}  ({pct:.1f}%)")

    print(f"\n  PER-(TYPE, MASTERY, SCORE_CATEGORY) COUNTS:")
    for (qt, ml, sc) in sorted(combo_counts):
        c = combo_counts[(qt, ml, sc)]
        print(f"    ({qt:<3}, {ml:<14}, {sc:<10}): {c:>5}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Cap Type 4a samples with stratified balancing.",
    )
    parser.add_argument(
        "--input", required=True,
        help="Input JSONL file (e.g. mcq_raw.jsonl).",
    )
    parser.add_argument(
        "--output", required=True,
        help="Output JSONL file with capped 4a samples.",
    )
    parser.add_argument(
        "--cap", type=int, default=650,
        help="Maximum number of Type 4a samples to keep (default: 650).",
    )
    args = parser.parse_args()

    # Load all samples
    all_samples = _load_jsonl(args.input)
    logger.info("loaded_samples", count=len(all_samples), file=args.input)

    # Separate 4a from everything else
    samples_4a = [s for s in all_samples if s.get("question_type") == "4a"]
    samples_other = [s for s in all_samples if s.get("question_type") != "4a"]

    print(f"\n  Input: {args.input}")
    print(f"  Total samples: {len(all_samples)}")
    print(f"  Type 4a samples: {len(samples_4a)}")
    print(f"  Other type samples: {len(samples_other)}")
    print(f"  Cap: {args.cap}")

    # Print BEFORE distribution
    _print_distribution("BEFORE CAPPING", all_samples)

    # Cap 4a
    if len(samples_4a) > args.cap:
        capped_4a = _stratified_cap(samples_4a, args.cap)
        print(f"\n  Capped Type 4a: {len(samples_4a)} → {len(capped_4a)}")
    else:
        capped_4a = samples_4a
        print(f"\n  Type 4a count ({len(samples_4a)}) already ≤ cap ({args.cap}). No capping needed.")

    # Combine and write
    final = samples_other + capped_4a

    # Print AFTER distribution
    _print_distribution("AFTER CAPPING", final)

    # Write output
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        for s in final:
            f.write(json.dumps(s) + "\n")

    print(f"  Written {len(final)} samples to {args.output}")
    print()


if __name__ == "__main__":
    main()
