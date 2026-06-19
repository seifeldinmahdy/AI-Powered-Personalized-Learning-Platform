"""
Train Hierarchical Visual Classifier — Two-level DistilBERT classification.

Level 1: Predicts category (7 classes: data_structure, flow_diagram, comparison,
         chart, conceptual, architectural, none)
Level 2: Predicts specific template within category (one model per category)

Features:
- Focal Loss (γ=2.0) for class imbalance
- Cosine LR schedule with warmup
- Differential learning rates per layer group
- Stratified 70/15/15 train/val/test split with balanced test set
- Synonym augmentation for rare classes (<80 samples)
- Early stopping (patience=3 on f1_macro)
- Per-class evaluation report & confusion matrix
- Separate val and test evaluation with MLflow tracking

Usage:
    python -m slide_gen.training.train_classifier \\
        --data data/agent_training/classifier_train.jsonl \\
        --output models/visual_classifier/ \\
        --epochs 30 \\
        --batch-size 16
"""

import os
import json
import random
import argparse
from pathlib import Path
from collections import Counter

# Enable CPU fallback for any MPS-unsupported ops (must be set before torch import)
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import torch
import torch.nn.functional as F
from torch.utils.data import Dataset, Subset
from transformers import (
    DistilBertForSequenceClassification,
    DistilBertTokenizer,
    Trainer,
    TrainingArguments,
    EarlyStoppingCallback,
)
from sklearn.model_selection import train_test_split as sklearn_split
from sklearn.utils import resample as sklearn_resample

# ── Device detection ────────────────────────────────────────────────────────
if torch.cuda.is_available():
    _DEVICE = "cuda"
elif torch.backends.mps.is_available():
    _DEVICE = "mps"
else:
    _DEVICE = "cpu"
print(f"🖥️  Training device: {_DEVICE.upper()}")
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

# MLflow — optional; training continues normally if not available
try:
    import mlflow
    import mlflow.sklearn
    _MLFLOW_AVAILABLE = True
except ImportError:
    _MLFLOW_AVAILABLE = False
    print("mlflow not installed — run tracking disabled. "
          "Install with: pip install mlflow")

# NLTK WordNet — optional; used for synonym augmentation of rare classes
_WORDNET_AVAILABLE = False
try:
    import nltk
    from nltk.corpus import wordnet
    try:
        wordnet.synsets("test")
        _WORDNET_AVAILABLE = True
    except LookupError:
        try:
            nltk.download("wordnet", quiet=True)
            nltk.download("omw-1.4", quiet=True)
            wordnet.synsets("test")
            _WORDNET_AVAILABLE = True
        except Exception:
            pass
except ImportError:
    pass
if not _WORDNET_AVAILABLE:
    print("⚠️  WordNet not available — synonym augmentation disabled.")


# =========================================================================
# AUGMENTATION
# =========================================================================

AUGMENTATION_THRESHOLD = 80
AUGMENTATION_REPLACE_PROB = 0.15


def synonym_replace(text: str, replace_prob: float = AUGMENTATION_REPLACE_PROB) -> str:
    """Replace words with WordNet synonyms with given probability."""
    if not _WORDNET_AVAILABLE:
        return text
    words = text.split()
    new_words = []
    for word in words:
        if len(word) < 4 or random.random() > replace_prob:
            new_words.append(word)
            continue
        synsets = wordnet.synsets(word.lower())
        if synsets:
            synonyms = set()
            for syn in synsets:
                for lemma in syn.lemmas():
                    name = lemma.name().replace("_", " ")
                    if name.lower() != word.lower():
                        synonyms.add(name)
            if synonyms:
                new_words.append(random.choice(list(synonyms)))
                continue
        new_words.append(word)
    return " ".join(new_words)


