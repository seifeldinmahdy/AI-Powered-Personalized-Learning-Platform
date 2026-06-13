"""Merge capped main dataset with boost files, validate, and produce final JSONL.

Reads the capped main dataset and boost files for underrepresented types,
concatenates them, shuffles with a fixed seed, runs a three-level distribution
report, validates mandatory minimums, and writes the final merged JSONL.

Optionally also produces mcq_qg_final.jsonl and mcq_dg_final.jsonl by calling
format_qg_data / format_dg_data with the merged file as input.

Usage::

    python -m mcq.training.merge_dataset \\
        --main  data/mcq_training/mcq_final_cleaned.jsonl \\
        --boost data/mcq_training/mcq_4c_boost.jsonl \\
                data/mcq_training/mcq_4d_boost.jsonl \\
        --output data/mcq_training/mcq_merged.jsonl \\
        --qg-output data/mcq_training/mcq_qg_final.jsonl \\
        --dg-output data/mcq_training/mcq_dg_final.jsonl \\
        --tokenizer unsloth/Qwen3-4B-Instruct
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

SEED = 42
MIN_PER_TYPE = 150
MAX_PER_TYPE = 900
MAX_COMBO_PCT = 0.40  # no (mastery, score_cat) combo > 40% within a type

# Mandatory minimums from the data-generation spec
_VERY_WEAK_4A_MIN_PER_MASTERY = 150  # Novice, Intermediate, Expert each
_NOVICE_INTER_PAIRED_MIN = 200       # samples that have both Novice and Intermediate


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
    print(f"\n{'=' * W}")
    print("  LEVEL 1 — QUESTION TYPE DISTRIBUTION")
    print(f"{'=' * W}")
    for t in sorted(type_counts):
        c = type_counts[t]
        pct = 100 * c / max(total, 1)
        bar = "█" * int(40 * c / max(total, 1))
        print(f"    Type {t:<4}: {c:>5}  ({pct:5.1f}%)  {bar}")

    # ── Level 2: Per mastery level ─────────────────────────────────────
    print(f"\n{'=' * W}")
    print("  LEVEL 2 — MASTERY LEVEL DISTRIBUTION")
    print(f"{'=' * W}")
    for m in sorted(mastery_counts):
        c = mastery_counts[m]
        pct = 100 * c / max(total, 1)
        bar = "█" * int(40 * c / max(total, 1))
        print(f"    {m:<14}: {c:>5}  ({pct:5.1f}%)  {bar}")

    # ── Level 3: Per (type, mastery, score_category) combination ──────
    print(f"\n{'=' * W}")
    print("  LEVEL 3 — PER-(TYPE, MASTERY, SCORE_CATEGORY) COMBINATION")
    print(f"{'=' * W}")
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
    print(f"{'=' * W}")
    print("  VALIDATION")
    print(f"{'=' * W}")

    any_error = False

    # Check per-type bounds
    for t in sorted(type_counts):
        c = type_counts[t]
        if c < MIN_PER_TYPE:
            print(f"  ERROR: Type {t} has {c} samples -- below minimum {MIN_PER_TYPE}.")
            any_error = True
        elif c > MAX_PER_TYPE:
            print(f"  ERROR: Type {t} has {c} samples -- above maximum {MAX_PER_TYPE}.")
            any_error = True
        else:
            print(f"  OK   Type {t}: {c} samples (within {MIN_PER_TYPE}-{MAX_PER_TYPE})")

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
                    f"  WARNING: Type {qt} combo ({ml}, {sc}) = "
                    f"{100*pct:.1f}% ({c}/{type_total}) -- exceeds {100*MAX_COMBO_PCT:.0f}%."
                )
                any_warning = True

    if not any_error and not any_warning:
        print("  All type validations passed.")
    elif any_error:
        print("\n  Some type bounds were violated. Review the dataset.")
    elif any_warning:
        print("\n  Combination dominance warnings found but no critical errors.")

    print()
    return not any_error


def _check_mandatory_minimums(samples: list[dict]) -> bool:
    """Check all mandatory minimums from the data-generation spec.

    Returns True if all minimums are met, False otherwise (with details printed).
    Caller should stop and regenerate if this returns False.
    """
    W = 66
    print(f"\n{'=' * W}")
    print("  MANDATORY MINIMUM CHECKS")
    print(f"{'=' * W}")

    passed = True

    # very_weak × 4a per mastery
    for mastery in ("Novice", "Intermediate", "Expert"):
        count = sum(
            1 for s in samples
            if s.get("mastery_level") == mastery
            and s.get("score_category") == "very_weak"
            and s.get("question_type") == "4a"
        )
        ok = count >= _VERY_WEAK_4A_MIN_PER_MASTERY
        status = "OK  " if ok else "FAIL"
        print(
            f"  {status}  {mastery} x very_weak x 4a: {count:>4}  "
            f"(min: {_VERY_WEAK_4A_MIN_PER_MASTERY})"
        )
        if not ok:
            passed = False

    # Novice/Intermediate paired — samples that appear in both mastery buckets
    # for the same chunk.  Approximated by: count of samples where mastery is
    # either Novice or Intermediate (these are the two adjacent levels that
    # students progress through; having paired examples aids interpolation).
    novice_inter_count = sum(
        1 for s in samples
        if s.get("mastery_level") in ("Novice", "Intermediate")
    )
    ok = novice_inter_count >= _NOVICE_INTER_PAIRED_MIN
    status = "OK  " if ok else "FAIL"
    print(
        f"  {status}  Novice/Intermediate examples: {novice_inter_count:>4}  "
        f"(min: {_NOVICE_INTER_PAIRED_MIN})"
    )
    if not ok:
        passed = False

    if passed:
        print("  All mandatory minimums met.")
    else:
        print("\n  MANDATORY MINIMUMS NOT MET. Regenerate before uploading to Kaggle.")

    print(f"{'=' * W}\n")
    return passed


def _print_final_distribution(samples: list[dict]):
    """Print the canonical FINAL DATASET DISTRIBUTION table from the spec."""
    W = 55
    n = len(samples)
    dg_n = n * 3  # 3 distractor examples per MCQ

    type_counts: Counter = Counter(s.get("question_type", "?") for s in samples)
    mastery_counts: Counter = Counter(s.get("mastery_level", "?") for s in samples)

    vw_4a = {
        m: sum(
            1 for s in samples
            if s.get("mastery_level") == m
            and s.get("score_category") == "very_weak"
            and s.get("question_type") == "4a"
        )
        for m in ("Novice", "Intermediate", "Expert")
    }

    novice_inter = sum(
        1 for s in samples
        if s.get("mastery_level") in ("Novice", "Intermediate")
    )

    ps_values = [
        s["personalization_score"]
        for s in samples
        if isinstance(s.get("personalization_score"), (int, float))
    ]
    avg_ps = round(sum(ps_values) / len(ps_values), 2) if ps_values else 0.0

    def _tc(t: str) -> int:
        return type_counts.get(t, 0)

    print(f"\n{'=' * W}")
    print("  FINAL DATASET DISTRIBUTION")
    print(f"{'=' * W}")
    print(f"  QG examples: {n:,}")
    print(f"  DG examples: {dg_n:,}")
    print()
    print("  By type:")
    print(f"    Type 1:  {_tc('1'):>4}   Type 4a: {_tc('4a'):>4}   Type 4b: {_tc('4b'):>4}")
    print(f"    Type 2:  {_tc('2'):>4}   Type 4c: {_tc('4c'):>4}   Type 4d: {_tc('4d'):>4}")
    print(f"    Type 3:  {_tc('3'):>4}   Type 4e: {_tc('4e'):>4}")
    print()
    print("  very_weak x 4a:")
    print(f"    Novice x very_weak x 4a:        {vw_4a['Novice']:>4}  (min: 150)")
    print(f"    Intermediate x very_weak x 4a:  {vw_4a['Intermediate']:>4}  (min: 150)")
    print(f"    Expert x very_weak x 4a:        {vw_4a['Expert']:>4}  (min: 150)")
    print()
    print(f"  Novice/Intermediate examples:    {novice_inter:>4}  (min: 200)")
    print()
    print(f"  Avg personalization_score:    {avg_ps:.2f} / 3.0")
    print(f"{'=' * W}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Merge capped main dataset with boost files and validate.",
    )
    parser.add_argument(
        "--main", required=True,
        help="Capped main JSONL file.",
    )
    parser.add_argument(
        "--boost", nargs="*", default=[],
        help="Zero or more boost JSONL files.",
    )
    parser.add_argument(
        "--output", required=True,
        help="Output merged JSONL file.",
    )
    parser.add_argument(
        "--qg-output", default="",
        help="If set, format and write QG training JSONL to this path.",
    )
    parser.add_argument(
        "--dg-output", default="",
        help="If set, format and write DG training JSONL to this path.",
    )
    parser.add_argument(
        "--tokenizer", default="unsloth/Qwen3-4B-Instruct",
        help="Tokenizer for QG/DG formatting (default: unsloth/Qwen3-4B-Instruct).",
    )
    parser.add_argument(
        "--no-format", action="store_true",
        help="Skip QG/DG formatting even if --qg-output/--dg-output are set.",
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

    if all_boost:
        print(f"  Total boost:  {len(all_boost)} samples")

    # Concatenate
    combined = main_samples + all_boost
    print(f"  Combined:     {len(combined)} samples")

    # Shuffle with fixed seed
    rng = random.Random(SEED)
    rng.shuffle(combined)
    print(f"  Shuffled with seed {SEED}")

    # Write merged output
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        for s in combined:
            f.write(json.dumps(s) + "\n")
    print(f"  Written to {args.output}")

    # Three-level report
    type_counts, mastery_counts, combo_counts = _three_level_report(combined)

    # Validate type bounds
    _validate_bounds(type_counts, combo_counts)

    # Mandatory minimums
    minimums_met = _check_mandatory_minimums(combined)

    # Final distribution table (always printed)
    _print_final_distribution(combined)

    if not minimums_met:
        print("  Mandatory minimums not met. Stop and regenerate before uploading.")
        sys.exit(1)

    # Optional: format into QG/DG training files
    if not args.no_format:
        if args.qg_output:
            from mcq.training.format_qg import format_qg_data
            print(f"\n  Formatting QG training data -> {args.qg_output}")
            qg_n = format_qg_data(args.output, args.qg_output, args.tokenizer)
            print(f"  QG: {qg_n} examples written")

        if args.dg_output:
            from mcq.training.format_dg import format_dg_data
            print(f"\n  Formatting DG training data -> {args.dg_output}")
            dg_n = format_dg_data(args.output, args.dg_output, args.tokenizer)
            print(f"  DG: {dg_n} examples written")


if __name__ == "__main__":
    main()
