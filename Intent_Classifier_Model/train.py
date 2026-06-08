"""
Training pipeline for DistilBert-CNN Intent Classifier.
Features: discriminative fine-tuning, warmup+cosine LR, early stopping,
comprehensive per-class/epoch metric tracking.
"""

import os
import shutil
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
import pandas as pd
import numpy as np
from tqdm import tqdm
import time
import json
import math
import re
from sklearn.metrics import (
    classification_report, confusion_matrix,
    accuracy_score, precision_recall_fscore_support
)
import warnings
warnings.filterwarnings('ignore')
from pathlib import Path

import wandb

from TinyBert import IntentClassifier, IntentDataset

INTENT_NAMES = ['On-Topic Question', 'Off-Topic Question', 'Emotional-State', 'Pace-Related', 'Repeat/clarification', 'Debugging/Code-Sharing']
DEFAULT_CONFIDENCE_THRESHOLD = 0.65
BASE_DIR = Path(__file__).resolve().parent
REAL_UTTERANCE_PATH = str(BASE_DIR / 'data' / 'real_utterances.csv')


# ─────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────



def normalize_context(ctx: str) -> str:
    """Remove ability field from session context to prevent topic-index leakage."""
    if not isinstance(ctx, str):
        return ''
    # Strip 'ability:...' segment between pipes
    ctx = re.sub(r'\|\s*ability:[^|]+', '', ctx)
    ctx = re.sub(r'\s*\|\s*', ' | ', ctx).strip(' |')
    return ctx


class EarlyStopping:
    def __init__(self, patience=3, min_delta=0.001, verbose=True, mode='min'):
        self.patience = patience
        self.min_delta = min_delta
        self.verbose = verbose
        self.mode = mode  # 'min' for loss, 'max' for F1/accuracy
        self.counter = 0
        self.best_score = None
        self.early_stop = False
        self.best_epoch = 0

    def __call__(self, score, epoch):
        improved = (
            self.best_score is None or
            (self.mode == 'min' and score < self.best_score - self.min_delta) or
            (self.mode == 'max' and score > self.best_score + self.min_delta)
        )
        if improved:
            self.best_score = score
            self.best_epoch = epoch
            self.counter = 0
        else:
            self.counter += 1
            if self.verbose:
                print(f"  Early stopping counter: {self.counter}/{self.patience}")
            if self.counter >= self.patience:
                self.early_stop = True
                if self.verbose:
                    print(f"  [!] Early stopping triggered! Best epoch was {self.best_epoch}")


class WarmupCosineScheduler:
    def __init__(self, optimizer, warmup_steps, total_steps):
        self.optimizer = optimizer
        self.warmup_steps = warmup_steps
        self.total_steps = total_steps
        self.base_lrs = [pg['lr'] for pg in optimizer.param_groups]
        self.current_step = 0

    def step(self):
        self.current_step += 1
        if self.current_step <= self.warmup_steps:
            scale = self.current_step / max(1, self.warmup_steps)
        else:
            progress = (self.current_step - self.warmup_steps) / max(1, self.total_steps - self.warmup_steps)
            scale = 0.5 * (1.0 + math.cos(math.pi * progress))
        for pg, base_lr in zip(self.optimizer.param_groups, self.base_lrs):
            pg['lr'] = base_lr * scale


def load_data(train_path, val_path, test_path):
    train_df = pd.read_csv(train_path)
    val_df = pd.read_csv(val_path)
    test_df = pd.read_csv(test_path)
    return train_df, val_df, test_df


def build_dataset_summary(train_df, val_df, test_df):
    return {
        'train_rows': int(len(train_df)),
        'val_rows': int(len(val_df)),
        'test_rows': int(len(test_df)),
        'train_class_counts': train_df['label'].value_counts().sort_index().to_dict(),
        'val_class_counts': val_df['label'].value_counts().sort_index().to_dict(),
        'test_class_counts': test_df['label'].value_counts().sort_index().to_dict(),
    }


def compute_class_weights(labels, num_classes, device):
    counts = np.bincount(labels, minlength=num_classes).astype(float)
    counts[counts == 0] = 1.0
    weights = 1.0 / counts
    weights = weights / weights.sum() * num_classes
    return torch.tensor(weights, dtype=torch.float32).to(device)


