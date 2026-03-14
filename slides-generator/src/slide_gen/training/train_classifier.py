"""
Train Hierarchical Visual Classifier — Two-level DistilBERT classification.

Level 1: Predicts category (6 classes: data_structure, flow_diagram, comparison, chart, conceptual, none)
Level 2: Predicts specific template within category (one model per category)

Features:
- Focal Loss (γ=2.0) for class imbalance
- Label smoothing (0.1)
- Early stopping (patience=3 on f1_weighted)
- Per-class evaluation report & confusion matrix

Usage:
    python -m slide_gen.training.train_classifier \
        --data data/agent_training/classifier_train.jsonl \
        --output models/visual_classifier/ \
        --epochs 30 \
        --batch-size 16
"""

import json
import argparse
from pathlib import Path
from collections import Counter

import torch
import torch.nn.functional as F
from torch.utils.data import Dataset
from transformers import (
    DistilBertForSequenceClassification,
    DistilBertTokenizer,
    Trainer,
    TrainingArguments,
    EarlyStoppingCallback,
)
from sklearn.metrics import accuracy_score, f1_score, classification_report, confusion_matrix
import numpy as np

from slide_gen.core.hierarchy import (
    CATEGORY_HIERARCHY,
    CATEGORY_LIST,
    CATEGORY_TO_ID,
    TEMPLATE_TO_CATEGORY,
    LEVEL2_LABELS,
    LEVEL2_LABEL_TO_ID,
    get_category,
)

# Keep backward compatibility: the old LABEL_LIST used by data generators
from slide_gen.core.slide_schema import VALID_TEMPLATES
LABEL_LIST = VALID_TEMPLATES + ["none"]


# =========================================================================
# DATASET
# =========================================================================

