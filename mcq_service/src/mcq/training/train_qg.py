"""Train the Question Generation (QG) LoRA adapter on Qwen3-4B-Instruct.

Fine-tunes ``unsloth/Qwen3-4B-Instruct`` with LoRA via Unsloth and
TRL's SFTTrainer.  Saves only the LoRA adapter weights, not the full
base model.

# THESIS NOTE: Both the QG and DG models use the same frozen Qwen3-4B
# base model with separate task-specific LoRA adapters. This demonstrates
# parameter-efficient multi-task adaptation — one base model, two
# specialised capabilities, total additional parameters approximately
# 0.1% of base model size per adapter.

Usage::

    python -m mcq.training.train_qg \\
        --data data/mcq_training/qg_formatted.jsonl \\
        --output models/mcq_qg/ \\
        --base-model unsloth/Qwen3-4B-Instruct \\
        --epochs 3 \\
        --batch-size 4 \\
        --rank 32
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TRAINING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

TRAIN_CONFIG = {
    "epochs": 3,
    # batch_size=4 + grad_accum=4 → effective batch 16.
    # With simplified system prompt and max_seq_length=1024, each T4 step
    # is ~2-3 min rather than the previous 10-12 h total.
    "batch_size": 4,
    "gradient_accumulation_steps": 4,
    "learning_rate": 2e-4,
    # Warmup is computed at runtime as 5% of total training steps.
    # The literal below is overridden in train_qg_model().
    "warmup_ratio": 0.05,
    "weight_decay": 0.01,
    "max_grad_norm": 1.0,
    # Simplified system prompt + compact user turn → avg ~450 tokens/sample.
    # 1024 is ample headroom and packs 2-3 samples per window.
    "max_seq_length": 1024,
    # QG: higher rank — must adhere to conditioning AND generate varied content
    "lora_r": 32,
    "lora_alpha": 64,
    "lora_dropout": 0.05,
    "load_in_4bit": True,
}


# ═══════════════════════════════════════════════════════════════════════════════
# STRATIFIED SPLIT
# ═══════════════════════════════════════════════════════════════════════════════


def _stratified_split(data_path: str, val_ratio: float = 0.1):
    """Shuffle then split data into train/val with stratification on question_type.

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

    # Shuffle before splitting so sequential order in the source file
    # does not bias the train/val split or batch composition.
    random.seed(42)
    random.shuffle(samples)

    if len(samples) < 10:
        split_idx = max(1, int(len(samples) * (1 - val_ratio)))
        return samples[:split_idx], samples[split_idx:]

    labels = [s.get("question_type", "unknown") for s in samples]

    if len(set(labels)) < 2:
        split_idx = max(1, int(len(samples) * (1 - val_ratio)))
        return samples[:split_idx], samples[split_idx:]

    train_samples, val_samples = train_test_split(
        samples, test_size=val_ratio, stratify=labels, random_state=42,
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
    """Generate on validation samples and compute ROUGE-L.

    Uses greedy decoding for deterministic output.
    """
    import re
    import torch
    from rouge_score import rouge_scorer

    from mcq.prompts.mcq_prompts import (
        extract_qg_output,
    )
    # Import the training-format message builder (not the full inference prompt)
    from mcq.training.format_qg import _build_qg_training_messages

    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)

    all_rouge1, all_rouge2, all_rougeL = [], [], []
    type_rougeL: dict[str, list[float]] = defaultdict(list)
    parse_success = 0
    parse_fail = 0

    eval_samples = val_samples[:max_samples]

    for sample in eval_samples:
        # Build the prompt/user turn only (no assistant turn) using the
        # same compact format used during training.
        messages_full = _build_qg_training_messages(sample)
        # Drop the assistant message to get just the prompt part
        messages_prompt = messages_full[:-1]

        try:
            # Qwen3: non-thinking mode for deterministic structured output
            input_text = tokenizer.apply_chat_template(
                messages_prompt,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        except TypeError:
            input_text = tokenizer.apply_chat_template(
                messages_prompt,
                tokenize=False,
                add_generation_prompt=True,
            )

        inputs = tokenizer(
            input_text,
            return_tensors="pt",
            truncation=True,
            max_length=TRAIN_CONFIG["max_seq_length"],
        )
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
        input_len = inputs["input_ids"].shape[1]

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=200,
                temperature=0.0,
                do_sample=False,
            )

        new_tokens = outputs[0][input_len:]
        gen_text = tokenizer.decode(new_tokens, skip_special_tokens=True)

        parsed = extract_qg_output(gen_text)
        if parsed:
            parse_success += 1
            ref_q = sample.get("question", "")
            ref_a = sample.get("correct_answer", "")
            ref_text = f"QUESTION: {ref_q} ANSWER: {ref_a}"
            gen_text_for_rouge = (
                f"QUESTION: {parsed['question']} ANSWER: {parsed['correct_answer']}"
            )

            scores = scorer.score(ref_text, gen_text_for_rouge)
            all_rouge1.append(scores["rouge1"].fmeasure)
            all_rouge2.append(scores["rouge2"].fmeasure)
            all_rougeL.append(scores["rougeL"].fmeasure)
            qt = sample.get("question_type", "unknown")
            type_rougeL[qt].append(scores["rougeL"].fmeasure)
        else:
            parse_fail += 1

    avg = lambda lst: round(sum(lst) / max(len(lst), 1), 4)

    return {
        "rouge1": avg(all_rouge1),
        "rouge2": avg(all_rouge2),
        "rougeL": avg(all_rougeL),
        "parse_success": parse_success,
        "parse_fail": parse_fail,
        "per_type_rougeL": {
            t: avg(v) for t, v in sorted(type_rougeL.items()) if v
        },
        "num_evaluated": len(eval_samples),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TRAINING LOOP
# ═══════════════════════════════════════════════════════════════════════════════


def train_qg_model(
    data_path: str,
    output_dir: str,
    base_model: str = "unsloth/Qwen3-4B-Instruct",
    epochs: int = TRAIN_CONFIG["epochs"],
    batch_size: int = TRAIN_CONFIG["batch_size"],
    learning_rate: float = TRAIN_CONFIG["learning_rate"],
    lora_r: int = TRAIN_CONFIG["lora_r"],
    lora_alpha: int = TRAIN_CONFIG["lora_alpha"],
    lora_dropout: float = TRAIN_CONFIG["lora_dropout"],
    max_seq_length: int = TRAIN_CONFIG["max_seq_length"],
    load_in_4bit: bool = TRAIN_CONFIG["load_in_4bit"],
) -> str:
    """Fine-tune the QG LoRA adapter with Unsloth + SFTTrainer.

    Parameters
    ----------
    data_path :
        Path to formatted qg_formatted.jsonl.
    output_dir :
        Directory to save LoRA adapter checkpoints.
    base_model :
        Base Qwen3-4B model identifier.
    epochs :
        Number of training epochs.
    batch_size :
        Per-device training batch size.
    learning_rate :
        Peak learning rate.
    lora_r :
        LoRA rank (QG default: 32).
    lora_alpha :
        LoRA alpha scaling factor (QG default: 64).
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

    grad_accum = TRAIN_CONFIG["gradient_accumulation_steps"]

    logger.info(
        "qg_training_start",
        base_model=base_model,
        lora_r=lora_r,
        lora_alpha=lora_alpha,
        load_in_4bit=load_in_4bit,
        max_seq_length=max_seq_length,
    )

    # ── Load base model with Unsloth ────────────────────────────────
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=base_model,
        max_seq_length=max_seq_length,
        load_in_4bit=load_in_4bit,
    )

    logger.info("qg_base_model_loaded", model=base_model)

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
        "qg_lora_applied",
        r=lora_r,
        alpha=lora_alpha,
        dropout=lora_dropout,
        trainable_params=sum(p.numel() for p in model.parameters() if p.requires_grad),
    )

    # ── Stratified split ────────────────────────────────────────────
    train_samples, val_samples = _stratified_split(data_path)
    train_split_path = str(out_path / "_train_split.jsonl")
    val_split_path   = str(out_path / "_val_split.jsonl")
    _write_split(train_samples, train_split_path)
    _write_split(val_samples,   val_split_path)

    logger.info(
        "qg_split_complete",
        train=len(train_samples),
        val=len(val_samples),
    )

    # ── Compute warmup steps (5% of total training steps) ──────────
    steps_per_epoch = math.ceil(len(train_samples) / (batch_size * grad_accum))
    total_steps     = steps_per_epoch * epochs
    warmup_steps    = max(1, round(TRAIN_CONFIG["warmup_ratio"] * total_steps))

    logger.info(
        "qg_warmup_computed",
        steps_per_epoch=steps_per_epoch,
        total_steps=total_steps,
        warmup_steps=warmup_steps,
    )

    # ── Build HuggingFace Datasets ──────────────────────────────────
    train_dataset = Dataset.from_list(train_samples)
    val_dataset   = Dataset.from_list(val_samples)

    # ── SFTTrainer configuration ────────────────────────────────────
    checkpoints_dir = str(out_path / "checkpoints")

    training_args = SFTConfig(
        output_dir=checkpoints_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=learning_rate,
        warmup_steps=warmup_steps,
        weight_decay=TRAIN_CONFIG["weight_decay"],
        max_grad_norm=TRAIN_CONFIG["max_grad_norm"],
        fp16=not torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False,
        bf16=torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False,
        # Epoch-based evaluation and saving.  With packing and 1024-token
        # sequences, one epoch is fast enough that per-epoch checkpoints are
        # manageable without filling the disk.
        eval_strategy="epoch",
        save_strategy="epoch",
        # Keep only the best 2 checkpoints to save disk space on Kaggle.
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        logging_steps=10,
        save_total_limit=2,
        report_to="none",
        seed=42,
        max_seq_length=max_seq_length,
        dataset_text_field="text",
        # packing=True pre-tokenises and packs multiple short samples into each
        # max_seq_length window.  Viability confirmed with simplified prompts
        # (~450 tokens/sample): 2-3 samples fit per 1024-token window.
        packing=True,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        args=training_args,
    )

    # ── Checkpoint resume ───────────────────────────────────────────
    # Scan for existing checkpoints and resume from the latest one.
    # This prevents load_best_model_at_end from crashing when the
    # resumed epoch produces a worse loss than a prior checkpoint —
    # the path must exist in the current session's output directory.
    resume_from = None
    ckpt_dir = Path(checkpoints_dir)
    if ckpt_dir.exists():
        ckpts = sorted(
            [d for d in ckpt_dir.iterdir() if d.is_dir() and d.name.startswith("checkpoint-")],
            key=lambda d: int(d.name.split("-")[-1]),
        )
        if ckpts:
            resume_from = str(ckpts[-1])
            logger.info("qg_resuming_from_checkpoint", checkpoint=resume_from)

    # ── Train ───────────────────────────────────────────────────────
    logger.info("qg_training_loop_starting", epochs=epochs)
    train_result = trainer.train(resume_from_checkpoint=resume_from)

    logger.info(
        "qg_training_loop_complete",
        train_loss=round(train_result.training_loss, 4),
    )

    # ── Save LoRA adapter ───────────────────────────────────────────
    adapter_path = str(out_path / "adapter")
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    logger.info("qg_lora_adapter_saved", path=adapter_path)

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
        "warmup_steps": warmup_steps,
        "total_steps": total_steps,
    }

    metrics_path = str(out_path / "training_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    # ── Print summary ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("QG LORA TRAINING COMPLETE")
    print("=" * 60)
    print(f"  Base model:        {base_model}")
    print(f"  LoRA rank:         {lora_r}  alpha: {lora_alpha}")
    print(f"  Training time:     {elapsed}s")
    print(f"  Train loss:        {round(train_result.training_loss, 4)}")
    print(f"  Final ROUGE-1:     {eval_results['rouge1']}")
    print(f"  Final ROUGE-2:     {eval_results['rouge2']}")
    print(f"  Final ROUGE-L:     {eval_results['rougeL']}")
    print(f"  Parse success:     {eval_results['parse_success']}/{eval_results['num_evaluated']}")
    print()
    print("  Per-type ROUGE-L:")
    for qtype, score in eval_results.get("per_type_rougeL", {}).items():
        print(f"    Type {qtype}: {score}")
    print()
    print(f"  Adapter saved to:  {adapter_path}")
    print(f"  Metrics saved to:  {metrics_path}")
    print("=" * 60 + "\n")

    logger.info("qg_training_complete", **metrics)
    return adapter_path


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        description="Fine-tune Qwen3-4B-Instruct with LoRA for MCQ question generation.",
    )
    parser.add_argument(
        "--data", required=True,
        help="Path to formatted qg_formatted.jsonl.",
    )
    parser.add_argument(
        "--output", required=True,
        help="Output directory for LoRA adapter and metrics.",
    )
    parser.add_argument(
        "--base-model", default="unsloth/Qwen3-4B-Instruct",
        help="Base model (default: unsloth/Qwen3-4B-Instruct).",
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

    train_qg_model(
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
