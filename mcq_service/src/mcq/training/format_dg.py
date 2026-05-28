"""Format DG training data — converts raw JSONL into T5-ready input/target pairs.

Reads dg_training_data.jsonl and writes dg_train.jsonl with fields:
  - input_text: structured T5 prefix
  - target_text: JSON output the model should produce
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


def format_dg_data(
    input_path: str,
    output_path: str,
) -> int:
    """Convert raw DG training data to T5-ready format.

    Parameters
    ----------
    input_path :
        Path to dg_training_data.jsonl.
    output_path :
        Path to write formatted dg_train.jsonl.

    Returns
    -------
    int
        Number of formatted samples written.
    """
    in_p = Path(input_path)
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with open(in_p, "r", encoding="utf-8") as fin, \
         open(out_p, "w", encoding="utf-8") as fout:

        for line in fin:
            line = line.strip()
            if not line:
                continue

            try:
                sample = json.loads(line)
                formatted = {
                    "input_text": sample["input"],
                    "target_text": sample["output"],
                }
                fout.write(json.dumps(formatted) + "\n")
                count += 1
            except (json.JSONDecodeError, KeyError):
                logger.warning("format_dg_skip_invalid_line", line=line[:100])

    logger.info("format_dg_complete", samples=count, output=str(out_p))
    return count