class HierarchicalDataset(Dataset):
    """
    Dataset that can produce labels for either Level 1 (category) or Level 2 (template).

    Args:
        data_path: Path to classifier_train.jsonl
        tokenizer: DistilBERT tokenizer
        level: "category" for Level 1, or a specific category name for Level 2
        max_length: Max token length
    """

    def __init__(self, data_path: str | Path, tokenizer, level: str = "category", max_length=256):
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.level = level
        self.texts = []
        self.labels = []

        # Determine label mapping
        if level == "category":
            self.label_list = CATEGORY_LIST
            self.label_to_id = CATEGORY_TO_ID
        else:
            # Level 2: subset to samples from this category
            if level not in LEVEL2_LABELS:
                raise ValueError(f"Unknown category for Level 2: {level}")
            self.label_list = LEVEL2_LABELS[level]
            self.label_to_id = LEVEL2_LABEL_TO_ID[level]

        with open(data_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                example = json.loads(line)
                template_id = example.get("label", "none")

                if level == "category":
                    # Map template → category
                    cat = get_category(template_id)
                    if cat not in self.label_to_id:
                        cat = "none"
                    self.texts.append(example["text"])
                    self.labels.append(self.label_to_id[cat])
                else:
                    # Level 2: only include samples from this category
                    cat = get_category(template_id)
                    if cat != level:
                        continue
                    if template_id not in self.label_to_id:
                        continue
                    self.texts.append(example["text"])
                    self.labels.append(self.label_to_id[template_id])

        print(f"  Loaded {len(self.texts)} examples for level='{level}' ({len(self.label_list)} classes)")

        # Print distribution
        label_counts = Counter(self.labels)
        for label_id in range(len(self.label_list)):
            count = label_counts.get(label_id, 0)
            if count > 0:
                print(f"    {self.label_list[label_id]}: {count}")

    def __len__(self):
        return len(self.texts)

    def __getitem__(self, idx):
        encoding = self.tokenizer(
            self.texts[idx],
            max_length=self.max_length,
            truncation=True,
            padding="max_length",
            return_tensors="pt",
        )

        return {
            "input_ids": encoding["input_ids"].squeeze(),
            "attention_mask": encoding["attention_mask"].squeeze(),
            "labels": torch.tensor(self.labels[idx], dtype=torch.long),
        }


# =========================================================================
# FOCAL LOSS
# =========================================================================

class FocalLoss(torch.nn.Module):
    """
    Focal Loss: -α(1-p)^γ * log(p)

    Down-weights easy/well-classified examples, focuses on hard ones.
    """

    def __init__(self, alpha: torch.Tensor, gamma: float = 2.0):
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        probs = F.softmax(logits, dim=-1)
        targets_one_hot = F.one_hot(targets, num_classes=logits.size(-1)).float()

        pt = (probs * targets_one_hot).sum(dim=-1)
        pt = torch.clamp(pt, min=1e-8)

        alpha_t = self.alpha.to(logits.device)[targets]

        focal_weight = alpha_t * (1 - pt) ** self.gamma
        loss = -focal_weight * torch.log(pt)

        return loss.mean()


# =========================================================================
# METRICS
# =========================================================================

def compute_metrics(eval_pred):
    """Compute accuracy, F1, and top-3 accuracy for evaluation."""
    logits, labels = eval_pred
    predictions = np.argmax(logits, axis=-1)

    top3_preds = np.argsort(logits, axis=-1)[:, -3:]
    top3_correct = np.mean([label in top3 for label, top3 in zip(labels, top3_preds)])

    return {
        "accuracy": accuracy_score(labels, predictions),
        "top3_accuracy": top3_correct,
        "f1_weighted": f1_score(labels, predictions, average="weighted", zero_division=0),
        "f1_macro": f1_score(labels, predictions, average="macro", zero_division=0),
    }


# =========================================================================
# SINGLE-LEVEL TRAINING HELPER
# =========================================================================

def _train_one_level(
    dataset: HierarchicalDataset,
    label_list: list[str],
    output_dir: str,
    model_name: str,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    warmup_steps: int,
    level_name: str,
):
    """Train a single DistilBERT model for one level of the hierarchy."""

    num_labels = len(label_list)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 70}")
    print(f"TRAINING: {level_name} ({num_labels} classes)")
    print(f"{'=' * 70}")

    tokenizer = DistilBertTokenizer.from_pretrained(model_name)
    model = DistilBertForSequenceClassification.from_pretrained(
        model_name, num_labels=num_labels
    )
    model.config.seq_classif_dropout = 0.3

    # Split into train/val (90/10)
    train_size = int(0.9 * len(dataset))
    val_size = len(dataset) - train_size

    if val_size < 1:
        print(f"  ⚠️  Too few samples ({len(dataset)}) for train/val split. Skipping {level_name}.")
        return

    train_dataset, val_dataset = torch.utils.data.random_split(
        dataset, [train_size, val_size]
    )
    print(f"  Train: {train_size}, Val: {val_size}")

    # Focal Loss weights
    label_counts = Counter(dataset.labels)
    total = len(dataset.labels)

    alpha = torch.ones(num_labels)
    for label_id, count in label_counts.items():
        if count > 0:
            alpha[label_id] = np.sqrt(total / count)

    alpha = alpha / alpha.mean()
    alpha = torch.clamp(alpha, max=10.0)

    print(f"\n  ⚖️  Focal Loss α weights (γ=2.0):")
    for i, w in enumerate(alpha):
        if label_counts.get(i, 0) > 0:
            print(f"    {label_list[i]:<20s}: α={w:.2f}  ({label_counts[i]} samples)")

    focal_loss_fn = FocalLoss(alpha=alpha, gamma=2.0)

    class FocalTrainer(Trainer):
        def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
            labels = inputs.pop("labels")
            outputs = model(**inputs)
            logits = outputs.logits
            loss = focal_loss_fn(logits, labels)
            return (loss, outputs) if return_outputs else loss

    training_args = TrainingArguments(
        output_dir=str(out_path),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        warmup_steps=warmup_steps,
        learning_rate=learning_rate,
        weight_decay=0.01,
        label_smoothing_factor=0.1,
        logging_dir=str(out_path / "logs"),
        logging_steps=50,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        save_only_model=True,
        load_best_model_at_end=True,
        metric_for_best_model="f1_weighted",
        greater_is_better=True,
        report_to="none",
        fp16=torch.cuda.is_available(),
    )

    trainer = FocalTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
    )

    print(f"\n  Starting training (early stopping, patience=3)...")
    trainer.train()

    print(f"\n  Saving model to {out_path}")
    trainer.save_model(str(out_path))
    tokenizer.save_pretrained(str(out_path))

    # Save label config for inference
    config = {"label_list": label_list, "level_name": level_name}
    config_path = out_path / "label_config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    # Post-training evaluation
    print(f"\n  📊 Post-Training Evaluation:")
    eval_result = trainer.predict(val_dataset)
    preds = np.argmax(eval_result.predictions, axis=-1)
    true_labels = np.array([val_dataset[i]["labels"].item() for i in range(len(val_dataset))])

    present_labels = sorted(set(true_labels.tolist()) | set(preds.tolist()))
    target_names = [label_list[i] for i in present_labels]

    print(classification_report(
        true_labels, preds,
        labels=present_labels,
        target_names=target_names,
        zero_division=0,
    ))

    # Save confusion matrix
    cm = confusion_matrix(true_labels, preds, labels=present_labels)
    cm_path = out_path / "confusion_matrix.txt"
    with open(cm_path, "w") as f:
        max_name_len = max(len(n) for n in target_names) if target_names else 10
        header = " " * (max_name_len + 2) + "  ".join(f"{n[:6]:>6}" for n in target_names)
        f.write(f"Confusion Matrix (rows=true, cols=predicted)\n\n{header}\n")
        for i, row in enumerate(cm):
            row_str = f"{target_names[i]:<{max_name_len}}  " + "  ".join(f"{v:>6}" for v in row)
            f.write(row_str + "\n")

    print(f"  📋 Confusion matrix saved to: {cm_path}")

    return trainer


