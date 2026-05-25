"""
Log the existing (pre-MLflow) visual classifier run to MLflow retroactively.

Derives metrics from the saved confusion_matrix.txt files in each model
directory, then logs them alongside the model artifacts and hyperparameters.

Usage:
    python scripts/log_old_run_to_mlflow.py
    python scripts/log_old_run_to_mlflow.py --tracking-uri http://127.0.0.1:5000
"""

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

# ── path setup ──────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

import mlflow
import mlflow.sklearn
from sklearn.metrics import (
    accuracy_score, f1_score, classification_report,
)


# ============================================================
# Helpers
# ============================================================

def parse_confusion_matrix(txt_path: Path):
    """
    Parse a confusion_matrix.txt file produced by train_classifier.py.

    Returns (labels, cm_array) or (None, None) if unparseable.
    """
    try:
        lines = txt_path.read_text().strip().splitlines()
        # Find header line (first line with 2+ identifiers)
        header_idx = None
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("Confusion"):
                header_idx = i
                break

        if header_idx is None:
            return None, None

        col_headers = lines[header_idx].split()
        data_lines = [l for l in lines[header_idx + 1:] if l.strip()]

        labels = []
        rows = []
        for line in data_lines:
            parts = line.split()
            # Row label is everything before the numbers
            nums = []
            label_parts = []
            for p in parts:
                try:
                    nums.append(int(p))
                except ValueError:
                    label_parts.append(p)
            if nums:
                labels.append("_".join(label_parts))
                rows.append(nums)

        if not rows:
            return None, None

        cm = np.array(rows)
        return labels, cm
    except Exception as e:
        print(f"  ⚠ Could not parse {txt_path}: {e}")
        return None, None


def metrics_from_cm(labels, cm):
    """Compute accuracy + weighted/macro F1 from a confusion matrix."""
    y_true, y_pred = [], []
    for i, row in enumerate(cm):
        for j, count in enumerate(row):
            y_true.extend([i] * count)
            y_pred.extend([j] * count)

    y_true = np.array(y_true)
    y_pred = np.array(y_pred)

    acc = accuracy_score(y_true, y_pred)
    f1_w = f1_score(y_true, y_pred, average="weighted", zero_division=0)
    f1_m = f1_score(y_true, y_pred, average="macro", zero_division=0)
    return {"accuracy": acc, "f1_weighted": f1_w, "f1_macro": f1_m}


def log_model_dir(run, prefix: str, model_dir: Path, level_name: str):
    """Log metrics + artifacts from a single model directory."""
    print(f"\n  [{level_name}]")

    cm_path = model_dir / "confusion_matrix.txt"
    label_config_path = model_dir / "label_config.json"

    if cm_path.exists():
        labels, cm = parse_confusion_matrix(cm_path)
        if cm is not None:
            metrics = metrics_from_cm(labels, cm)
            for k, v in metrics.items():
                run.log_metric(f"{prefix}/{k}", v)
                print(f"    {prefix}/{k}: {v:.4f}")
        mlflow.log_artifact(str(cm_path), artifact_path=f"{prefix}/eval")

    if label_config_path.exists():
        with open(label_config_path) as f:
            lc = json.load(f)
        run.log_param(f"{prefix}/labels", ",".join(lc.get("label_list", [])))
        run.log_param(f"{prefix}/num_classes", len(lc.get("label_list", [])))
        mlflow.log_artifact(str(label_config_path), artifact_path=f"{prefix}/config")

    for extra in ["config.json", "hierarchy_config.json"]:
        p = model_dir / extra
        if p.exists():
            mlflow.log_artifact(str(p), artifact_path=f"{prefix}/config")


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Log old classifier run to MLflow")
    parser.add_argument("--model-dir", default=str(_PROJECT_ROOT / "models" / "visual_classifier"),
                        help="Path to the visual_classifier model directory")
    parser.add_argument("--tracking-uri", default="mlruns",
                        help="MLflow tracking URI (default: local mlruns/)")
    parser.add_argument("--experiment", default="visual_classifier",
                        help="MLflow experiment name")
    args = parser.parse_args()

    model_base = Path(args.model_dir)
    mlflow.set_tracking_uri(args.tracking_uri)
    mlflow.set_experiment(args.experiment)

    print(f"\n{'='*60}")
    print("Logging OLD visual classifier run to MLflow")
    print(f"  Model dir:    {model_base}")
    print(f"  Tracking URI: {args.tracking_uri}")
    print(f"  Experiment:   {args.experiment}")
    print(f"{'='*60}")

    with mlflow.start_run(run_name="old_run_v1_hierarchical") as run:
        # ── Tags ──────────────────────────────────────────────
        mlflow.set_tags({
            "source": "retroactively_logged",
            "architecture": "distilbert-base-uncased",
            "hierarchy": "two_level",
            "note": "Pre-MLflow run. Metrics derived from saved confusion matrices.",
        })

        # ── Hyperparameters (best guess from training args) ───
        # These are the defaults from train_classifier.py at the time
        mlflow.log_params({
            "base_model": "distilbert-base-uncased",
            "max_epochs": 30,
            "batch_size": 16,
            "learning_rate": 2e-5,
            "warmup_steps": 50,
            "weight_decay": 0.01,
            "label_smoothing": 0.1,
            "loss": "focal_loss",
            "focal_gamma": 2.0,
            "early_stopping_patience": 3,
            "metric_for_best_model": "f1_weighted",
            "train_val_split": "90/10",
        })

        # ── Level 1 ───────────────────────────────────────────
        l1_dir = model_base / "level1"
        if l1_dir.exists():
            log_model_dir(mlflow, "level1", l1_dir, "Level 1 — Category")
        else:
            print("  ⚠ level1/ not found — skipping")

        # ── Level 2 ───────────────────────────────────────────
        l2_base = model_base / "level2"
        if l2_base.exists():
            for cat_dir in sorted(l2_base.iterdir()):
                if cat_dir.is_dir():
                    log_model_dir(
                        mlflow, f"level2/{cat_dir.name}", cat_dir,
                        f"Level 2 — {cat_dir.name}"
                    )

        # ── Hierarchy config ──────────────────────────────────
        hcfg = model_base / "hierarchy_config.json"
        if hcfg.exists():
            with open(hcfg) as f:
                hconfig = json.load(f)
            mlflow.log_param("level1/num_categories", len(hconfig.get("category_list", [])))
            mlflow.log_param("trained_level2_categories",
                             ",".join(hconfig.get("trained_level2", [])))
            mlflow.log_artifact(str(hcfg), artifact_path="config")

        print(f"\n✅ Run logged: {run.info.run_id}")
        print(f"   View with:  mlflow ui --port 5000")


if __name__ == "__main__":
    main()
