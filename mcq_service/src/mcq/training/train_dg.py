"""Train the Distractor Generation (DG) T5 model.

Fine-tunes a T5-base model on the formatted DG training data.
Identical architecture to train_qg.py but operates on distractor data.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog
import torch
from torch.utils.data import Dataset, DataLoader
from transformers import (
    T5ForConditionalGeneration,
    T5Tokenizer,
    get_linear_schedule_with_warmup,
)

logger = structlog.get_logger(__name__)


class DGDataset(Dataset):
    """T5 dataset for distractor generation training."""

    def __init__(self, data_path: str, tokenizer: T5Tokenizer, max_length: int = 512):
        self.samples: list[dict] = []
        self.tokenizer = tokenizer
        self.max_length = max_length

        with open(data_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        self.samples.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        logger.info("dg_dataset_loaded", samples=len(self.samples))

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> dict:
        sample = self.samples[idx]

        input_enc = self.tokenizer(
            sample["input_text"],
            max_length=self.max_length,
            truncation=True,
            padding="max_length",
            return_tensors="pt",
        )

        target_enc = self.tokenizer(
            sample["target_text"],
            max_length=self.max_length,
            truncation=True,
            padding="max_length",
            return_tensors="pt",
        )

        labels = target_enc["input_ids"].squeeze()
        labels[labels == self.tokenizer.pad_token_id] = -100

        return {
            "input_ids": input_enc["input_ids"].squeeze(),
            "attention_mask": input_enc["attention_mask"].squeeze(),
            "labels": labels,
        }


def train_dg_model(
    data_path: str,
    output_dir: str,
    base_model: str = "t5-base",
    epochs: int = 5,
    batch_size: int = 4,
    learning_rate: float = 3e-4,
    max_length: int = 512,
) -> str:
    """Fine-tune the DG T5 model.

    Parameters
    ----------
    data_path :
        Path to formatted dg_train.jsonl.
    output_dir :
        Directory to save the fine-tuned model.
    base_model :
        Base T5 model to fine-tune from.
    epochs :
        Number of training epochs.
    batch_size :
        Training batch size.
    learning_rate :
        Learning rate.
    max_length :
        Maximum token length for input/output.

    Returns
    -------
    str
        Path to saved model directory.
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("dg_training_start", device=str(device), base_model=base_model)

    tokenizer = T5Tokenizer.from_pretrained(base_model)
    model = T5ForConditionalGeneration.from_pretrained(base_model)
    model.to(device)

    dataset = DGDataset(data_path, tokenizer, max_length)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
    total_steps = len(dataloader) * epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=int(total_steps * 0.1),
        num_training_steps=total_steps,
    )

    model.train()
    for epoch in range(epochs):
        total_loss = 0.0
        for batch in dataloader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = batch["labels"].to(device)

            outputs = model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                labels=labels,
            )

            loss = outputs.loss
            total_loss += loss.item()

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()

        avg_loss = total_loss / len(dataloader)
        logger.info("dg_epoch_complete", epoch=epoch + 1, avg_loss=round(avg_loss, 4))

    # Save model
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out_path))
    tokenizer.save_pretrained(str(out_path))

    logger.info("dg_model_saved", path=str(out_path))
    return str(out_path)
