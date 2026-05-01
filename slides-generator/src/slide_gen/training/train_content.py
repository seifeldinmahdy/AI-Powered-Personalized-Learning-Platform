"""
Train Content Specialist — Fine-tune T5-Base on content generation.

Usage:
    python -m slide_gen.training.train_content \
        --data data/agent_training/content_train.jsonl \
        --output models/content_specialist/ \
        --epochs 5 \
        --batch-size 8
"""

import json
import argparse
from pathlib import Path

import torch
from torch.utils.data import Dataset, DataLoader
from transformers import (
    T5ForConditionalGeneration,
    T5Tokenizer,
    Trainer,
    TrainingArguments,
)


class ContentDataset(Dataset):
    """Dataset for T5 content specialist fine-tuning."""

    def __init__(self, data_path: str | Path, tokenizer, max_input_len=512, max_target_len=256):
        self.tokenizer = tokenizer
        self.max_input_len = max_input_len
        self.max_target_len = max_target_len
        self.examples = []

        with open(data_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    self.examples.append(json.loads(line))

        print(f"Loaded {len(self.examples)} training examples")

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        example = self.examples[idx]

        # Tokenize input
        input_enc = self.tokenizer(
            example["input"],
            max_length=self.max_input_len,
            truncation=True,
            padding="max_length",
            return_tensors="pt",
        )

        # Tokenize target
        target_enc = self.tokenizer(
            example["target"],
            max_length=self.max_target_len,
            truncation=True,
            padding="max_length",
            return_tensors="pt",
        )

        # Replace padding token ids with -100 so they're ignored by loss
        labels = target_enc["input_ids"].squeeze()
        labels[labels == self.tokenizer.pad_token_id] = -100

        return {
            "input_ids": input_enc["input_ids"].squeeze(),
            "attention_mask": input_enc["attention_mask"].squeeze(),
            "labels": labels,
        }


def train(
    data_path: str,
    output_dir: str,
    model_name: str = "t5-base",
    epochs: int = 5,
    batch_size: int = 8,
    learning_rate: float = 3e-4,
    warmup_steps: int = 100,
):
    """
    Fine-tune T5-Base on content generation data.

    Args:
        data_path: Path to content_train.jsonl
        output_dir: Directory to save the fine-tuned model
        model_name: Base model name
        epochs: Number of training epochs
        batch_size: Training batch size
        learning_rate: Learning rate
        warmup_steps: Warmup steps for scheduler
    """
    print(f"Loading model: {model_name}")
    tokenizer = T5Tokenizer.from_pretrained(model_name, legacy=True)
    model = T5ForConditionalGeneration.from_pretrained(model_name)

    print(f"Loading dataset: {data_path}")
    dataset = ContentDataset(data_path, tokenizer)

    # Split into train/val (90/10)
    train_size = int(0.9 * len(dataset))
    val_size = len(dataset) - train_size
    train_dataset, val_dataset = torch.utils.data.random_split(
        dataset, [train_size, val_size]
    )
    print(f"  Train: {train_size}, Val: {val_size}")

    # Training config
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        warmup_steps=warmup_steps,
        learning_rate=learning_rate,
        weight_decay=0.01,
        logging_dir=f"{output_dir}/logs",
        logging_steps=50,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        load_best_model_at_end=True,
        report_to="none",
        fp16=torch.cuda.is_available(),
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
    )

    print("\nStarting training...")
    trainer.train()

    print(f"\nSaving model to {output_dir}")
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    print("Done!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tune T5-Base for content generation")
    parser.add_argument("--data", "-d", required=True, help="Path to content_train.jsonl")
    parser.add_argument("--output", "-o", default="models/content_specialist/",
                        help="Output directory for fine-tuned model")
    parser.add_argument("--model", "-m", default="t5-base", help="Base model name")
    parser.add_argument("--epochs", type=int, default=5, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=8, help="Batch size")
    parser.add_argument("--lr", type=float, default=3e-4, help="Learning rate")

    args = parser.parse_args()
    train(args.data, args.output, args.model, args.epochs, args.batch_size, args.lr)
