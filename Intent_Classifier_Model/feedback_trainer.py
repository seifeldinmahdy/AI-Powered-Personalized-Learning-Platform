"""
Feedback-aware retraining orchestrator for the intent classifier.

This script is invoked by the Django management command
``check_intent_retraining`` once enough user reviews (👍/👎) have been
collected. It:

1. Loads pending feedback utterances exported by the backend.
2. Regenerates the base synthetic dataset (optional but recommended).
3. Mixes feedback rows into train/val/test splits.
4. Runs ``train.py`` with the mixed splits and a feedback-specific test set.
5. Applies a quality gate that includes both synthetic-test and feedback-test F1.
6. Promotes the new model to ``best_model.pt`` if the gate passes.

Usage:
    python feedback_trainer.py [--regenerate] [--feedback-csv PATH]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
FEEDBACK_CSV_DEFAULT = DATA_DIR / "feedback_utterances.csv"
SPLITS = {
    "train": DATA_DIR / "train.csv",
    "val": DATA_DIR / "val.csv",
    "test": DATA_DIR / "test.csv",
}
MIXED_SPLITS = {
    "train": DATA_DIR / "train_mixed.csv",
    "val": DATA_DIR / "val_mixed.csv",
    "test": DATA_DIR / "test_mixed.csv",
}
FEEDBACK_TEST_CSV = DATA_DIR / "feedback_test.csv"
FEEDBACK_MANIFEST = BASE_DIR / "feedback_batch_manifest.json"
MODEL_OUTPUT = BASE_DIR / "best_model_feedback.pt"
RESULTS_OUTPUT = BASE_DIR / "training_results_feedback.json"
PROD_MODEL = BASE_DIR / "best_model.pt"

# Quality safeguard: no single student's utterances may dominate a retraining batch.
MAX_STUDENT_FRACTION = 0.40
SAMPLE_SIZE = 10

INTENT_LABEL_MAP = {
    "On-Topic Question": 0,
    "Off-Topic Question": 1,
    "Emotional-State": 2,
    "Pace-Related": 3,
    "Repeat/clarification": 4,
    "Debugging/Code-Sharing": 5,
}
INTENT_NAMES = list(INTENT_LABEL_MAP.keys())


def load_feedback(csv_path: Path) -> pd.DataFrame:
    """Load and validate the feedback CSV exported from the backend."""
    if not csv_path.exists():
        raise FileNotFoundError(f"Feedback CSV not found: {csv_path}")

    df = pd.read_csv(csv_path)
    required = {"student_input", "session_context", "label_id"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Feedback CSV missing columns: {missing}")

    # Start from the original predicted label, then overwrite with any
    # human-provided corrected_intent.
    df["label"] = df["label_id"].astype(int)
    if "corrected_intent" in df.columns:
        corrected_map = {name: idx for name, idx in INTENT_LABEL_MAP.items()}
        mask = df["corrected_intent"].notna() & (df["corrected_intent"] != "")
        df.loc[mask, "label"] = df.loc[mask, "corrected_intent"].map(corrected_map)
    df["intent_name"] = df["label"].map(lambda i: INTENT_NAMES[i])

    return df


def cap_per_student(df: pd.DataFrame, max_fraction: float = MAX_STUDENT_FRACTION, random_state: int = 42) -> pd.DataFrame:
    """Downsample any over-represented student so no one dominates the batch."""
    if "student_id" not in df.columns or df.empty:
        return df

    total = len(df)
    cap = max(1, int(total * max_fraction))
    capped_rows = []
    capped_students = []

    for student_id, group in df.groupby("student_id", sort=False):
        if len(group) > cap:
            capped_rows.append(group.sample(n=cap, random_state=random_state))
            capped_students.append((student_id, len(group), cap))
        else:
            capped_rows.append(group)

    if capped_students:
        print("[!] Per-student cap applied:")
        for sid, original, new_cap in capped_students:
            print(f"    student {sid}: {original} -> {new_cap} rows")

    return pd.concat(capped_rows, ignore_index=True).sample(frac=1, random_state=random_state).reset_index(drop=True)


def write_manifest(df: pd.DataFrame, output_path: Path = FEEDBACK_MANIFEST) -> dict:
    """Write a lightweight manifest for admin visibility into the batch."""
    sample_df = df.groupby("intent_name", sort=False).apply(
        lambda g: g.head(max(1, SAMPLE_SIZE // df["intent_name"].nunique()))
    ).reset_index(drop=True)
    sample = sample_df[["student_id", "intent_name", "student_input", "corrected_intent"]].to_dict("records")

    manifest = {
        "total_rows": len(df),
        "per_student": df.groupby("student_id").size().to_dict(),
        "per_class": df.groupby("intent_name").size().to_dict(),
        "max_student_fraction": MAX_STUDENT_FRACTION,
        "capped": any(
            count / len(df) > MAX_STUDENT_FRACTION
            for count in df.groupby("student_id").size().values
        ),
        "sample": sample,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"[+] Feedback batch manifest written to {output_path}")
    return manifest


def split_feedback(df: pd.DataFrame, train_size=0.70, val_size=0.15, random_state=42):
    """Split feedback rows into train/val/test with stratification."""
    # Keep only the columns the training pipeline expects.
    df = df[["student_input", "session_context", "label", "intent_name"]].copy()
    if len(df) < 6:
        raise ValueError("Need at least 6 feedback rows to create train/val/test splits.")

    labels = df["label"].values
    train_df, temp_df = train_test_split(
        df, test_size=(1 - train_size), stratify=labels, random_state=random_state
    )
    test_ratio = 1 - train_size - val_size
    if test_ratio <= 0:
        raise ValueError("Invalid train/val/test proportions.")
    val_df, test_df = train_test_split(
        temp_df,
        test_size=(test_ratio / (1 - train_size)),
        stratify=temp_df["label"].values,
        random_state=random_state,
    )
    return train_df, val_df, test_df


def backup_splits():
    """Backup original train/val/test CSVs before overwriting with mixed data."""
    for name, path in SPLITS.items():
        if path.exists():
            shutil.copy2(path, path.with_suffix(".csv.bak"))


def restore_splits():
    """Restore original train/val/test CSVs from backup."""
    for name, path in SPLITS.items():
        backup = path.with_suffix(".csv.bak")
        if backup.exists():
            shutil.copy2(backup, path)
            backup.unlink()


def generate_synthetic_dataset():
    """Regenerate the base synthetic dataset via dataset_generator.py."""
    print("[+] Regenerating synthetic dataset...")
    result = subprocess.run(
        [sys.executable, "dataset_generator.py"],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise RuntimeError("dataset_generator.py failed")
    print("[+] Synthetic dataset regenerated.")


def run_feedback_training(feedback_test_csv: Path):
    """Run train.py against the mixed splits and feedback test set."""
    env = os.environ.copy()
    env["INTENT_TRAIN_CSV"] = str(MIXED_SPLITS["train"])
    env["INTENT_VAL_CSV"] = str(MIXED_SPLITS["val"])
    env["INTENT_TEST_CSV"] = str(MIXED_SPLITS["test"])
    env["INTENT_BEST_MODEL_PATH"] = str(MODEL_OUTPUT)
    env["INTENT_RESULTS_PATH"] = str(RESULTS_OUTPUT)
    env["INTENT_FEEDBACK_TEST_CSV"] = str(feedback_test_csv)

    print("[+] Starting training run with mixed data...")
    result = subprocess.run(
        [sys.executable, "train.py"],
        cwd=str(BASE_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    # Stream output for logs
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError("train.py failed")
    print("[+] Training run complete.")


def quality_gate_passes(results: dict) -> bool:
    """
    Quality gate for feedback-trained models.

    Requires:
      - synthetic test accuracy >= 0.88 and F1 >= 0.88
      - Emotional-State F1 >= 0.88
      - On-Topic F1 >= 0.82
      - Debugging F1 >= 0.90
      - feedback test F1 >= 0.75 (lower bar because feedback data is smaller)
    """
    metrics = results.get("metrics", {})
    per_class = results.get("per_class_metrics", {})
    fb_metrics = results.get("feedback_test_metrics", {})

    acc = metrics.get("accuracy", 0.0)
    f1 = metrics.get("f1_score", 0.0)
    emo_f1 = per_class.get("Emotional-State", {}).get("f1_score", 0.0)
    ontopic_f1 = per_class.get("On-Topic Question", {}).get("f1_score", 0.0)
    debug_f1 = per_class.get("Debugging/Code-Sharing", {}).get("f1_score", 0.0)
    fb_f1 = fb_metrics.get("f1_score", 0.0)

    print(f"  Quality gate check:")
    print(f"    synthetic acc={acc:.3f} (>=0.88)")
    print(f"    synthetic f1={f1:.3f} (>=0.88)")
    print(f"    emotional f1={emo_f1:.3f} (>=0.88)")
    print(f"    ontopic f1={ontopic_f1:.3f} (>=0.82)")
    print(f"    debug f1={debug_f1:.3f} (>=0.90)")
    print(f"    feedback f1={fb_f1:.3f} (>=0.75)")

    if acc >= 1.0:
        print("  [!] Perfect accuracy — likely memorisation. Rejecting.")
        return False

    return (
        acc >= 0.88
        and f1 >= 0.88
        and emo_f1 >= 0.88
        and ontopic_f1 >= 0.82
        and debug_f1 >= 0.90
        and fb_f1 >= 0.75
    )


def main():
    parser = argparse.ArgumentParser(description="Feedback-aware intent classifier retraining")
    parser.add_argument(
        "--feedback-csv",
        type=Path,
        default=FEEDBACK_CSV_DEFAULT,
        help="Path to feedback utterances CSV exported from the backend.",
    )
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="Regenerate the base synthetic dataset before mixing feedback.",
    )
    parser.add_argument(
        "--skip-quality-gate",
        action="store_true",
        help="Skip the quality gate and always promote the model (not recommended).",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("Feedback-Aware Intent Classifier Retraining")
    print("=" * 60)

    feedback_df = load_feedback(args.feedback_csv)
    print(f"[+] Loaded {len(feedback_df)} feedback utterances.")
    print(feedback_df["label"].value_counts().sort_index().to_string())

    feedback_df = cap_per_student(feedback_df)
    write_manifest(feedback_df)

    if args.regenerate:
        generate_synthetic_dataset()

    # Verify base splits exist
    for name, path in SPLITS.items():
        if not path.exists():
            raise FileNotFoundError(f"Missing base split: {path}")

    backup_splits()
    try:
        # Split feedback and mix into base synthetic data
        fb_train, fb_val, fb_test = split_feedback(feedback_df)
        print(f"[+] Feedback split — train:{len(fb_train)} val:{len(fb_val)} test:{len(fb_test)}")

        fb_test.to_csv(FEEDBACK_TEST_CSV, index=False)

        for split_name, mixed_path in MIXED_SPLITS.items():
            base_df = pd.read_csv(SPLITS[split_name])
            split_df = {"train": fb_train, "val": fb_val, "test": fb_test}[split_name]
            mixed_df = pd.concat([base_df, split_df], ignore_index=True)
            mixed_df = mixed_df.sample(frac=1, random_state=42).reset_index(drop=True)
            mixed_df.to_csv(mixed_path, index=False)
            print(f"[+] Wrote {mixed_path} ({len(mixed_df)} rows)")

        run_feedback_training(FEEDBACK_TEST_CSV)

        with open(RESULTS_OUTPUT, "r") as f:
            results = json.load(f)

        if args.skip_quality_gate:
            print("[!] Quality gate skipped by flag.")
            promote = True
        else:
            promote = quality_gate_passes(results)

        if promote:
            if MODEL_OUTPUT.exists():
                shutil.copy2(MODEL_OUTPUT, PROD_MODEL)
                print(f"[+] Model promoted: {MODEL_OUTPUT} -> {PROD_MODEL}")
            else:
                print(f"[!] Model output not found at {MODEL_OUTPUT}; promotion skipped.")
                sys.exit(1)
        else:
            print("[!] Quality gate not met. Model NOT promoted.")
            sys.exit(2)

    finally:
        restore_splits()
        print("[+] Restored original synthetic splits.")

    print("=" * 60)
    print("Feedback retraining pipeline complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