def make_balanced_test_set(indices, labels):
    """Resample test indices so every class has exactly min_count samples."""
    labels = np.array(labels)
    unique = np.unique(labels)
    counts = Counter(labels.tolist())
    min_count = min(counts.values())
    if min_count < 1:
        return list(indices), 0
    balanced = []
    for cls in unique:
        mask = labels == cls
        cls_idx = np.array(indices)[mask]
        sampled = sklearn_resample(
            cls_idx, n_samples=min_count, replace=False, random_state=42
        )
        balanced.extend(sampled.tolist())
    return balanced, min_count


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
        augment: If True, augment rare classes with synonym replacement
    """

    def __init__(self, data_path: str | Path, tokenizer, level: str = "category",
                 max_length=256, augment: bool = True):
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.level = level
        self.texts = []
        self.labels = []
        self.augmentation_stats = {}

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
                        continue  # skip 'none'/unknown — not a trained category
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

        original_count = len(self.texts)
        print(f"  Loaded {original_count} examples for level='{level}' ({len(self.label_list)} classes)")

        # Print distribution
        label_counts = Counter(self.labels)
        for label_id in range(len(self.label_list)):
            count = label_counts.get(label_id, 0)
            if count > 0:
                print(f"    {self.label_list[label_id]}: {count}")

        # Augment rare classes (Change 5)
        if augment and _WORDNET_AVAILABLE:
            augmented_total = 0
            for label_id in range(len(self.label_list)):
                count = label_counts.get(label_id, 0)
                if 0 < count < AUGMENTATION_THRESHOLD:
                    needed = AUGMENTATION_THRESHOLD - count
                    class_indices = [i for i, l in enumerate(self.labels) if l == label_id]
                    added = 0
                    for _ in range(needed):
                        src_idx = random.choice(class_indices)
                        aug_text = synonym_replace(self.texts[src_idx])
                        self.texts.append(aug_text)
                        self.labels.append(label_id)
                        added += 1
                    self.augmentation_stats[self.label_list[label_id]] = {
                        "original": count, "augmented": added, "final": count + added,
                    }
                    augmented_total += added
                    print(f"    ↳ Augmented {self.label_list[label_id]}: {count} → {count + added}")
            if augmented_total > 0:
                print(f"  📈 Augmented samples added: {augmented_total} (total: {len(self.texts)})")

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
    mlflow_prefix: str | None = None,
):
    """Train a single DistilBERT model for one level of the hierarchy."""

    num_labels = len(label_list)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 70}")
    print(f"TRAINING: {level_name} ({num_labels} classes)")
    print(f"  ℹ️  Primary metric: f1_macro (early stopping)")
    print(f"{'=' * 70}")

    tokenizer = DistilBertTokenizer.from_pretrained(model_name)
    model = DistilBertForSequenceClassification.from_pretrained(
        model_name, num_labels=num_labels
    )
    model.config.seq_classif_dropout = 0.3   # Change 8: classification head dropout
    model.config.dropout = 0.2               # Change 8: transformer layer dropout

    # ── Stratified 70/15/15 split (Change 1) ──────────────────────────────
    all_indices = list(range(len(dataset)))
    all_labels = np.array(dataset.labels)

    if len(dataset) < 10:
        print(f"  ⚠️  Too few samples ({len(dataset)}) for split. Skipping {level_name}.")
        return

    label_counts_for_split = Counter(all_labels.tolist())
    min_class_count = min(label_counts_for_split.values())
    balanced_test_info = None

    if min_class_count < 3:
        # Fallback to random split if a class has <3 samples (can't stratify)
        print(f"  ⚠️  A class has only {min_class_count} samples — using random split")
        train_size = int(0.7 * len(dataset))
        val_size = int(0.15 * len(dataset))
        test_size = len(dataset) - train_size - val_size
        train_dataset, val_dataset, test_dataset = torch.utils.data.random_split(
            dataset, [train_size, val_size, test_size]
        )
    else:
        train_idx, temp_idx = sklearn_split(
            all_indices, test_size=0.30, stratify=all_labels, random_state=42
        )
        temp_labels = all_labels[temp_idx]
        val_idx, test_idx = sklearn_split(
            temp_idx, test_size=0.50, stratify=temp_labels, random_state=42
        )

        # Balanced test set
        test_labels_raw = all_labels[test_idx]
        balanced_test_idx, min_per_class = make_balanced_test_set(
            test_idx, test_labels_raw
        )

        train_dataset = Subset(dataset, train_idx)
        val_dataset = Subset(dataset, val_idx)
        test_dataset = Subset(dataset, balanced_test_idx)

        balanced_test_info = {"min_per_class": min_per_class, "total": len(balanced_test_idx)}

    print(f"  Train: {len(train_dataset)}, Val: {len(val_dataset)}, Test: {len(test_dataset)}")
    if balanced_test_info:
        print(f"  Test set balanced: {balanced_test_info['min_per_class']} samples/class")

    # ── Focal Loss weights (computed on full dataset) ─────────────────────
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

    # ── Differential learning rates (Change 4) ───────────────────────────
    param_groups = [
        {'params': list(model.distilbert.embeddings.parameters()),
         'lr': learning_rate * 0.1},
        {'params': list(model.distilbert.transformer.layer[:3].parameters()),
         'lr': learning_rate * 0.5},
        {'params': list(model.distilbert.transformer.layer[3:].parameters()),
         'lr': learning_rate * 1.0},
    ]
    if hasattr(model, 'pre_classifier'):
        param_groups.append({
            'params': list(model.pre_classifier.parameters()),
            'lr': learning_rate * 2.0,
        })
    param_groups.append({
        'params': list(model.classifier.parameters()),
        'lr': learning_rate * 2.0,
    })

    class FocalTrainer(Trainer):
        def __init__(self, *args, _param_groups=None, **kwargs):
            self._param_groups = _param_groups
            super().__init__(*args, **kwargs)

        def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
            labels = inputs.pop("labels")
            outputs = model(**inputs)
            logits = outputs.logits
            loss = focal_loss_fn(logits, labels)
            return (loss, outputs) if return_outputs else loss

        def create_optimizer(self):
            if self._param_groups is not None:
                self.optimizer = torch.optim.AdamW(
                    self._param_groups, weight_decay=0.01
                )
            else:
                return super().create_optimizer()

    # ── Training arguments (Changes 2, 3, 6) ─────────────────────────────
    training_args = TrainingArguments(
        output_dir=str(out_path),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        warmup_steps=warmup_steps,
        learning_rate=learning_rate,
        weight_decay=0.01,
        label_smoothing_factor=0.1,
        lr_scheduler_type="cosine",              # Change 2
        max_grad_norm=1.0,                       # Change 3
        logging_dir=str(out_path / "logs"),
        logging_steps=50,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=1,
        save_only_model=True,
        load_best_model_at_end=True,
        metric_for_best_model="f1_macro",        # Change 6
        greater_is_better=True,
        report_to="none",
        # MPS: fp16 is CUDA-only; pin_memory causes silent slowdowns on MPS
        fp16=torch.cuda.is_available(),
        dataloader_pin_memory=torch.cuda.is_available(),
    )

    trainer = FocalTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
        _param_groups=param_groups,
    )

    print(f"\n  Starting training (early stopping patience=3, metric=f1_macro)...")
    trainer.train()

    print(f"\n  Saving model to {out_path}")
    trainer.save_model(str(out_path))
    tokenizer.save_pretrained(str(out_path))

    # Save label config for inference
    config = {"label_list": label_list, "level_name": level_name}
    config_path = out_path / "label_config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    # ── VALIDATION SET RESULTS (Change 7) ─────────────────────────────────
    print(f"\n  {'─' * 50}")
    print(f"  📊 VALIDATION SET RESULTS:")
    print(f"  {'─' * 50}")
    val_result = trainer.predict(val_dataset)
    val_preds = np.argmax(val_result.predictions, axis=-1)
    val_true = np.array([val_dataset[i]["labels"].item() for i in range(len(val_dataset))])

    val_present = sorted(set(val_true.tolist()) | set(val_preds.tolist()))
    val_names = [label_list[i] for i in val_present]

    print(classification_report(
        val_true, val_preds,
        labels=val_present, target_names=val_names, zero_division=0,
    ))

    # Save val confusion matrix
    val_cm = confusion_matrix(val_true, val_preds, labels=val_present)
    val_cm_path = out_path / "val_confusion_matrix.txt"
    with open(val_cm_path, "w") as f:
        max_name_len = max(len(n) for n in val_names) if val_names else 10
        header = " " * (max_name_len + 2) + "  ".join(f"{n[:6]:>6}" for n in val_names)
        f.write(f"Validation Confusion Matrix (rows=true, cols=predicted)\n\n{header}\n")
        for i, row in enumerate(val_cm):
            row_str = f"{val_names[i]:<{max_name_len}}  " + "  ".join(f"{v:>6}" for v in row)
            f.write(row_str + "\n")
    print(f"  📋 Val confusion matrix: {val_cm_path}")

    # ── TEST SET RESULTS (Change 7) ───────────────────────────────────────
    print(f"\n  {'─' * 50}")
    print(f"  📊 TEST SET RESULTS (balanced):")
    print(f"  {'─' * 50}")
    test_result = trainer.predict(test_dataset)
    test_preds = np.argmax(test_result.predictions, axis=-1)
    test_true = np.array([test_dataset[i]["labels"].item() for i in range(len(test_dataset))])

    test_present = sorted(set(test_true.tolist()) | set(test_preds.tolist()))
    test_names = [label_list[i] for i in test_present]

    test_report = classification_report(
        test_true, test_preds,
        labels=test_present, target_names=test_names, zero_division=0,
    )
    print(test_report)

    test_acc = accuracy_score(test_true, test_preds)
    test_f1_macro = f1_score(test_true, test_preds, average="macro", zero_division=0)
    test_f1_weighted = f1_score(test_true, test_preds, average="weighted", zero_division=0)

    # Save test evaluation
    test_eval_path = out_path / "test_evaluation.txt"
    test_cm = confusion_matrix(test_true, test_preds, labels=test_present)
    with open(test_eval_path, "w") as f:
        f.write(f"TEST SET EVALUATION (balanced)\n{'=' * 50}\n")
        f.write(f"Accuracy:    {test_acc:.4f}\n")
        f.write(f"F1 Macro:    {test_f1_macro:.4f}\n")
        f.write(f"F1 Weighted: {test_f1_weighted:.4f}\n\n")
        f.write(f"Classification Report:\n{test_report}\n")
        max_name_len = max(len(n) for n in test_names) if test_names else 10
        header = " " * (max_name_len + 2) + "  ".join(f"{n[:6]:>6}" for n in test_names)
        f.write(f"\nConfusion Matrix (rows=true, cols=predicted):\n\n{header}\n")
        for i, row in enumerate(test_cm):
            row_str = f"{test_names[i]:<{max_name_len}}  " + "  ".join(f"{v:>6}" for v in row)
            f.write(row_str + "\n")
    print(f"  📋 Test evaluation: {test_eval_path}")

    # ── MLflow logging for this level ─────────────────────────
    if _MLFLOW_AVAILABLE and mlflow_prefix:
        try:
            pfx = mlflow_prefix
            # Val metrics
            mlflow.log_metrics({
                f"{pfx}/val/accuracy": float(accuracy_score(val_true, val_preds)),
                f"{pfx}/val/f1_weighted": float(f1_score(
                    val_true, val_preds, average="weighted", zero_division=0)),
                f"{pfx}/val/f1_macro": float(f1_score(
                    val_true, val_preds, average="macro", zero_division=0)),
            })
            # Test metrics
            mlflow.log_metrics({
                f"{pfx}/test/accuracy": float(test_acc),
                f"{pfx}/test/f1_macro": float(test_f1_macro),
                f"{pfx}/test/f1_weighted": float(test_f1_weighted),
                f"{pfx}/num_classes": float(len(label_list)),
                f"{pfx}/num_samples": float(len(dataset)),
            })
            # Split sizes
            mlflow.log_metrics({
                f"{pfx}/train_size": float(len(train_dataset)),
                f"{pfx}/val_size": float(len(val_dataset)),
                f"{pfx}/test_size": float(len(test_dataset)),
            })
            if balanced_test_info:
                mlflow.log_metric(
                    f"{pfx}/test_samples_per_class",
                    float(balanced_test_info["min_per_class"]),
                )
            mlflow.log_artifact(str(val_cm_path), artifact_path=f"{pfx}/eval")
            mlflow.log_artifact(str(test_eval_path), artifact_path=f"{pfx}/eval")
            mlflow.log_artifact(str(out_path / "label_config.json"),
                                artifact_path=f"{pfx}/config")
        except Exception as _mlflow_exc:
            print(f"  ⚠️  MLflow logging failed (non-fatal): {_mlflow_exc}")

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
    augment: bool = True,
    mlflow_tracking_uri: str | None = None,
    mlflow_experiment: str = "visual_classifier",
    mlflow_run_name: str | None = None,
):
    """
    Train the full hierarchical classifier.

    Phase 1: Train Level 1 (category) classifier
    Phase 2: Train Level 2 (template) classifiers for each category
    """
    output_base = Path(output_dir)
    output_base.mkdir(parents=True, exist_ok=True)

    # Collect augmentation stats across all levels (Change 9)
    all_augmentation_stats = {}

    # ── MLflow setup ───────────────────────────────────────────
    _mlflow_run = None
    if _MLFLOW_AVAILABLE:
        try:
            if mlflow_tracking_uri:
                mlflow.set_tracking_uri(mlflow_tracking_uri)
            mlflow.set_experiment(mlflow_experiment)
            _mlflow_run = mlflow.start_run(run_name=mlflow_run_name or "train")
            mlflow.log_params({
                "base_model": model_name,
                "max_epochs": epochs,
                "batch_size": batch_size,
                "learning_rate": learning_rate,
                "warmup_steps": warmup_steps,
                "weight_decay": 0.01,
                "label_smoothing": 0.1,
                "loss": "focal_loss",
                "focal_gamma": 2.0,
                "early_stopping_patience": 3,
                "metric_for_best_model": "f1_macro",
                "train_val_test_split": "70/15/15",
                "data_path": str(data_path),
                # Change 2
                "lr_scheduler_type": "cosine",
                # Change 3
                "max_grad_norm": 1.0,
                # Change 4 — differential LR multipliers
                "lr_embeddings": learning_rate * 0.1,
                "lr_lower_transformer": learning_rate * 0.5,
                "lr_upper_transformer": learning_rate * 1.0,
                "lr_pre_classifier": learning_rate * 2.0,
                "lr_classifier_head": learning_rate * 2.0,
                # Change 5
                "augmentation_enabled": augment,
                "augmentation_threshold": AUGMENTATION_THRESHOLD,
                "augmentation_replace_prob": AUGMENTATION_REPLACE_PROB,
                # Change 8
                "transformer_dropout": 0.2,
                "classifier_dropout": 0.3,
            })
            print(f"\n📊 MLflow run started: {_mlflow_run.info.run_id}")
            print(f"   Experiment: {mlflow_experiment}")
        except Exception as _e:
            print(f"  ⚠️  MLflow setup failed (non-fatal): {_e}")
            _mlflow_run = None

    tokenizer = DistilBertTokenizer.from_pretrained(model_name)

    try:
        # -------------------------------------------------------
        # PHASE 1: Train Level 1 (Category Classifier)
        # -------------------------------------------------------
        print("\n" + "█" * 70)
        print("PHASE 1: LEVEL 1 — CATEGORY CLASSIFIER")
        print("█" * 70)

        l1_dataset = HierarchicalDataset(
            data_path, tokenizer, level="category", augment=augment
        )
        if l1_dataset.augmentation_stats:
            all_augmentation_stats["level1"] = l1_dataset.augmentation_stats
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
            mlflow_prefix="level1" if _mlflow_run else None,
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

            l2_dataset = HierarchicalDataset(
                data_path, tokenizer, level=category, augment=augment
            )
            if l2_dataset.augmentation_stats:
                all_augmentation_stats[f"level2/{category}"] = l2_dataset.augmentation_stats

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
                mlflow_prefix=f"level2/{category}" if _mlflow_run else None,
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

        # ── Log summary params + augmentation stats to MLflow ───
        if _MLFLOW_AVAILABLE and _mlflow_run:
            try:
                mlflow.log_params({
                    "trained_level2_categories": ",".join(trained_categories),
                    "skipped_level2_categories": ",".join(skipped_categories),
                    "level1/num_categories": len(CATEGORY_LIST),
                })
                mlflow.log_artifact(str(config_path), artifact_path="config")

                # Change 9: Save augmentation stats artifact
                if all_augmentation_stats:
                    aug_stats_path = output_base / "augmentation_stats.json"
                    with open(aug_stats_path, "w") as f:
                        json.dump(all_augmentation_stats, f, indent=2)
                    mlflow.log_artifact(str(aug_stats_path), artifact_path="config")
                    # Also log individual counts
                    for level_key, stats in all_augmentation_stats.items():
                        for cls_name, cls_stats in stats.items():
                            safe_key = f"{level_key}/aug_{cls_name}"
                            mlflow.log_metric(safe_key, float(cls_stats["augmented"]))
            except Exception as _e:
                print(f"  ⚠️  MLflow final logging failed (non-fatal): {_e}")

        print(f"\n\n{'=' * 70}")
        print("TRAINING COMPLETE")
        print(f"{'=' * 70}")
        print(f"  Level 1 model:  {output_base / 'level1'}")
        print(f"  Level 2 models: {', '.join(trained_categories) or '(none)'}")
        print(f"  Skipped:        {', '.join(skipped_categories) or '(none)'}")
        print(f"  Config:         {config_path}")
        if all_augmentation_stats:
            print(f"  Augmentation:   {output_base / 'augmentation_stats.json'}")
        if _MLFLOW_AVAILABLE and _mlflow_run:
            print(f"  MLflow run ID:  {_mlflow_run.info.run_id}")
            print(f"  View results:   mlflow ui --port 5000")
        print(f"\nDone!")

    finally:
        # Always end the MLflow run, even on error
        if _MLFLOW_AVAILABLE and _mlflow_run:
            try:
                mlflow.end_run()
            except Exception:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train hierarchical visual classifier")
    parser.add_argument("--data", "-d", required=True, help="Path to classifier_train.jsonl")
    parser.add_argument("--output", "-o", default="models/visual_classifier/",
                        help="Output directory for models")
    parser.add_argument("--model", "-m", default="distilbert-base-uncased", help="Base model")
    parser.add_argument("--epochs", type=int, default=30, help="Max training epochs")
    parser.add_argument("--batch-size", type=int, default=16, help="Batch size")
    parser.add_argument("--lr", type=float, default=2e-5, help="Learning rate")
    parser.add_argument("--no-augment", action="store_true",
                        help="Disable synonym augmentation for rare classes")
    parser.add_argument("--mlflow-uri", default=None,
                        help="MLflow tracking URI (default: local mlruns/)")
    parser.add_argument("--mlflow-experiment", default="visual_classifier",
                        help="MLflow experiment name")
    parser.add_argument("--mlflow-run-name", default=None,
                        help="Human-readable name for this MLflow run")

    args = parser.parse_args()
    train(
        args.data, args.output, args.model, args.epochs, args.batch_size, args.lr,
        augment=not args.no_augment,
        mlflow_tracking_uri=args.mlflow_uri,
        mlflow_experiment=args.mlflow_experiment,
        mlflow_run_name=args.mlflow_run_name,
    )

