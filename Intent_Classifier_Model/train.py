"""
Training pipeline for DistilBert-CNN Intent Classifier.
Features: discriminative fine-tuning, warmup+cosine LR, early stopping,
comprehensive per-class/epoch metric tracking.
"""

import os
import random
import argparse
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torch.cuda.amp import GradScaler
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
DEFAULT_REAL_UTTERANCE_PATH = str(BASE_DIR / 'data' / 'real_utterances.csv')


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
    # ── Reproducibility ──────────────────────────────────────────────────────────
    torch.manual_seed(42)
    random.seed(42)
    np.random.seed(42)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(42)
    # ─────────────────────────────────────────────────────────────────────────────
    # ── CLI / env overrides ─────────────────────────────────────────
    parser = argparse.ArgumentParser()
    parser.add_argument('--train-csv', default=os.getenv('INTENT_TRAIN_CSV', str(BASE_DIR / 'data' / 'train.csv')))
    parser.add_argument('--val-csv', default=os.getenv('INTENT_VAL_CSV', str(BASE_DIR / 'data' / 'val.csv')))
    parser.add_argument('--test-csv', default=os.getenv('INTENT_TEST_CSV', str(BASE_DIR / 'data' / 'test.csv')))
    parser.add_argument('--best-model-path', default=os.getenv('INTENT_BEST_MODEL_PATH', 'best_model.pt'))
    parser.add_argument('--results-path', default=os.getenv('INTENT_RESULTS_PATH', 'training_results.json'))
    parser.add_argument('--feedback-test-csv', default=os.getenv('INTENT_FEEDBACK_TEST_CSV', ''))
    parser.add_argument('--real-utterance-csv', default=os.getenv('INTENT_REAL_UTTERANCE_CSV', DEFAULT_REAL_UTTERANCE_PATH))
    parser.add_argument('--held-out-domain-test-csv', default=os.getenv('INTENT_HELD_OUT_DOMAIN_TEST_CSV', str(BASE_DIR / 'data' / 'test_held_out_domain.csv')))
    args = parser.parse_args()

    # ── Hyperparameters ─────────────────────────────────────────────
    TRAIN_PATH  = args.train_csv
    VAL_PATH    = args.val_csv
    TEST_PATH   = args.test_csv
    best_model_path = args.best_model_path
    BATCH_SIZE  = 32
    EPOCHS      = 20
    BERT_LR     = 2e-5       # Lower LR for BERT backbone
    HEAD_LR     = 2e-4   # was 5e-5 — head needs to learn faster than backbone
    WEIGHT_DECAY = 0.01
    MAX_LENGTH  = 128
    PATIENCE    = 4
    DROPOUT     = 0.2
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
    real_utterance_path = args.real_utterance_csv
    real_eval_df = None
    if os.path.exists(real_utterance_path):
        try:
            real_df = pd.read_csv(real_utterance_path)
            real_df = real_df.sample(frac=1, random_state=42).reset_index(drop=True)
            split_idx = int(len(real_df) * 0.70)
            real_train_df = real_df.iloc[:split_idx]
            real_eval_df  = real_df.iloc[split_idx:]
            # Oversample real training data 2x so model learns from it
            real_train_oversampled = pd.concat([real_train_df] * 2, ignore_index=True)
            train_df = pd.concat([train_df, real_train_oversampled], ignore_index=True)
            train_df = train_df.sample(frac=1, random_state=42).reset_index(drop=True)
            print(f"[+] Mixed {len(real_train_oversampled)} real utterance rows from {real_utterance_path} into training. Train total: {len(train_df)}")
            print(f"[+] Real eval split size: {len(real_eval_df)}")
        except Exception as exc:
            print(f"[!] Failed to load real utterances from {real_utterance_path}: {exc}")
            real_eval_df = None
    else:
        print(f"[!] No real utterance file at {real_utterance_path} — training without real data.")

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
        num_filters=192,
        filter_sizes=[3, 4, 5, 6],
        dropout=DROPOUT,
        freeze_bert=FREEZE_BERT,
        device=device
    )
    print(f"Training on device: {device}")

    import logging
    logger = logging.getLogger(__name__)
    # ── GroupNorm verification ────────────────────────────────────────────────────
    norm_types = {}
    for name, module in classifier.model.named_modules():
        t = type(module).__name__
        if t in ('BatchNorm1d', 'GroupNorm', 'LayerNorm'):
            norm_types[name] = t
    
    if any(t == 'BatchNorm1d' for t in norm_types.values()):
        logger.warning(
            "BatchNorm1d detected in model. GroupNorm should have replaced it. "
            "Layers: %s",
            {k: v for k, v in norm_types.items() if v == 'BatchNorm1d'},
        )
    else:
        logger.info("GroupNorm confirmed — no BatchNorm layers found. Norm types: %s",
                    set(norm_types.values()))
    # ─────────────────────────────────────────────────────────────────────────────

    train_dataset = IntentDataset(train_df.to_dict('records'), classifier.tokenizer, max_length=MAX_LENGTH)
    val_dataset   = IntentDataset(val_df.to_dict('records'),   classifier.tokenizer, max_length=MAX_LENGTH)
    test_dataset  = IntentDataset(test_df.to_dict('records'),  classifier.tokenizer, max_length=MAX_LENGTH)

    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    val_loader   = DataLoader(val_dataset,   batch_size=BATCH_SIZE, shuffle=False)
    test_loader  = DataLoader(test_dataset,  batch_size=BATCH_SIZE, shuffle=False)

    # ── Optimizer with discriminative fine-tuning ───────────────────
    class_weights = compute_class_weights(train_df['label'].values, num_classes, classifier.device)
    label_smoothing = 0.1
    criterion = nn.CrossEntropyLoss(label_smoothing=label_smoothing, weight=class_weights)

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

    # ── Training history ────────────────────────────────────────────
    history = {
        'train_loss': [],
        'train_acc': [],
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
            'filter_sizes': [3, 4, 5, 6],
            'num_filters': 192,
            'norm_type': 'GroupNorm',
            'dropout_layers': 1,
            'train_rows': len(train_df),
            'val_rows': len(val_df),
            'test_rows': len(test_df),
            'total_steps': total_steps,
            'warmup_steps': warmup_steps,
            'confidence_threshold': DEFAULT_CONFIDENCE_THRESHOLD,
            **dataset_summary,
        },
    )

    class _LoopState:
        restart_count: int = 0
    _state = _LoopState()

    # ── Temperature scaling on validation set ──────────────────────
    def fit_temperature(clf, v_loader, max_iter=50):
        '''Fit temperature parameter T to minimize NLL on validation set.'''
        clf.model.eval()
        # Collect validation logits and labels
        all_logits, all_labels = [], []
        with torch.no_grad():
            for batch in v_loader:
                input_ids = batch['input_ids'].to(clf.device)
                attention_mask = batch['attention_mask'].to(clf.device)
                labels_b = batch['labels'].to(clf.device)
                token_type_ids = batch.get('token_type_ids')
                if token_type_ids is not None:
                    token_type_ids = token_type_ids.to(clf.device)
                logits = clf.model(input_ids, attention_mask, token_type_ids=token_type_ids)
                # Undo any existing temperature
                logits = logits * clf.model.temperature
                all_logits.append(logits)
                all_labels.append(labels_b)
        all_logits = torch.cat(all_logits)
        all_labels = torch.cat(all_labels)
        
        # Optimize T via grid search + fine refinement
        best_T, best_nll = 1.0, float('inf')
        for T in [0.5, 0.7, 1.0, 1.3, 1.6, 2.0, 2.5, 3.0, 4.0, 5.0]:
            scaled = all_logits / T
            nll = nn.CrossEntropyLoss()(scaled, all_labels).item()
            if nll < best_nll:
                best_nll, best_T = nll, T
        
        # Fine search around best
        for T in [best_T - 0.3, best_T - 0.15, best_T, best_T + 0.15, best_T + 0.3]:
            if T <= 0: continue
            scaled = all_logits / T
            nll = nn.CrossEntropyLoss()(scaled, all_labels).item()
            if nll < best_nll:
                best_nll, best_T = nll, T
        
        clf.model.temperature = best_T
        print(f"[+] Temperature fitted: T={best_T:.3f} (val NLL={best_nll:.4f})")
        return best_T

    # ── Training loop (AMP) ─────────────────────────────────────────
    scaler = GradScaler()
    for epoch in range(EPOCHS):
        classifier.model.train()
        train_loss = 0
        train_pbar = tqdm(train_loader, desc=f"Epoch {epoch+1}/{EPOCHS}")
        train_correct = 0
        train_total = 0

        for batch in train_pbar:
            loss, correct, total = classifier.train_step_amp(batch, optimizer, criterion, scaler=scaler)
            scheduler.step()
            train_loss += loss
            train_correct += correct
            train_total += total
            train_pbar.set_postfix({
                'loss': f'{loss:.4f}',
                'acc':  f'{train_correct / train_total:.4f}',
            })

        avg_train_loss = train_loss / len(train_loader)
        train_acc = train_correct / train_total
        val_loss, val_acc, val_prec, val_rec, val_f1, all_preds, all_labels = evaluate_model_full(classifier, val_loader)

        history['train_loss'].append(round(avg_train_loss, 4))
        history['train_acc'].append(round(train_acc, 4))
        history['val_loss'].append(round(val_loss, 4))
        history['val_acc'].append(round(val_acc, 4))
        history['val_f1'].append(round(val_f1, 4))

        print(f"Epoch {epoch+1}: Train Loss: {avg_train_loss:.4f} | Train Acc: {train_acc:.4f} | Val Loss: {val_loss:.4f} | Val Acc: {val_acc:.4f} | Val F1: {val_f1:.4f}")

        # ── wandb per-epoch logging ──────────────────────────────────
        metrics_to_log = {
            'epoch': epoch + 1,
            'train_loss': float(avg_train_loss),
            'train_accuracy': float(train_acc),
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
            MAX_RESTARTS = 2

            if _state.restart_count >= MAX_RESTARTS:
                print(f"Early stopping — {MAX_RESTARTS} restarts exhausted. Terminating at epoch {epoch + 1}.")
                break

            best_epoch = early_stopping.best_epoch
            print(f"Early stopping at epoch {epoch + 1} — rewinding to epoch {best_epoch} (best val_f1={best_val_f1:.4f})")

            # 1. Rewind to best checkpoint
            classifier.load_model(best_model_path)

            # 2. Calibrate temperature
            temperature = fit_temperature(classifier, val_loader)
            classifier.model.temperature = temperature
            print(f"Temperature recalibrated: T={temperature:.4f}")

            # 3. Halve learning rates
            for pg in optimizer.param_groups:
                pg['lr'] = pg['lr'] * 0.5
            print(f"LRs halved — BERT: {optimizer.param_groups[0]['lr']:.2e}  HEAD: {optimizer.param_groups[-1]['lr']:.2e}")

            # 4. Reduce label smoothing
            label_smoothing = max(label_smoothing * 0.5, 0.01)
            criterion = nn.CrossEntropyLoss(label_smoothing=label_smoothing,
                                            weight=class_weights)
            logger.info("Label smoothing reduced to %.3f — criterion recreated", label_smoothing)

            # 5. Reset scheduler with short warmup from new lower LR
            remaining = EPOCHS - (epoch + 1)
            warmup    = min(200, remaining * len(train_loader) // 10)
            scheduler = WarmupCosineScheduler(
                optimizer,
                warmup_steps=warmup,
                total_steps=remaining * len(train_loader),
            )
            print(f"Scheduler reset — {warmup} warmup / {remaining * len(train_loader)} total steps")

            # 6. Reset early stopping counter and flag
            early_stopping.counter    = 0
            early_stopping.early_stop = False

            _state.restart_count += 1
            print(f"Restart {_state.restart_count} / {MAX_RESTARTS} — continuing training.")


    # ── Final evaluation on TEST set ────────────────────────────────
    classifier.load_model(best_model_path)
    best_T = fit_temperature(classifier, val_loader)
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
        'classification_report': cls_report,
        'real_utterance_metrics': None,
        'real_utterance_per_class': None,
        'real_utterance_report': None,
        'feedback_test_metrics': None,
        'model_checkpoint_path': None,
    }

    # ── Real-utterance evaluation split ─────────────────────────────
    print(f"\n{'='*60}")
    print("REAL-UTTERANCE EVALUATION")
    print(f"{'='*60}")
    print(f"Looking for real utterances at: {real_utterance_path}")
    print(f"Real eval split available: {real_eval_df is not None and len(real_eval_df) > 0}")

    if os.path.exists(real_utterance_path):
        if real_eval_df is None or len(real_eval_df) == 0:
            print("[!] Real utterance file exists but eval split is empty — skipping eval.")
            results['real_utterance_metrics'] = {
                'error': 'Real eval split is empty (file loaded but no eval rows)',
            }
        else:
            try:
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
                print("\nPer-class (real utterances):")
                print(real_cls_report)
            except Exception as e:
                print(f"[!] Real-utterance eval failed: {e}")
                results['real_utterance_metrics'] = {'error': str(e)}
    else:
        print(f"[!] No real utterance file at {real_utterance_path} — skipping.")
        results['real_utterance_metrics'] = {
            'error': f'No real utterance file at {real_utterance_path}',
        }

    # ── Feedback test-set evaluation ────────────────────────────────
    feedback_test_metrics = None
    if args.feedback_test_csv and os.path.exists(args.feedback_test_csv):
        print(f"\n{'='*60}")
        print("FEEDBACK TEST-SET EVALUATION")
        print(f"{'='*60}")
        try:
            fb_test_df = pd.read_csv(args.feedback_test_csv)
            fb_test_df['session_context'] = fb_test_df['session_context'].apply(normalize_context)
            fb_dataset = IntentDataset(fb_test_df.to_dict('records'), classifier.tokenizer, max_length=MAX_LENGTH)
            fb_loader = DataLoader(fb_dataset, batch_size=BATCH_SIZE, shuffle=False)
            fb_loss, fb_acc, fb_prec, fb_rec, fb_f1, fb_preds, fb_labels = evaluate_model_full(classifier, fb_loader)

            fb_per_class_p, fb_per_class_r, fb_per_class_f1, fb_support = precision_recall_fscore_support(
                fb_labels, fb_preds, average=None, zero_division=0
            )
            fb_per_class = {}
            for i, name in enumerate(INTENT_NAMES):
                if i < len(fb_per_class_f1):
                    fb_per_class[name] = {
                        'precision': round(float(fb_per_class_p[i]), 4),
                        'recall': round(float(fb_per_class_r[i]), 4),
                        'f1_score': round(float(fb_per_class_f1[i]), 4),
                        'support': int(fb_support[i]),
                    }

            feedback_test_metrics = {
                'accuracy': round(fb_acc, 4),
                'f1_score': round(fb_f1, 4),
                'precision': round(fb_prec, 4),
                'recall': round(fb_rec, 4),
                'test_loss': round(fb_loss, 4),
                'per_class': fb_per_class,
            }
            results['feedback_test_metrics'] = feedback_test_metrics
            print(f"Feedback Test Acc: {fb_acc:.4f} | F1: {fb_f1:.4f}")
        except Exception as e:
            print(f"[!] Feedback test eval failed: {e}")

    # ── Held-out-domain evaluation ──────────────────────────────────
    held_out_domain_metrics = None
    if os.path.exists(args.held_out_domain_test_csv):
        print(f"\n{'='*60}")
        print("HELD-OUT-DOMAIN EVALUATION")
        print(f"{'='*60}")
        try:
            hod_test_df = pd.read_csv(args.held_out_domain_test_csv)
            hod_test_df['session_context'] = hod_test_df['session_context'].apply(normalize_context)
            hod_dataset = IntentDataset(hod_test_df.to_dict('records'), classifier.tokenizer, max_length=MAX_LENGTH)
            hod_loader = DataLoader(hod_dataset, batch_size=BATCH_SIZE, shuffle=False)
            hod_loss, hod_acc, hod_prec, hod_rec, hod_f1, hod_preds, hod_labels = evaluate_model_full(classifier, hod_loader)

            hod_per_class_p, hod_per_class_r, hod_per_class_f1, hod_support = precision_recall_fscore_support(
                hod_labels, hod_preds, average=None, zero_division=0
            )
            hod_per_class = {}
            for i, name in enumerate(INTENT_NAMES):
                if i < len(hod_per_class_f1):
                    hod_per_class[name] = {
                        'precision': round(float(hod_per_class_p[i]), 4),
                        'recall': round(float(hod_per_class_r[i]), 4),
                        'f1_score': round(float(hod_per_class_f1[i]), 4),
                        'support': int(hod_support[i]),
                    }

            held_out_domain_metrics = {
                'accuracy': round(hod_acc, 4),
                'f1_score': round(hod_f1, 4),
                'precision': round(hod_prec, 4),
                'recall': round(hod_rec, 4),
                'test_loss': round(hod_loss, 4),
                'per_class': hod_per_class,
            }
            results['held_out_domain_metrics'] = held_out_domain_metrics
            print(f"Held-Out-Domain Acc: {hod_acc:.4f} | F1: {hod_f1:.4f}")
        except Exception as e:
            print(f"[!] Held-out-domain eval failed: {e}")
            results['held_out_domain_metrics'] = {'error': str(e)}
    else:
        print(f"\n[!] No held-out-domain test file at {args.held_out_domain_test_csv} — skipping.")
        results['held_out_domain_metrics'] = {
            'error': f'No held-out-domain test file at {args.held_out_domain_test_csv}',
        }

    # ── Verify checkpoint exists and record path ────────────────────
    if os.path.exists(best_model_path):
        results['model_checkpoint_path'] = str(Path(best_model_path).resolve())
        print(f"[+] Model checkpoint saved at: {best_model_path}")
    else:
        print(f"[!] Expected checkpoint not found at {best_model_path}")

    # ── Promotion gate ──────────────────────────────────────────────
    real_f1 = None
    if isinstance(results.get('real_utterance_metrics'), dict):
        real_f1 = results['real_utterance_metrics'].get('f1_score')
    hod_acc_val = None
    if isinstance(results.get('held_out_domain_metrics'), dict):
        hod_acc_val = results['held_out_domain_metrics'].get('accuracy')

    results['promotion_ready'] = (
        isinstance(real_f1, (int, float)) and real_f1 >= 0.75
        and isinstance(hod_acc_val, (int, float)) and hod_acc_val >= 0.70
    )
    if results['promotion_ready']:
        print(f"\n[READY] Real-utterance F1 {real_f1:.4f} >= 0.75 and held-out-domain acc {hod_acc_val:.4f} >= 0.70 — model is eligible for promotion.")
    else:
        print(f"\n[NOT READY] real_f1={real_f1}, held_out_domain_acc={hod_acc_val} — do not promote yet.")

    with open(args.results_path, 'w') as f:
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
        'temperature': float(best_T),
    })
    wandb.save(args.results_path)
    if os.path.exists(best_model_path):
        wandb.save(best_model_path)
    wandb.finish()

    print(f"\n{'='*60}")
    print(f"TRAINING COMPLETE  ({training_duration:.1f}s)")
    print(f"{'='*60}")
    print(f"Test Acc: {test_acc:.4f} | Test F1: {test_f1:.4f} | Test Loss: {test_loss:.4f}")
    print(f"Confidence threshold: {DEFAULT_CONFIDENCE_THRESHOLD}")
    print("\nPer-class results (synthetic test):")
    print(cls_report)
    print("Confusion Matrix:")
    for row in cm:
        print(f"  {row}")
    print("\n[+] Results saved to 'training_results.json'")


if __name__ == '__main__':
    main()
