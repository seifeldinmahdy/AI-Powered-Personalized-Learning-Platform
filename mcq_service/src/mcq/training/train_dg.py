"""Train the Distractor Generation (DG) LoRA adapter on Llama 3.2 3B.

Fine-tunes ``unsloth/Llama-3.2-3B-Instruct`` with LoRA via Unsloth and
TRL's SFTTrainer.  Saves only the LoRA adapter weights (~50-150MB).

# THESIS NOTE: Both the QG and DG models use the same frozen Llama 3.2 3B
# base model with separate task-specific LoRA adapters. This demonstrates
# parameter-efficient multi-task adaptation — one base model, two
# specialized capabilities, total additional parameters approximately
# 0.1% of base model size per adapter.

Usage::

    python -m mcq.training.train_dg \\
        --data data/mcq_training/dg_train.jsonl \\
        --output models/mcq_dg/ \\
        --base-model unsloth/Llama-3.2-3B-Instruct \\
        --epochs 2 \\
        --batch-size 8 \\
        --rank 16
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TRAINING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

TRAIN_CONFIG = {
    "epochs": 2,
    # batch_size halved + grad_accum doubled to keep effective batch = 4 * 4 = 16
    # while fitting 1024-token sequences in T4 VRAM.
    "batch_size": 4,
    "gradient_accumulation_steps": 4,
    "learning_rate": 2e-4,
    "warmup_steps": 10,
    "weight_decay": 0.01,
    "max_grad_norm": 1.0,
    # Raised from 512 → 1024 so the question + correct answer + chunk context
    # are NOT truncated. DG avg sample is ~1150 tokens; 1024 captures ~89%
    # of the content (vs. 44% at 512).
    "max_seq_length": 1024,
    "lora_r": 16,
    "lora_alpha": 16,
    "lora_dropout": 0.0,
    "load_in_4bit": True,
}


# ═══════════════════════════════════════════════════════════════════════════════
# STRATIFIED SPLIT
# ═══════════════════════════════════════════════════════════════════════════════


def _stratified_split(data_path: str, val_ratio: float = 0.1):
    """Shuffle then split data with stratification on combined question_type + mastery.

    Shuffling before splitting ensures that each training batch sees a mixed
    distribution of question types, mastery levels, and source books.  The
    fixed seed makes the split deterministic and reproducible across runs.
    """
    from sklearn.model_selection import train_test_split

    samples = []
    with open(data_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    samples.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    # Shuffle before splitting so the sequential book order in the source
    # file does not bias the train/val split or batch composition.
    random.seed(42)
    random.shuffle(samples)

    if len(samples) < 10:
        split_idx = max(1, int(len(samples) * (1 - val_ratio)))
        return samples[:split_idx], samples[split_idx:]

    labels = [
        f"{s.get('question_type', 'unknown')}_{s.get('mastery_level', 'unknown')}"
        for s in samples
    ]

    # Bucket rare labels to ensure stratification works
    label_counts = defaultdict(int)
    for lb in labels:
        label_counts[lb] += 1

    labels_clean = [
        lb if label_counts[lb] >= 2 else "rare"
        for lb in labels
    ]

    if len(set(labels_clean)) < 2:
        split_idx = max(1, int(len(samples) * (1 - val_ratio)))
        return samples[:split_idx], samples[split_idx:]

    train_samples, val_samples = train_test_split(
        samples, test_size=val_ratio, stratify=labels_clean, random_state=42,
    )
    return train_samples, val_samples


def _write_split(samples: list[dict], path: str):
    """Write samples to a JSONL file."""
    with open(path, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s) + "\n")


# ═══════════════════════════════════════════════════════════════════════════════
# EVALUATION
# ═══════════════════════════════════════════════════════════════════════════════


def _evaluate_generation(
    model,
    tokenizer,
    val_samples: list[dict],
    max_samples: int = 50,
) -> dict:
    """Generate on validation samples, compute ROUGE-L and cosine similarity."""
    import torch
    from rouge_score import rouge_scorer
    from sklearn.metrics.pairwise import cosine_similarity
    from sentence_transformers import SentenceTransformer

    from mcq.prompts.mcq_prompts import (
        build_dg_chat_prompt,
        extract_dg_output,
        format_chat_for_training,
    )

    scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
    embedder = SentenceTransformer("all-MiniLM-L6-v2")

    all_rougeL: list[float] = []
    mastery_cosines: dict[str, list[float]] = defaultdict(list)
    parse_success = 0
    parse_fail = 0

    eval_samples = val_samples[:max_samples]

    for sample in eval_samples:
        # Extract correct answer from the text field via regex
        text_field = sample.get("text", "")
        correct_answer = ""

        # Try to find "Correct answer: ..." in the user message
        match = re.search(r"Correct answer:\s*(.+?)(?:\n|$)", text_field)
        if match:
            correct_answer = match.group(1).strip()

        # Extract reference distractor from the assistant turn
        ref_match = re.search(r"DISTRACTOR:\s*(.+?)(?:\n|$)", text_field)
        ref_distractor = ref_match.group(1).strip() if ref_match else ""

        mastery = sample.get("mastery_level", "unknown")

        # Build prompt (system + user only)
        messages = build_dg_chat_prompt(
            question="",
            correct_answer=correct_answer,
            question_type=sample.get("question_type", "4a"),
            topic="",
            mastery_level=mastery,
            score_category=sample.get("score_category", "moderate"),
        )

        input_text = format_chat_for_training(messages, tokenizer)
        inputs = tokenizer(input_text, return_tensors="pt", truncation=True, max_length=512)
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
        input_len = inputs["input_ids"].shape[1]

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=80,
                temperature=0.0,
                do_sample=False,
            )

        new_tokens = outputs[0][input_len:]
        gen_text = tokenizer.decode(new_tokens, skip_special_tokens=True)

        parsed = extract_dg_output(gen_text)
        if parsed:
            parse_success += 1

            # ROUGE-L against reference distractor
            if ref_distractor:
                scores = scorer.score(ref_distractor, parsed)
                all_rougeL.append(scores["rougeL"].fmeasure)

            # Cosine similarity to correct answer (plausibility metric)
            if correct_answer and parsed:
                embs = embedder.encode(
                    [correct_answer, parsed],
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
                sim = cosine_similarity([embs[0]], [embs[1]])[0][0]
                mastery_cosines[mastery].append(float(sim))
        else:
            parse_fail += 1

    avg = lambda lst: round(np.mean(lst), 4) if lst else 0.0

    return {
        "rougeL": avg(all_rougeL),
        "cosine_sim_per_mastery": {
            m: avg(v) for m, v in sorted(mastery_cosines.items()) if v
        },
        "parse_success": parse_success,
        "parse_fail": parse_fail,
        "num_evaluated": len(eval_samples),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TRAINING LOOP
# ═══════════════════════════════════════════════════════════════════════════════


def train_dg_model(
    data_path: str,
    output_dir: str,
    base_model: str = "unsloth/Llama-3.2-3B-Instruct",
    epochs: int = TRAIN_CONFIG["epochs"],
    batch_size: int = TRAIN_CONFIG["batch_size"],
    learning_rate: float = TRAIN_CONFIG["learning_rate"],
    lora_r: int = TRAIN_CONFIG["lora_r"],
    lora_alpha: int = TRAIN_CONFIG["lora_alpha"],
    lora_dropout: float = TRAIN_CONFIG["lora_dropout"],
    max_seq_length: int = TRAIN_CONFIG["max_seq_length"],
    load_in_4bit: bool = TRAIN_CONFIG["load_in_4bit"],
) -> str:
    """Fine-tune the DG LoRA adapter with Unsloth + SFTTrainer.

    Parameters
    ----------
    data_path :
        Path to formatted dg_train.jsonl.
    output_dir :
        Directory to save LoRA adapter checkpoints.
    base_model :
        Base Llama model identifier.
    epochs :
        Number of training epochs.
    batch_size :
        Per-device training batch size.
    learning_rate :
        Peak learning rate.
    lora_r :
        LoRA rank.
    lora_alpha :
        LoRA alpha scaling factor.
    lora_dropout :
        LoRA dropout rate.
    max_seq_length :
        Maximum sequence length.
    load_in_4bit :
        Whether to use 4-bit quantization (QLoRA).

    Returns
    -------
    str
        Path to saved LoRA adapter directory.
    """
    import torch
    from datasets import Dataset
    from unsloth import FastLanguageModel
    from trl import SFTTrainer, SFTConfig

    start_time = time.time()
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    logger.info(
        "dg_training_start",
        base_model=base_model,
        lora_r=lora_r,
        load_in_4bit=load_in_4bit,
    )

    # ── Load base model with Unsloth ────────────────────────────────
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=base_model,
        max_seq_length=max_seq_length,
        load_in_4bit=load_in_4bit,
    )

    logger.info("dg_base_model_loaded", model=base_model)

    # ── Apply LoRA ──────────────────────────────────────────────────
    model = FastLanguageModel.get_peft_model(
        model,
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=lora_dropout,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )

    logger.info(
        "dg_lora_applied",
        r=lora_r,
        alpha=lora_alpha,
        trainable_params=sum(p.numel() for p in model.parameters() if p.requires_grad),
    )

    # ── Stratified split ────────────────────────────────────────────
    train_samples, val_samples = _stratified_split(data_path)
    train_split_path = str(out_path / "_train_split.jsonl")
    val_split_path = str(out_path / "_val_split.jsonl")
    _write_split(train_samples, train_split_path)
    _write_split(val_samples, val_split_path)

    logger.info(
        "dg_split_complete",
        train=len(train_samples),
        val=len(val_samples),
    )

    # ── Build HuggingFace Datasets ──────────────────────────────────
    train_dataset = Dataset.from_list(train_samples)
    val_dataset = Dataset.from_list(val_samples)

    # ── SFTTrainer configuration ────────────────────────────────────
    training_args = SFTConfig(
        output_dir=str(out_path / "checkpoints"),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=TRAIN_CONFIG["gradient_accumulation_steps"],
        learning_rate=learning_rate,
        warmup_steps=TRAIN_CONFIG["warmup_steps"],
        weight_decay=TRAIN_CONFIG["weight_decay"],
        max_grad_norm=TRAIN_CONFIG["max_grad_norm"],
        fp16=not torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False,
        bf16=torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False,
        # eval every 300 optimizer steps; with packing the eval pass is fast.
        eval_strategy="steps",
        eval_steps=300,
        save_strategy="steps",
        save_steps=300,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        logging_steps=10,
        save_total_limit=2,
        report_to="none",
        seed=42,
        max_seq_length=max_seq_length,
        dataset_text_field="text",
        # packing=True pre-tokenises and packs multiple short DG samples into
        # each 1024-token window, eliminating the per-step CPU tokenisation
        # bottleneck that caused the 17 h wall time on Kaggle T4.
        packing=True,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        args=training_args,
    )

    # ── Train ───────────────────────────────────────────────────────
    logger.info("dg_training_loop_starting", epochs=epochs)
    train_result = trainer.train()

    logger.info(
        "dg_training_loop_complete",
        train_loss=round(train_result.training_loss, 4),
    )

    # ── Save LoRA adapter ───────────────────────────────────────────
    adapter_path = str(out_path / "adapter")
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    logger.info("dg_lora_adapter_saved", path=adapter_path)

    # ── Final evaluation with generation ────────────────────────────
    FastLanguageModel.for_inference(model)
    eval_results = _evaluate_generation(model, tokenizer, val_samples, max_samples=50)

    elapsed = round(time.time() - start_time, 1)

    # ── Save metrics ────────────────────────────────────────────────
    metrics = {
        "base_model": base_model,
        "epochs": epochs,
        "batch_size": batch_size,
        "learning_rate": learning_rate,
        "lora_r": lora_r,
        "lora_alpha": lora_alpha,
        "lora_dropout": lora_dropout,
        "max_seq_length": max_seq_length,
        "load_in_4bit": load_in_4bit,
        "training_time_seconds": elapsed,
        "train_loss": round(train_result.training_loss, 4),
        "final_eval": eval_results,
        "train_samples": len(train_samples),
        "val_samples": len(val_samples),
    }

    metrics_path = str(out_path / "training_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    # ── Print summary ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("DG LORA TRAINING COMPLETE")
    print("=" * 60)
    print(f"  Base model:        {base_model}")
    print(f"  LoRA rank:         {lora_r}")
    print(f"  Training time:     {elapsed}s")
    print(f"  Train loss:        {round(train_result.training_loss, 4)}")
    print(f"  Final ROUGE-L:     {eval_results['rougeL']}")
    print(f"  Parse success:     {eval_results['parse_success']}/{eval_results['num_evaluated']}")
    print()
    print("  Cosine similarity per mastery (distractor plausibility):")
    for mastery, sim in eval_results.get("cosine_sim_per_mastery", {}).items():
        print(f"    {mastery}: {sim}")
    print()
    print(f"  Adapter saved to:  {adapter_path}")
    print(f"  Metrics saved to:  {metrics_path}")
    print("=" * 60 + "\n")

    logger.info("dg_training_complete", **metrics)
    return adapter_path


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="Fine-tune Llama 3.2 3B with LoRA for MCQ distractor generation.",
    )
    parser.add_argument(
        "--data", required=True,
        help="Path to formatted dg_train.jsonl.",
    )
    parser.add_argument(
        "--output", required=True,
        help="Output directory for LoRA adapter and metrics.",
    )
    parser.add_argument(
        "--base-model", default="unsloth/Llama-3.2-3B-Instruct",
        help="Base Llama model (default: unsloth/Llama-3.2-3B-Instruct).",
    )
    parser.add_argument(
        "--epochs", type=int, default=TRAIN_CONFIG["epochs"],
        help=f"Number of training epochs (default: {TRAIN_CONFIG['epochs']}).",
    )
    parser.add_argument(
        "--batch-size", type=int, default=TRAIN_CONFIG["batch_size"],
        help=f"Per-device batch size (default: {TRAIN_CONFIG['batch_size']}).",
    )
    parser.add_argument(
        "--learning-rate", type=float, default=TRAIN_CONFIG["learning_rate"],
        help=f"Peak learning rate (default: {TRAIN_CONFIG['learning_rate']}).",
    )
    parser.add_argument(
        "--rank", type=int, default=TRAIN_CONFIG["lora_r"],
        help=f"LoRA rank (default: {TRAIN_CONFIG['lora_r']}).",
    )
    args = parser.parse_args()

    train_dg_model(
        data_path=args.data,
        output_dir=args.output,
        base_model=args.base_model,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        lora_r=args.rank,
    )


if __name__ == "__main__":
    main()