# =========================================================================
# MAIN TRAINING PIPELINE
# =========================================================================

MIN_SAMPLES_FOR_LEVEL2 = 10  # Skip Level 2 training for categories with fewer samples


def train(
    data_path: str,
    output_dir: str,
    model_name: str = "distilbert-base-uncased",
    epochs: int = 30,
    batch_size: int = 16,
    learning_rate: float = 2e-5,
    warmup_steps: int = 50,
):
    """
    Train the full hierarchical classifier.

    Phase 1: Train Level 1 (category) classifier
    Phase 2: Train Level 2 (template) classifiers for each category
    """
    output_base = Path(output_dir)
    output_base.mkdir(parents=True, exist_ok=True)

    tokenizer = DistilBertTokenizer.from_pretrained(model_name)

    # -------------------------------------------------------
    # PHASE 1: Train Level 1 (Category Classifier)
    # -------------------------------------------------------
    print("\n" + "█" * 70)
    print("PHASE 1: LEVEL 1 — CATEGORY CLASSIFIER")
    print("█" * 70)

    l1_dataset = HierarchicalDataset(data_path, tokenizer, level="category")
    l1_output = str(output_base / "level1")

    _train_one_level(
        dataset=l1_dataset,
        label_list=CATEGORY_LIST,
        output_dir=l1_output,
        model_name=model_name,
        epochs=epochs,
        batch_size=batch_size,
        learning_rate=learning_rate,
        warmup_steps=warmup_steps,
        level_name="Level 1 (Category)",
    )

    # -------------------------------------------------------
    # PHASE 2: Train Level 2 (Per-Category Classifiers)
    # -------------------------------------------------------
    print("\n\n" + "█" * 70)
    print("PHASE 2: LEVEL 2 — PER-CATEGORY TEMPLATE CLASSIFIERS")
    print("█" * 70)

    trained_categories = []
    skipped_categories = []

    for category, templates in LEVEL2_LABELS.items():
        if len(templates) <= 1:
            print(f"\n  ⏭️  Skipping '{category}' — only {len(templates)} template(s), no classification needed")
            skipped_categories.append(category)
            continue

        l2_dataset = HierarchicalDataset(data_path, tokenizer, level=category)

        if len(l2_dataset) < MIN_SAMPLES_FOR_LEVEL2:
            print(f"\n  ⏭️  Skipping '{category}' — only {len(l2_dataset)} samples (need ≥{MIN_SAMPLES_FOR_LEVEL2})")
            skipped_categories.append(category)
            continue

        l2_output = str(output_base / "level2" / category)

        _train_one_level(
            dataset=l2_dataset,
            label_list=templates,
            output_dir=l2_output,
            model_name=model_name,
            epochs=epochs,
            batch_size=batch_size,
            learning_rate=learning_rate,
            warmup_steps=warmup_steps,
            level_name=f"Level 2 ({category})",
        )
        trained_categories.append(category)

    # -------------------------------------------------------
    # SAVE HIERARCHY CONFIG (for inference)
    # -------------------------------------------------------
    hierarchy_config = {
        "category_list": CATEGORY_LIST,
        "category_hierarchy": {k: v for k, v in CATEGORY_HIERARCHY.items()},
        "trained_level2": trained_categories,
        "skipped_level2": skipped_categories,
    }
    config_path = output_base / "hierarchy_config.json"
    with open(config_path, "w") as f:
        json.dump(hierarchy_config, f, indent=2)

    print(f"\n\n{'=' * 70}")
    print("TRAINING COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Level 1 model:  {output_base / 'level1'}")
    print(f"  Level 2 models: {', '.join(trained_categories) or '(none)'}")
    print(f"  Skipped:        {', '.join(skipped_categories) or '(none)'}")
    print(f"  Config:         {config_path}")
    print(f"\nDone!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train hierarchical visual classifier")
    parser.add_argument("--data", "-d", required=True, help="Path to classifier_train.jsonl")
    parser.add_argument("--output", "-o", default="models/visual_classifier/",
                        help="Output directory for models")
    parser.add_argument("--model", "-m", default="distilbert-base-uncased", help="Base model")
    parser.add_argument("--epochs", type=int, default=30, help="Max training epochs")
    parser.add_argument("--batch-size", type=int, default=16, help="Batch size")
    parser.add_argument("--lr", type=float, default=2e-5, help="Learning rate")

    args = parser.parse_args()
    train(args.data, args.output, args.model, args.epochs, args.batch_size, args.lr)
