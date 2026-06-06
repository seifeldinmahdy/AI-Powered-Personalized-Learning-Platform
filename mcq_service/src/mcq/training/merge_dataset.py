"""Merge capped main dataset with boost files and validate final distribution.

Reads the capped main dataset and boost files for underrepresented types,
concatenates them, shuffles with a fixed seed, runs a three-level distribution
report, and validates bounds.

Usage::

    python -m mcq.training.merge_dataset \
        --main  data/mcq_training/mcq_raw_capped.jsonl \
        --boost data/mcq_training/mcq_4c_boost.jsonl \
                data/mcq_training/mcq_4d_boost.jsonl \
                data/mcq_training/mcq_4e_boost.jsonl \
        --output data/mcq_training/mcq_final.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

SEED = 42
MIN_PER_TYPE = 150
MAX_PER_TYPE = 900
MAX_COMBO_PCT = 0.40  # no (mastery, score_cat) combo > 40% within a type


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


def _three_level_report(samples: list[dict]):
    """Print a comprehensive three-level distribution report."""
    W = 66
    total = len(samples)

    type_counts: Counter = Counter()
    mastery_counts: Counter = Counter()
    combo_counts: Counter = Counter()

    for s in samples:
        qt = s.get("question_type", "?")
        ml = s.get("mastery_level", "?")
        sc = s.get("score_category", "?")
        type_counts[qt] += 1
        mastery_counts[ml] += 1
        combo_counts[(qt, ml, sc)] += 1

    # ── Level 1: Per question type ─────────────────────────────────────
    print(f"\n{'═' * W}")
    print("  LEVEL 1 — QUESTION TYPE DISTRIBUTION")
    print(f"{'═' * W}")
    for t in sorted(type_counts):
        c = type_counts[t]
        pct = 100 * c / max(total, 1)
        bar = "█" * int(40 * c / max(total, 1))
        print(f"    Type {t:<4}: {c:>5}  ({pct:5.1f}%)  {bar}")

    # ── Level 2: Per mastery level ─────────────────────────────────────
    print(f"\n{'═' * W}")
    print("  LEVEL 2 — MASTERY LEVEL DISTRIBUTION")
    print(f"{'═' * W}")
    for m in sorted(mastery_counts):
        c = mastery_counts[m]
        pct = 100 * c / max(total, 1)
        bar = "█" * int(40 * c / max(total, 1))
        print(f"    {m:<14}: {c:>5}  ({pct:5.1f}%)  {bar}")

    # ── Level 3: Per (type, mastery, score_category) combination ──────
    print(f"\n{'═' * W}")
    print("  LEVEL 3 — PER-(TYPE, MASTERY, SCORE_CATEGORY) COMBINATION")
    print(f"{'═' * W}")
    # Group by type for readability
    types_seen = sorted(set(qt for (qt, _, _) in combo_counts))
    for qt in types_seen:
        type_total = type_counts[qt]
        print(f"\n    Type {qt} ({type_total} total):")
        type_combos = {
            (ml, sc): c
            for (q, ml, sc), c in combo_counts.items()
            if q == qt
        }
        for (ml, sc) in sorted(type_combos):
            c = type_combos[(ml, sc)]
            pct = 100 * c / max(type_total, 1)
            print(f"      ({ml:<14}, {sc:<10}): {c:>5}  ({pct:5.1f}%)")

    print()
    return type_counts, mastery_counts, combo_counts


def _validate_bounds(
    type_counts: Counter,
    combo_counts: Counter,
):
    """Validate type bounds and combination dominance."""
    W = 66
    print(f"{'═' * W}")
    print("  VALIDATION")
    print(f"{'═' * W}")

    any_error = False

    # Check per-type bounds
    for t in sorted(type_counts):
        c = type_counts[t]
        if c < MIN_PER_TYPE:
            print(f"  ❌ ERROR: Type {t} has {c} samples — below minimum {MIN_PER_TYPE}.")
            any_error = True
        elif c > MAX_PER_TYPE:
            print(f"  ❌ ERROR: Type {t} has {c} samples — above maximum {MAX_PER_TYPE}.")
            any_error = True
        else:
            print(f"  ✅ Type {t}: {c} samples (within {MIN_PER_TYPE}–{MAX_PER_TYPE})")

    print()

    # Check combination dominance within each type
    types_seen = sorted(set(qt for (qt, _, _) in combo_counts))
    any_warning = False
    for qt in types_seen:
        type_total = type_counts[qt]
        type_combos = {
            (ml, sc): c
            for (q, ml, sc), c in combo_counts.items()
            if q == qt
        }
        for (ml, sc), c in type_combos.items():
            pct = c / max(type_total, 1)
            if pct > MAX_COMBO_PCT:
                print(
                    f"  ⚠ WARNING: Type {qt} combo ({ml}, {sc}) = "
                    f"{100*pct:.1f}% ({c}/{type_total}) — exceeds {100*MAX_COMBO_PCT:.0f}%."
                )
                any_warning = True

    if not any_error and not any_warning:
        print("  ✅ All validations passed.")
    elif any_error:
        print("\n  ❌ Some type bounds were violated. Review the dataset.")
    elif any_warning:
        print("\n  ⚠ Combination dominance warnings found but no critical errors.")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Merge capped main dataset with boost files and validate.",
    )
    parser.add_argument(
        "--main", required=True,
        help="Capped main JSONL file.",
    )
    parser.add_argument(
        "--boost", nargs="+", required=True,
        help="One or more boost JSONL files.",
    )
    parser.add_argument(
        "--output", required=True,
        help="Output merged JSONL file.",
    )
    args = parser.parse_args()

    # Load main dataset
    main_samples = _load_jsonl(args.main)
    logger.info("loaded_main", count=len(main_samples), file=args.main)
    print(f"\n  Main dataset: {len(main_samples)} samples from {args.main}")

    # Load boost files
    all_boost = []
    for boost_path in args.boost:
        boost_samples = _load_jsonl(boost_path)
        logger.info("loaded_boost", count=len(boost_samples), file=boost_path)
        print(f"  Boost file:   {len(boost_samples)} samples from {boost_path}")
        all_boost.extend(boost_samples)

    print(f"  Total boost:  {len(all_boost)} samples")

    # Concatenate
    combined = main_samples + all_boost
    print(f"  Combined:     {len(combined)} samples")

    # Shuffle with fixed seed
    rng = random.Random(SEED)
    rng.shuffle(combined)
    print(f"  Shuffled with seed {SEED}")

    # Write output
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        for s in combined:
            f.write(json.dumps(s) + "\n")
    print(f"  Written to {args.output}")

    # Three-level report
    type_counts, mastery_counts, combo_counts = _three_level_report(combined)

    # Validate
    _validate_bounds(type_counts, combo_counts)


if __name__ == "__main__":
    main()