def evaluate_model_full(classifier, loader):
    """Full evaluation returning all metrics."""
    classifier.model.eval()
    all_preds, all_labels = [], []
    total_loss = 0
    criterion = nn.CrossEntropyLoss()

    with torch.no_grad():
        for batch in loader:
            input_ids = batch['input_ids'].to(classifier.device)
            attention_mask = batch['attention_mask'].to(classifier.device)
            labels = batch['labels'].to(classifier.device)
            token_type_ids = batch.get('token_type_ids')
            if token_type_ids is not None:
                token_type_ids = token_type_ids.to(classifier.device)

            logits = classifier.model(input_ids, attention_mask, token_type_ids=token_type_ids)
            loss = criterion(logits, labels)
            total_loss += loss.item() * labels.size(0)

            preds = torch.argmax(logits, dim=1).cpu().numpy()
            all_preds.extend(preds)
            all_labels.extend(labels.cpu().numpy())

    n = len(all_labels)
    avg_loss = total_loss / n
    accuracy = accuracy_score(all_labels, all_preds)
    precision, recall, f1, _ = precision_recall_fscore_support(
        all_labels, all_preds, average='weighted', zero_division=0
    )

    return avg_loss, accuracy, precision, recall, f1, all_preds, all_labels


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────

def main():
    # ── Hyperparameters ─────────────────────────────────────────────
    TRAIN_PATH  = str(BASE_DIR / 'data' / 'train.csv')
    VAL_PATH    = str(BASE_DIR / 'data' / 'val.csv')
    TEST_PATH   = str(BASE_DIR / 'data' / 'test.csv')
    BATCH_SIZE  = 16
    EPOCHS      = 15
    BERT_LR     = 2e-5       # Lower LR for BERT backbone
    HEAD_LR     = 2e-4   # was 5e-5 — head needs to learn faster than backbone
    WEIGHT_DECAY = 0.01
    MAX_LENGTH  = 128
    PATIENCE    = 7
    DROPOUT     = 0.3
    FREEZE_BERT = False

    hyperparams = {
        'batch_size': BATCH_SIZE,
        'epochs': EPOCHS,
        'bert_lr': BERT_LR,
        'head_lr': HEAD_LR,
        'weight_decay': WEIGHT_DECAY,
        'max_length': MAX_LENGTH,
        'patience': PATIENCE,
        'label_smoothing': 0.1,
        'dropout': DROPOUT,
        'freeze_bert': FREEZE_BERT
    }

    print("=" * 60)
    print("DistilBert-CNN Multi-Input Model Training")
    print("=" * 60)

    start_time = time.time()

    # ── Data ────────────────────────────────────────────────────────
    train_df, val_df, test_df = load_data(TRAIN_PATH, VAL_PATH, TEST_PATH)

    # ── Mix real utterances into training ───────────────────────────
    if os.path.exists(REAL_UTTERANCE_PATH):
        real_df = pd.read_csv(REAL_UTTERANCE_PATH)
        real_df = real_df.sample(frac=1, random_state=42).reset_index(drop=True)
        split_idx = int(len(real_df) * 0.70)
        real_train_df = real_df.iloc[:split_idx]
        real_eval_df  = real_df.iloc[split_idx:]
        # Oversample real training data 8x so model learns from it
        real_train_oversampled = pd.concat([real_train_df] * 8, ignore_index=True)
        train_df = pd.concat([train_df, real_train_oversampled], ignore_index=True)
        train_df = train_df.sample(frac=1, random_state=42).reset_index(drop=True)
        print(f"[+] Mixed {len(real_train_oversampled)} real utterance rows into training. Train total: {len(train_df)}")
    else:
        real_eval_df = None

    for df in [train_df, val_df, test_df]:
        df['session_context'] = df['session_context'].apply(normalize_context)
    if real_eval_df is not None:
        real_eval_df['session_context'] = real_eval_df['session_context'].apply(normalize_context)

    num_classes = train_df['label'].nunique()
    print(f"Train: {len(train_df)} | Val: {len(val_df)} | Test: {len(test_df)} | Classes: {num_classes}")
    dataset_summary = build_dataset_summary(train_df, val_df, test_df)

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    classifier = IntentClassifier(
        num_classes=num_classes,
        bert_model_name='distilbert-base-uncased',
        dropout=DROPOUT,
        freeze_bert=FREEZE_BERT,
        device=device
    )
    print(f"Training on device: {device}")

    train_dataset = IntentDataset(train_df.to_dict('records'), classifier.tokenizer, max_length=MAX_LENGTH)
    val_dataset   = IntentDataset(val_df.to_dict('records'),   classifier.tokenizer, max_length=MAX_LENGTH)
    test_dataset  = IntentDataset(test_df.to_dict('records'),  classifier.tokenizer, max_length=MAX_LENGTH)

    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    val_loader   = DataLoader(val_dataset,   batch_size=BATCH_SIZE, shuffle=False)
    test_loader  = DataLoader(test_dataset,  batch_size=BATCH_SIZE, shuffle=False)

    # ── Optimizer with discriminative fine-tuning ───────────────────
    class_weights = compute_class_weights(train_df['label'].values, num_classes, classifier.device)
    criterion = nn.CrossEntropyLoss(label_smoothing=0.1, weight=class_weights)

    bert_params = list(classifier.model.bert.parameters())
    head_params = [p for n, p in classifier.model.named_parameters() if not n.startswith('bert.')]

    optimizer = torch.optim.AdamW([
        {'params': bert_params, 'lr': BERT_LR},
        {'params': head_params, 'lr': HEAD_LR}
    ], weight_decay=WEIGHT_DECAY)

    total_steps = len(train_loader) * EPOCHS
    warmup_steps = int(total_steps * 0.1)
    scheduler = WarmupCosineScheduler(optimizer, warmup_steps, total_steps)
    early_stopping = EarlyStopping(patience=PATIENCE, mode='max')

    best_val_f1 = 0.0
    best_model_path = "best_model.pt"

    # ── Training history ────────────────────────────────────────────
    history = {
        'train_loss': [],
        'val_loss': [],
        'val_acc': [],
        'val_f1': []
    }

    # ── wandb experiment tracking ────────────────────────────────────
    wandb.init(
        project="intent-classifier",
        name=f"distilbert-cnn-{int(time.time())}",
        config={
            **hyperparams,
            'model_name': 'DistilBert-CNN',
            'num_classes': num_classes,
            'train_rows': len(train_df),
            'val_rows': len(val_df),
            'test_rows': len(test_df),
            'total_steps': total_steps,
            'warmup_steps': warmup_steps,
            'confidence_threshold': DEFAULT_CONFIDENCE_THRESHOLD,
            **dataset_summary,
        },
    )

    # ── Training loop ──────────────────────────────────────────────
    for epoch in range(EPOCHS):
        classifier.model.train()
        train_loss = 0
        train_pbar = tqdm(train_loader, desc=f"Epoch {epoch+1}/{EPOCHS}")

        for batch in train_pbar:
            loss = classifier.train_step(batch, optimizer, criterion)
            scheduler.step()
            train_loss += loss
            train_pbar.set_postfix({'loss': f'{loss:.4f}'})

        avg_train_loss = train_loss / len(train_loader)
        val_loss, val_acc, val_prec, val_rec, val_f1, all_preds, all_labels = evaluate_model_full(classifier, val_loader)

        history['train_loss'].append(round(avg_train_loss, 4))
        history['val_loss'].append(round(val_loss, 4))
        history['val_acc'].append(round(val_acc, 4))
        history['val_f1'].append(round(val_f1, 4))

        print(f"Epoch {epoch+1}: Train Loss: {avg_train_loss:.4f} | Val Loss: {val_loss:.4f} | Val Acc: {val_acc:.4f} | Val F1: {val_f1:.4f}")

        # ── wandb per-epoch logging ──────────────────────────────────
        metrics_to_log = {
            'epoch': epoch + 1,
            'train_loss': float(avg_train_loss),
            'val_loss': float(val_loss),
            'val_accuracy': float(val_acc),
            'val_precision': float(val_prec),
            'val_recall': float(val_rec),
            'val_f1': float(val_f1),
        }
        
        # Compute per-class F1
        _, _, per_class_f1, _ = precision_recall_fscore_support(
            all_labels, all_preds, average=None, zero_division=0
        )
        for i, name in enumerate(INTENT_NAMES):
            if i < len(per_class_f1):
                safe_name = name.replace(" ", "_").replace("/", "_")
                metrics_to_log[f'val_f1_{safe_name}'] = float(per_class_f1[i])

        wandb.log(metrics_to_log)

        if val_f1 > best_val_f1:
            best_val_f1 = val_f1
            classifier.save_model(best_model_path)
            print(f"  [+] Best model saved with F1: {val_f1:.4f}")

        early_stopping(val_f1, epoch + 1)
        if early_stopping.early_stop:
            print("Stopping early.")
            break

    # ── Final evaluation on TEST set ────────────────────────────────
    classifier.load_model(best_model_path)
    test_loss, test_acc, test_prec, test_rec, test_f1, all_preds, all_labels = evaluate_model_full(classifier, test_loader)

    training_duration = round(time.time() - start_time, 2)

    # Per-class metrics
    per_class_p, per_class_r, per_class_f1, per_class_support = precision_recall_fscore_support(
        all_labels, all_preds, average=None, zero_division=0
    )
    per_class_metrics = {}
    for i, name in enumerate(INTENT_NAMES):
        per_class_metrics[name] = {
            'precision': round(float(per_class_p[i]), 4),
            'recall': round(float(per_class_r[i]), 4),
            'f1_score': round(float(per_class_f1[i]), 4),
            'support': int(per_class_support[i])
        }

    # Confusion matrix
    cm = confusion_matrix(all_labels, all_preds).tolist()

    # Classification report
    cls_report = classification_report(all_labels, all_preds, target_names=INTENT_NAMES, zero_division=0)

    # ── Save results ───────────────────────────────────────────────
    results = {
        'model': 'DistilBert-CNN',
        'confidence_threshold': DEFAULT_CONFIDENCE_THRESHOLD,
        'dataset_summary': dataset_summary,
        'hyperparameters': hyperparams,
        'training_duration_seconds': training_duration,
        'epochs_trained': len(history['train_loss']),
        'metrics': {
            'accuracy': round(test_acc, 4),
            'f1_score': round(test_f1, 4),
            'precision': round(test_prec, 4),
            'recall': round(test_rec, 4),
            'test_loss': round(test_loss, 4)
        },
        'per_class_metrics': per_class_metrics,
        'confusion_matrix': cm,
        'training_history': history,
        'classification_report': cls_report
    }

    # ── Real-utterance evaluation split ─────────────────────────────
    if os.path.exists(REAL_UTTERANCE_PATH):
        print(f"\n{'='*60}")
        print("REAL-UTTERANCE EVALUATION")
        print(f"{'='*60}")
        try:
            if real_eval_df is None or len(real_eval_df) == 0:
                print("[!] No real eval split available — skipping.")
                raise ValueError("Skip")
            real_df = real_eval_df
            real_dataset = IntentDataset(
                real_df.to_dict('records'), classifier.tokenizer, max_length=MAX_LENGTH
            )
            real_loader = DataLoader(real_dataset, batch_size=BATCH_SIZE, shuffle=False)
            (
                real_loss, real_acc, real_prec, real_rec, real_f1,
                real_preds, real_labels,
            ) = evaluate_model_full(classifier, real_loader)

            real_per_class_p, real_per_class_r, real_per_class_f1, real_support = (
                precision_recall_fscore_support(
                    real_labels, real_preds, average=None, zero_division=0
                )
            )
            real_per_class = {}
            for i, name in enumerate(INTENT_NAMES):
                if i < len(real_per_class_f1):
                    real_per_class[name] = {
                        'precision': round(float(real_per_class_p[i]), 4),
                        'recall': round(float(real_per_class_r[i]), 4),
                        'f1_score': round(float(real_per_class_f1[i]), 4),
                        'support': int(real_support[i]),
                    }

            real_cls_report = classification_report(
                real_labels, real_preds, target_names=INTENT_NAMES, zero_division=0
            )

            results['real_utterance_metrics'] = {
                'accuracy': round(real_acc, 4),
                'f1_score': round(real_f1, 4),
                'precision': round(real_prec, 4),
                'recall': round(real_rec, 4),
                'test_loss': round(real_loss, 4),
            }
            results['real_utterance_per_class'] = real_per_class
            results['real_utterance_report'] = real_cls_report

            print(f"Real Acc: {real_acc:.4f} | Real F1: {real_f1:.4f}")
            print(f"\nPer-class (real utterances):")
            print(real_cls_report)
        except Exception as e:
            print(f"[!] Real-utterance eval failed: {e}")
    else:
        print(f"\n[!] No real utterance file at {REAL_UTTERANCE_PATH} — skipping.")

    with open('training_results.json', 'w') as f:
        json.dump(results, f, indent=4)

    # ── wandb final logging ──────────────────────────────────────────
    wandb.log({
        'test_loss': float(test_loss),
        'test_accuracy': float(test_acc),
        'test_precision': float(test_prec),
        'test_recall': float(test_rec),
        'test_f1': float(test_f1),
        'training_duration_seconds': float(training_duration),
        'epochs_trained': float(len(history['train_loss'])),
    })
    wandb.save('training_results.json')
    if os.path.exists(best_model_path):
        wandb.save(best_model_path)
    wandb.finish()

    print(f"\n{'='*60}")
    print(f"TRAINING COMPLETE  ({training_duration:.1f}s)")
    print(f"{'='*60}")
    print(f"Test Acc: {test_acc:.4f} | Test F1: {test_f1:.4f} | Test Loss: {test_loss:.4f}")
    print(f"Confidence threshold: {DEFAULT_CONFIDENCE_THRESHOLD}")
    print(f"\nPer-class results (synthetic test):")
    print(cls_report)
    print(f"Confusion Matrix:")
    for row in cm:
        print(f"  {row}")
    print(f"\n[+] Results saved to 'training_results.json'")


if __name__ == '__main__':
    main()
